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
    Valid for binary_sensors, sensors & groups."""

    _hass_url = None
    _hass_key = None

    _hass_master_ssl = None
    _hass_master_url = None
    _hass_master_key = None
    _sufix = None
    _excluded = None
    _force_update_entities = None

    _ha_api = None
    _master_ha_api = None

    def initialize(self):
        """AppDaemon required method for app init."""

        self._hass_master_ssl = self.args.get('master_ha_https', 'false') == 'true'
        self._hass_master_url = self.args.get('master_ha_url')
        self._hass_master_key = self.args.get('master_ha_key', '')
        self._sufix = self.args.get('slave_sufix', DEFAULT_SUFFIX)

        self._excluded = self.args.get('excluded', '')
        if self._excluded:
            self._excluded = self._excluded.split(',')
        self.log('EXCLUDED: {}'.format(self._excluded))
        self.log('EXCLUDED: {}'.format(self._excluded))
        raw_entities = self.args.get('force_update_entities', '')
        self._force_update_entities = [e.rstrip().lstrip() for e in raw_entities.split(',')]

        self._master_ha_api = remote.API(self._hass_master_url, self._hass_master_key,
                                         port=80 if self._hass_master_ssl else 8123,
                                         use_ssl=self._hass_master_ssl)

        # Publish slave states in master
        bs_states = self.get_state('binary_sensor')
        s_states = self.get_state('sensor')
        sensors = dict(**s_states)
        sensors.update(bs_states)
        for entity_id, state_atts in sensors.items():
            if state_atts and ('homebridge_hidden' in state_atts['attributes']):
                self.log('SENSOR: {}, hidden={}'.format(entity_id, state_atts['attributes']['homebridge_hidden']))
            else:
                self.log('SENSOR: {}, ATTRS={}'.format(entity_id, state_atts))
            if not self._excluded or not any([excl in entity_id for excl in self._excluded]):
                f_upd = entity_id in self._force_update_entities
                self.log('--> sensor "{}": {}, FU={}'.format(entity_id, state_atts['state'], f_upd), level=LOG_LEVEL)
                remote.set_state(self._master_ha_api, entity_id + self._sufix, state_atts['state'],
                                 attributes=state_atts['attributes'], force_update=f_upd)
                self.listen_state(self._ch_state, entity_id, attributes=state_atts['attributes'], force_update=f_upd)

        self.log('Transfer states from slave to master in {} COMPLETE'.format(self._master_ha_api), level='INFO')

    # noinspection PyUnusedLocal
    def _ch_state(self, entity, attribute, old, new, kwargs):
        if 'force_update' in kwargs and kwargs['force_update']:
            # self.log('STATE CHANGE: {} from "{}" to "{}"; attr={}'.format(entity, old, new, attribute))
            remote.set_state(self._master_ha_api, entity + self._sufix, new,
                             attributes=self.get_state(entity, 'attributes'))
        else:
            remote.set_state(self._master_ha_api, entity + self._sufix, new, **kwargs)
