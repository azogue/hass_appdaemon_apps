# -*- coding: utf-8 -*-
"""
Automation task as a AppDaemon App for Home Assistant

AppDaemon App which posts any state change in one HASS instance (the local/main instance, as slave)
to another HASS instance (the master instance).
I prefer this method than config multiple REST sensors in the master HASS, with their customization & grouping.
Also, the master-slave configuration for multiple instances explained in docs looks like doesn't want to run for me (?),
and I don't need (nor want) to get master state updates in the slave instance,
so it's a one-way information pipe, **only from slave to master**, and it's better (=quicker response) than the REST
sensors because it doesn't depend of scan intervals in the master machine.

"""
import appdaemon.appapi as appapi
import homeassistant.remote as remote
import datetime as dt
from dateutil.parser import parse
from math import ceil


LOG_LEVEL = 'INFO'
DEFAULT_SUFFIX = '_slave'
DEFAULT_RAWBS_SECS_OFF = 10


# noinspection PyClassHasNoInit
class SlavePublisher(appapi.AppDaemon):
    """AppDaemon Class for setting states from one HASS instance (main) in Another (remote).
    Valid for binary_sensors and sensors."""
    _hass_master_url = None
    _hass_master_key = None
    _master_ha_api = None

    _sufix = None

    _raw_sensors = None
    _raw_sensors_sufix = None
    _raw_sensors_seconds_to_off = None
    _raw_sensors_last_states = {}
    _raw_sensors_attributes = {}

    def initialize(self):
        """AppDaemon required method for app init."""

        self._hass_master_url = self.args.get('master_ha_url')
        self._hass_master_key = self.args.get('master_ha_key', '')
        self._sufix = self.args.get('slave_sufix', DEFAULT_SUFFIX)
        self._master_ha_api = remote.API(self._hass_master_url, self._hass_master_key, port=8123)

        # Raw binary sensors
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
            # [self.set_state(dev, state='off', attributes=attrs) for dev, attrs in .._raw_sensors_attributes.values()]
            [remote.set_state(self._master_ha_api, dev + self._sufix, 'off', attributes=attrs)
             for dev, attrs in self._raw_sensors_attributes.values()]
            next_run = self.datetime() + dt.timedelta(seconds=self._raw_sensors_seconds_to_off)
            self.run_every(self._turn_off_raw_sensor_if_not_updated, next_run, self._raw_sensors_seconds_to_off)

        # Publish slave states in master
        bs_states = self.get_state('binary_sensor')
        # self.log('bs_states before raw filter: {}'.format(bs_states))
        if self._raw_sensors is not None:
            [bs_states.pop(raw) for raw in self._raw_sensors]
        # self.log('bs_states after raw filter: {}'.format(bs_states))

        s_states = self.get_state('sensor')
        sensors = dict(**s_states)
        sensors.update(bs_states)
        for entity_id, state_atts in sensors.items():
            # self.log('SENSOR: {}, ATTRS={}'.format(entity_id, state_atts))
            # self.log('--> sensor "{}": {}'.format(entity_id, state_atts['state']), level=LOG_LEVEL)
            remote.set_state(self._master_ha_api, entity_id + self._sufix,
                             state_atts['state'], attributes=state_atts['attributes'])
            self.listen_state(self._ch_state, entity_id, attributes=state_atts['attributes'])
        self.log('Transfer states from slave to master in {} COMPLETE'.format(self._master_ha_api))

    # noinspection PyUnusedLocal
    def _ch_state(self, entity, attribute, old, new, kwargs):
        remote.set_state(self._master_ha_api, entity + self._sufix, new, **kwargs)
        # self.log('STATE CHANGE: {} from "{}" to "{}"; attr={}; kw={}'.format(entity, old, new, attribute, kwargs))

    # noinspection PyUnusedLocal
    def _turn_on_raw_sensor_on_change(self, entity, attribute, old, new, kwargs):
        _, last_st = self._raw_sensors_last_states[entity]
        self._raw_sensors_last_states[entity] = [self.datetime(), True]
        if not last_st:
            name, attrs = self._raw_sensors_attributes[entity]
            # self.set_state(name, state='on', attributes=attrs)
            remote.set_state(self._master_ha_api, name + self._sufix, 'on', attributes=attrs)
            # self.log('TURN ON "{}" (de {} a {} --> {})'.format(entity, old, new, name))

    # noinspection PyUnusedLocal
    def _turn_off_raw_sensor_if_not_updated(self, *kwargs):
        now = self.datetime()
        for s, (ts, st) in self._raw_sensors_last_states.copy().items():
            if st and ceil((now - ts).total_seconds()) >= self._raw_sensors_seconds_to_off:
                # self.log('TURN OFF "{}" (last ch: {})'.format(s, ts))
                name, attrs = self._raw_sensors_attributes[s]
                self._raw_sensors_last_states[s] = [now, False]
                # self.set_state(name, state='off', attributes=attrs)
                remote.set_state(self._master_ha_api, name + self._sufix, 'off', attributes=attrs)
