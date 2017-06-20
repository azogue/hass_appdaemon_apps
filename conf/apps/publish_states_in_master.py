# -*- coding: utf-8 -*-
"""
Automation task as a AppDaemon App for Home Assistant

AppDaemon App which posts any state change in one HASS instance
(the local/main instance, as slave) to another HASS (the master instance).

I prefer this method than config multiple REST sensors in the master HASS,
with their customization & grouping.
Also, the master-slave configuration for multiple instances explained in docs
looks like doesn't want to run for me (?), and I don't need (nor want) to get
master state updates in the slave instance, so it's a one-way information
pipe, **only from slave to master**, and it's better (=quicker response) than
the REST sensors because it doesn't depend of scan intervals.

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
    """SlavePublisher.

    AppDaemon Class for setting states
    from one HASS instance (main) in Another (remote).
    Valid for binary_sensors and sensors."""

    _hass_master_url = None
    _hass_master_key = None
    _hass_master_port = None
    _master_ha_api = None

    _sufix = None
    _sensor_updates = None

    _raw_sensors = None
    _raw_sensors_sufix = None
    _raw_sensors_seconds_to_off = None
    _raw_sensors_last_states = {}
    _raw_sensors_attributes = {}

    def initialize(self):
        """AppDaemon required method for app init."""

        self._hass_master_url = self.args.get('master_ha_url')
        self._hass_master_key = self.args.get('master_ha_key', '')
        self._hass_master_port = int(self.args.get('master_ha_port', '8123'))
        self._sufix = self.args.get('slave_sufix', DEFAULT_SUFFIX)
        self._master_ha_api = remote.API(
            self._hass_master_url, self._hass_master_key,
            port=self._hass_master_port)

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
            self.log('seconds_to_off: {}'.format(self._raw_sensors_seconds_to_off))
            self.log('attributes_sensors: {}'.format(self._raw_sensors_attributes))
            self.log('last_changes: {}'.format(self._raw_sensors_last_states))
            # [self.set_state(dev, state='off', attributes=attrs) for dev, attrs in .._raw_sensors_attributes.values()]
            [remote.set_state(self._master_ha_api, dev + self._sufix, 'off', attributes=attrs)
             for dev, attrs in self._raw_sensors_attributes.values()]
            next_run = self.datetime() + dt.timedelta(seconds=self._raw_sensors_seconds_to_off)
            self.run_every(self._turn_off_raw_sensor_if_not_updated, next_run, self._raw_sensors_seconds_to_off)

        # Publish slave states in master
        bs_states = self.get_state('binary_sensor')
        if self._raw_sensors is not None:
            [bs_states.pop(raw) for raw in self._raw_sensors]

        s_states = self.get_state('sensor')
        sensors = dict(**s_states)
        sensors.update(bs_states)
        now = self.datetime()
        sensor_updates = {}
        for entity_id, state_atts in sensors.items():
            self.log('SENSOR: {}, ATTRS={}'.format(entity_id, state_atts))
            remote.set_state(self._master_ha_api, entity_id + self._sufix,
                             state_atts['state'],
                             attributes=state_atts['attributes'])
            self.listen_state(self._ch_state, entity_id,
                              attributes=state_atts['attributes'])
            sensor_updates.update({entity_id + self._sufix: now})
        self._sensor_updates = sensor_updates
        self.run_minutely(self._update_states, None)
        self.log('Transfer states from slave to master in {} COMPLETE'
                 .format(self._master_ha_api))

    # noinspection PyUnusedLocal
    def _update_states(self, kwargs):
        """Update states in master if they are not changed."""
        now = self.datetime()
        s_states = self.get_state('sensor')
        bs_states = self.get_state('binary_sensor')
        sensors = dict(**s_states)
        sensors.update(bs_states)
        for entity_id, state_atts in sensors.items():
            key = entity_id + self._sufix
            if key not in self._sensor_updates \
                    or (now - self._sensor_updates[key]).total_seconds() > 60:
                remote.set_state(
                    self._master_ha_api, key, state_atts['state'],
                    attributes=state_atts['attributes'])
                self._sensor_updates[key] = now

    # noinspection PyUnusedLocal
    def _ch_state(self, entity, attribute, old, new, kwargs):
        remote.set_state(
            self._master_ha_api, entity + self._sufix, new, **kwargs)
        self._sensor_updates[entity + self._sufix] = self.datetime()

    # noinspection PyUnusedLocal
    def _turn_on_raw_sensor_on_change(self, entity, attribute,
                                      old, new, kwargs):
        _, last_st = self._raw_sensors_last_states[entity]
        self._raw_sensors_last_states[entity] = [self.datetime(), True]
        if not last_st:
            name, attrs = self._raw_sensors_attributes[entity]
            remote.set_state(
                self._master_ha_api, name + self._sufix, 'on',
                attributes=attrs)

    # noinspection PyUnusedLocal
    def _turn_off_raw_sensor_if_not_updated(self, *kwargs):
        now = self.datetime()
        for s, (ts, st) in self._raw_sensors_last_states.copy().items():
            if st and ceil((now - ts).total_seconds()
                           ) >= self._raw_sensors_seconds_to_off:
                name, attrs = self._raw_sensors_attributes[s]
                self._raw_sensors_last_states[s] = [now, False]
                remote.set_state(
                    self._master_ha_api, name + self._sufix, 'off',
                    attributes=attrs)
