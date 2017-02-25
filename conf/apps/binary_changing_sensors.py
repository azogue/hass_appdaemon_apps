# -*- coding: utf-8 -*-
"""
Automation task as a AppDaemon App for Home Assistant

Aplicación para generar binary_sensors que representan ON para cambio de estado en los últimos X segundos,
OFF si el último cambio es más antiguo, a partir de otros binary_sensors para los que se obvia el valor booleano y
se atiende a la antigüedad del mismo.

Los binary_sensors generados copian los atributos de los sensores "en bruto", y se nombran eliminando un sufijo
especificado, que deber estar contenido en el nombre de la entidad "en bruto". Ejemplo:

    "binary_sensor.my_sensor_raw" + sufijo "_raw" ---> "binary_sensor.my_sensor"

"""
import appdaemon.appapi as appapi
import datetime as dt
from dateutil.parser import parse
from math import ceil


DEFAULT_RAWBS_SECS_OFF = 10


# noinspection PyClassHasNoInit
class PublisherRawSensors(appapi.AppDaemon):
    """App for publishing binary_sensors turned on as changed in X seconds."""
    _raw_sensors = None
    _raw_sensors_sufix = None
    _raw_sensors_seconds_to_off = None
    _raw_sensors_last_states = {}
    _raw_sensors_attributes = {}

    def initialize(self):
        """AppDaemon required method for app init."""

        self._raw_sensors = self.args.get('raw_binary_sensors', None)
        if self._raw_sensors is not None:
            self._raw_sensors = self._raw_sensors.split(',')
            self._raw_sensors_sufix = self.args.get('raw_binary_sensors_sufijo', '_raw')
            # Persistencia en segundos de último valor hasta considerarlos 'off'
            self._raw_sensors_seconds_to_off = int(self.args.get('raw_binary_sensors_time_off', DEFAULT_RAWBS_SECS_OFF))

            # Handlers de cambio en raw binary_sensors:
            l1, l2 = 'attributes', 'last_changed'
            for s in self._raw_sensors:
                self._raw_sensors_attributes[s] = (s.replace(self._raw_sensors_sufix, ''), self.get_state(s, l1))
                self._raw_sensors_last_states[s] = [parse(self.get_state(s, l2)).replace(tzinfo=None), False]
                self.listen_state(self._turn_on_raw_sensor_on_change, s)
            # self.log('seconds_to_off: {}'.format(self._raw_sensors_seconds_to_off))
            # self.log('attributes_sensors: {}'.format(self._raw_sensors_attributes))
            # self.log('last_changes: {}'.format(self._raw_sensors_last_states))
            [self.set_state(dev, state='off', attributes=attrs) for dev, attrs in self._raw_sensors_attributes.values()]
            next_run = self.datetime() + dt.timedelta(seconds=self._raw_sensors_seconds_to_off)
            self.run_every(self._turn_off_raw_sensor_if_not_updated, next_run, self._raw_sensors_seconds_to_off)

    # noinspection PyUnusedLocal
    def _turn_on_raw_sensor_on_change(self, entity, attribute, old, new, kwargs):
        _, last_st = self._raw_sensors_last_states[entity]
        self._raw_sensors_last_states[entity] = [self.datetime(), True]
        if not last_st:
            name, attrs = self._raw_sensors_attributes[entity]
            self.set_state(name, state='on', attributes=attrs)
            self.log('TURN ON "{}" (de {} a {} --> {})'.format(entity, old, new, name))

    # noinspection PyUnusedLocal
    def _turn_off_raw_sensor_if_not_updated(self, *kwargs):
        now = self.datetime()
        for s, (ts, st) in self._raw_sensors_last_states.copy().items():
            if st and ceil((now - ts).total_seconds()) >= self._raw_sensors_seconds_to_off:
                self.log('TURN OFF "{}" (last ch: {})'.format(s, ts))
                name, attrs = self._raw_sensors_attributes[s]
                self._raw_sensors_last_states[s] = [now, False]
                self.set_state(name, state='off', attributes=attrs)
