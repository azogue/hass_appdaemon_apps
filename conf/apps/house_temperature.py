# -*- coding: utf-8 -*-
"""
Automation task as a AppDaemon App for Home Assistant

"""
from collections import deque
import datetime as dt

import appdaemon.appapi as appapi
from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT, ATTR_FRIENDLY_NAME, ATTR_ATTRIBUTION,
    ATTR_STATE, ATTR_ICON, ATTR_DEVICE_CLASS, TEMP_CELSIUS)


DEFAULT_FREQ_SAMPLING_SEC = 300  # 300 (5min)
DEFAULT_DELTA_EVOLUTION = 5400  # 1.5h

BINARY_SENSOR_NAME = 'binary_sensor.close_house'
SENSOR_NAME = 'sensor.house_delta_temperature'

LOGLEVEL = 'INFO'
BAD_VALUE = -1000


# noinspection PyClassHasNoInit
class HouseTemps(appapi.AppDaemon):
    """App for publishing binary_sensors turned on as changed in X seconds."""
    _house_zones = None
    _exterior_sensors = None
    _exterior_estimated = None

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
        except TypeError:
            return
        except ValueError:
            return BAD_VALUE

    # def _process_deltas(self, deque1, deque2, index):
    #     return deque1[index] - deque2[index]

    # noinspection PyUnusedLocal
    def _update_temps(self, *args):
        # self.log("DEBUG: {}".format(args))

        # Collect temps for each zone
        zones = {}
        for zone, sensors in self._temperatures_int.items():
            [self._temperatures_int[zone][s].append(self._get_float(s))
             for s in sensors]
            values = [x[-1] for x in self._temperatures_int[zone].values()
                      if x != BAD_VALUE]
            num_s = len(values)
            # self.log(str(self._temperatures_int[zone].values()))
            mean_t = sum(values) / num_s
            # self.log("ZONE {} --> {:.1f} ºC ({} temps)"
            #          .format(zone, mean_t, num_s))
            zones[zone] = mean_t

        # Collect sensed exterior temps
        [self._temperatures_ext[s].append(self._get_float(s))
         for s in self._temperatures_ext]
        values = [x[-1] for x in self._temperatures_ext.values()
                  if x != BAD_VALUE]
        num_s = len(values)
        mean_ext = sum(values) / num_s
        # self.log("EXTERIOR --> {:.1f} ºC ({} temps) --> {}"
        #          .format(mean_ext, num_s, self._temperatures_ext), LOGLEVEL)

        # Collect estimated exterior temps (weather services)
        [self._temperatures_estimated[s].append(self._get_float(s))
         for s in self._temperatures_estimated]
        values = [x[-1] for x in self._temperatures_estimated.values()
                  if x != BAD_VALUE]
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
            ATTR_FRIENDLY_NAME: "Salto de temperaturas",
            # TODO icono chulo
            ATTR_ICON: "mdi:thermometer",
            ATTR_ATTRIBUTION: "Powered by AzogueLabs",
        }
        # Append deltas_zones
        [attrs.update({'Zona ' + z: delta})
         for z, delta in deltas_zones.items()]
        self.set_state(SENSOR_NAME,
                       state=delta_house, attributes=attrs)

        # Binary sensor state & attributes
        # TODO terminar

        bin_attrs = {
            "Interior": temp_house,
            "Exterior": mean_ext,
            "Exterior Est.": mean_ext_est,
            "∆T with exterior": delta_house,
            ATTR_FRIENDLY_NAME: "Cierre de ventanas y persianas",
            ATTR_DEVICE_CLASS: "opening",
            ATTR_ATTRIBUTION: "Powered by AzogueLabs",
        }
        self.set_state(BINARY_SENSOR_NAME,
                       state="on" if delta_house > 0 else "off",
                       attributes=bin_attrs)

