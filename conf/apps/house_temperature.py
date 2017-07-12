# -*- coding: utf-8 -*-
"""
Automation task as a AppDaemon App for Home Assistant

App to monitor the temperature gradients in the house and around,
and to suggest natural ventilation and/or sunscreen control
"""
from collections import deque
import datetime as dt

import appdaemon.appapi as appapi
from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT, ATTR_FRIENDLY_NAME, ATTR_ATTRIBUTION,
    ATTR_ICON, ATTR_DEVICE_CLASS, TEMP_CELSIUS)

from common import get_global, GLOBAL_DEFAULT_CHATID


# TODO evolution and trend -> notify
DEFAULT_DEAD_BAND = 0.5  # ºC
DEFAULT_DELTA_EVOLUTION = 5400  # 1.5h
DEFAULT_FREQ_SAMPLING_SEC = 300  # 300 (5min)

BINARY_SENSOR_NAME = 'binary_sensor.close_house'
SENSOR_NAME = 'sensor.house_delta_temperature'

LOGLEVEL = 'INFO'


# noinspection PyClassHasNoInit
class HouseTemps(appapi.AppDaemon):
    """App for publishing binary_sensors turned on as changed in X seconds."""
    _house_zones = None
    _exterior_sensors = None
    _exterior_estimated = None
    _deadband = None
    _open_house = None

    _sampling_freq = None
    _len_history = None
    _num_samples = None

    _temperatures_int = None
    _temperatures_ext = None
    _temperatures_estimated = None

    def initialize(self):
        """AppDaemon required method for app init."""
        self._sampling_freq = self.args.get(
            'sampling_freq', DEFAULT_FREQ_SAMPLING_SEC)
        self._len_history = self.args.get(
            'delta_history', DEFAULT_DELTA_EVOLUTION)
        self._deadband = self.args.get('dead_band', DEFAULT_DEAD_BAND) / 2

        self._num_samples = self._len_history // self._sampling_freq
        self._house_zones = self.args.get('zones')
        self._exterior_sensors = self.args.get('exterior')
        self._exterior_estimated = self.args.get('exterior_estimated', {})

        self.log("HouseTemps evolution for {} sec ({} samples, freq: {} sec)"
                 .format(self._len_history, self._num_samples,
                         self._sampling_freq), LOGLEVEL)

        self._temperatures_int = {
            zone: {s: deque([self._get_float(s)], maxlen=self._num_samples)
                   for s in sensors}
            for zone, sensors in self._house_zones.items()}
        self._temperatures_ext = {
            s: deque([self._get_float(s)], maxlen=self._num_samples)
            for s in self._exterior_sensors}
        self._temperatures_estimated = {
            s: deque([self._get_float(s)], maxlen=self._num_samples)
            for s in self._exterior_estimated}

        self.log(str(self._temperatures_int), LOGLEVEL)
        self.log(str(self._temperatures_ext), LOGLEVEL)
        self.log(str(self._temperatures_estimated), LOGLEVEL)

        self.run_every(
            self._update_temps,
            self.datetime() + dt.timedelta(seconds=self._sampling_freq),
            self._sampling_freq)

        self._update_temps()

    def _get_float(self, entity_id):
        try:
            return float(self.get_state(entity_id))
        except (TypeError, ValueError):
            return None

    # def _process_deltas(self, deque1, deque2, index):
    #     return deque1[index] - deque2[index]

    # noinspection PyUnusedLocal
    def _update_temps(self, *args):
        notify_change = False

        # Collect temps for each zone
        zones = {}
        for zone, sensors in self._temperatures_int.items():
            [self._temperatures_int[zone][s].append(self._get_float(s))
             for s in sensors if self._get_float(s) is not None]

            values = [x[-1] for x in self._temperatures_int[zone].values()
                      if x is not None and x[-1] is not None]
            if not values:
                return
            num_s = len(values)
            # self.log(str(self._temperatures_int[zone].values()))
            mean_t = sum(values) / num_s
            # self.log("ZONE {} --> {:.1f} ºC ({} temps)"
            #          .format(zone, mean_t, num_s))
            zones[zone] = mean_t

        # Collect sensed exterior temps
        [self._temperatures_ext[s].append(self._get_float(s))
         for s in self._temperatures_ext if self._get_float(s) is not None]
        values = [x[-1] for x in self._temperatures_ext.values()]
        if not values:
            return
        num_s = len(values)
        mean_ext = sum(values) / num_s
        # self.log("EXTERIOR --> {:.1f} ºC ({} temps) --> {}"
        #          .format(mean_ext, num_s, self._temperatures_ext), LOGLEVEL)

        # Collect estimated exterior temps (weather services)
        [self._temperatures_estimated[s].append(self._get_float(s))
         for s in self._temperatures_estimated
         if self._get_float(s) is not None]
        values = [x[-1] for x in self._temperatures_estimated.values()]
        if not values:
            return
        num_s_est = len(values)
        mean_ext_est = sum(values) / num_s_est
        # self.log("EXTERIOR EST --> {:.1f} ºC ({} temps) --> {}"
        #          .format(mean_ext_est, num_s_est,
        #                  self._temperatures_estimated))

        # Eval instant deltas
        delta_est = round(mean_ext - mean_ext_est, 1)
        temp_house = round(sum(zones.values()) / len(zones), 1)
        delta_house = round(temp_house - mean_ext, 1)
        deltas_zones = {z: round(t - mean_ext, 1) for z, t in zones.items()}
        mean_ext = round(mean_ext, 1)

        assert (abs(delta_house) < 15)
        assert (abs(delta_est) < 25)

        # self.log("\nDELTAS:\n\tHOUSE --> {:.1f} ºC"
        #          "\n\tEXT_EST --> {:.1f} ºC"
        #          "\n\tZONES --> {}"
        #          .format(delta_house, delta_est, deltas_zones), LOGLEVEL)

        # Sensor state & attributes
        attrs = {
            "Interior": temp_house,
            "Exterior": mean_ext,
            "Exterior Est.": mean_ext_est,
            "∆T with estimated exterior": delta_est,
            ATTR_UNIT_OF_MEASUREMENT: TEMP_CELSIUS,
            ATTR_FRIENDLY_NAME: "Recalentamiento de casa",
            ATTR_ICON: "mdi:thermometer",
            ATTR_ATTRIBUTION: "Powered by AzogueLabs",
            "homebridge_hidden": True,
        }
        # Append deltas_zones
        [attrs.update({'Zona ' + z: delta})
         for z, delta in deltas_zones.items()]
        self.set_state(SENSOR_NAME, state=delta_house, attributes=attrs)

        # Decision logic (deadband)
        if self._open_house is None:
            # First value
            self._open_house = delta_house > 0
            self.log("Inicio de monitor de ventilación natural "
                     "(∆House: {} ºC, Apertura:{})"
                     .format(delta_house, self._open_house))
        elif self._open_house and delta_house < -self._deadband:
            self._open_house = False
            notify_change = True
        elif not self._open_house and delta_house > self._deadband:
            self._open_house = True
            notify_change = True

        if notify_change:  # TODO Enviar diagrama psicrométrico
            self.call_service('telegram_bot/send_message',
                              **self._make_notification(delta_house, attrs))
            self.log("Notificación de ventilación natural"
                     " (∆House: {} ºC, Apertura: {})"
                     .format(delta_house, self._open_house))

        # Binary sensor state & attributes
        bin_attrs = {
            "Interior": temp_house,
            "Exterior": mean_ext,
            "Exterior Est.": mean_ext_est,
            "∆T with exterior": delta_house,
            ATTR_FRIENDLY_NAME: "Apertura de ventanas",
            ATTR_DEVICE_CLASS: "opening",
            ATTR_ATTRIBUTION: "Powered by AzogueLabs",
        }
        self.set_state(BINARY_SENSOR_NAME,
                       state="on" if self._open_house else "off",
                       attributes=bin_attrs)

    def _make_notification(self, delta_house, attributes):
        temps_st = " Las temperaturas actuales son de *{:.1f} °C en " \
                   "el exterior* (estimados {:.1f} °C), y *{:.1f} °C " \
                   "en el interior*, ∆T={:.1f} °C. (∆ por zonas: {})"
        temps_st = temps_st.format(
            attributes["Exterior"], attributes["Exterior Est."],
            attributes["Interior"], delta_house,
            ', '.join(['{}:{:.1f}°C'.format(z[5:], delta)
                       for z, delta in attributes.items()
                       if z.startswith('Zona ')]))
        if self._open_house:
            title = "*Apertura de ventanas*"
            message = "_Se recomienda ventilar la casa " \
                      "para refrescarla_. "
        else:
            title = "*Cierre y oscurecimiento de ventanas*"
            message = "_Se recomienda aislar la casa lo máximo posible para " \
                      "evitar el recalentamiento gratuito_. "

        cmd_mask = 'Ventilador {}:/service_call ' \
                   'homeassistant/turn_{} switch.new_switch_2'
        return {"title": title,
                "message": message + temps_st,
                "inline_keyboard": [cmd_mask.format('ON', 'on'),
                                    cmd_mask.format('OFF', 'off')],
                "disable_notification": True,
                "target": get_global(self, GLOBAL_DEFAULT_CHATID)}
