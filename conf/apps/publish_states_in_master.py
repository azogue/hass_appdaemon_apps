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


LOG_LEVEL = 'INFO'
DEFAULT_SUFFIX = '_slave'


# noinspection PyClassHasNoInit
class SlavePublisher(appapi.AppDaemon):
    """AppDaemon Class for setting states from one HASS instance (main) in Another (remote).
    Valid for binary_sensors and sensors."""

    _hass_url = None
    _hass_key = None

    _hass_master_url = None
    _hass_master_key = None
    _sufix = None

    _ha_api = None
    _master_ha_api = None

    def initialize(self):
        """AppDaemon required method for app init."""

        self._hass_master_url = self.args.get('master_ha_url')
        self._hass_master_key = self.args.get('master_ha_key', '')
        self._sufix = self.args.get('slave_sufix', DEFAULT_SUFFIX)
        self._master_ha_api = remote.API(self._hass_master_url, self._hass_master_key, port=8123)

        # Publish slave states in master
        bs_states = self.get_state('binary_sensor')
        s_states = self.get_state('sensor')
        sensors = dict(**s_states)
        sensors.update(bs_states)
        for entity_id, state_atts in sensors.items():
            self.log('SENSOR: {}, ATTRS={}'.format(entity_id, state_atts))
            self.log('--> sensor "{}": {}'.format(entity_id, state_atts['state']), level=LOG_LEVEL)
            remote.set_state(self._master_ha_api, entity_id + self._sufix,
                             state_atts['state'], attributes=state_atts['attributes'])
            self.listen_state(self._ch_state, entity_id, attributes=state_atts['attributes'])
        self.log('Transfer states from slave to master in {} COMPLETE'.format(self._master_ha_api), level='INFO')

    # noinspection PyUnusedLocal
    def _ch_state(self, entity, attribute, old, new, kwargs):
        remote.set_state(self._master_ha_api, entity + self._sufix, new, **kwargs)
        # self.log('STATE CHANGE: {} from "{}" to "{}"; attr={}; kw={}'.format(entity, old, new, attribute, kwargs))
