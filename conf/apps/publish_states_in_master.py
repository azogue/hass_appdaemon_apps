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

    _hass_master_url = None
    _hass_master_key = None
    _sufix = None
    _excluded = None
    _force_update_entities = None

    _ha_api = None
    _master_ha_api = None

    def initialize(self):
        """AppDaemon required method for app init."""
        self._hass_master_url = self.args.get('master_ha_url')
        self._hass_master_key = self.args.get('master_ha_key', '')
        self._sufix = self.args.get('slave_sufix', DEFAULT_SUFFIX)

        self._excluded = self.args.get('excluded', '').split(',')
        raw_entities = self.args.get('force_update_entities', '')
        self._force_update_entities = [e.rstrip().lstrip() for e in raw_entities.split(',')]

        self._master_ha_api = remote.API(self._hass_master_url, self._hass_master_key)

        # Publish slave states in master
        bs_states = self.get_state('binary_sensor')
        s_states = self.get_state('sensor')
        sensors = dict(**s_states)
        sensors.update(bs_states)
        for entity_id, state_atts in sensors.items():
            if not any([excl in entity_id for excl in self._excluded]):
                f_upd = entity_id in self._force_update_entities
                self.log('--> sensor "{}": {}, FU={}'.format(entity_id, state_atts['state'], f_upd), level=LOG_LEVEL)
                remote.set_state(self._master_ha_api, entity_id + self._sufix, state_atts['state'],
                                 attributes=state_atts['attributes'], force_update=f_upd)
                self.listen_state(self._ch_state, entity_id, attributes=state_atts['attributes'], force_update=f_upd)

        # Publish groups and logout group intersections --> append slave entities to master.group
        master_group_names = [g.entity_id for g in remote.get_states(self._master_ha_api)
                              if g.entity_id.startswith('group.')]
        s_states = self.get_state('group')
        for entity_id, state_atts in s_states.items():
            if not any([excl in entity_id for excl in self._excluded]):
                attrs = state_atts['attributes'].copy()
                attrs['entity_id'] = [e + self._sufix for e in attrs['entity_id']]
                if entity_id in master_group_names:  # Solape --> fusión
                    master_g = remote.get_state(self._master_ha_api, entity_id)
                    self.log('*** GROUP INTERSECT "{}". Master: {} + {}'
                             .format(entity_id, master_g.attributes['entity_id'], attrs['entity_id']), level=LOG_LEVEL)
                    # self.log('*** GROUP FUSION "{}". Master: {}; Slave: {}'
                    #         .format(entity_id, master_g.attributes['entity_id'], attrs['entity_id']), level=LOG_LEVEL)
                    # attrs['entity_id'] = master_g.attributes['entity_id'] + attrs['entity_id']
                    # remote.set_state(self._master_ha_api, entity_id, state_atts['state'], attributes=attrs)
                else:
                    self.log('* GROUP "{}" --> {}'.format(entity_id + self._sufix, attrs['entity_id']), level=LOG_LEVEL)
                    remote.set_state(self._master_ha_api, entity_id + self._sufix,
                                     state_atts['state'], attributes=attrs)
        self.log('Transfer states from slave to master in {} COMPLETE'.format(self._master_ha_api), level='INFO')

    # noinspection PyUnusedLocal
    def _ch_state(self, entity, attribute, old, new, kwargs):
        if 'force_update' in kwargs and kwargs['force_update']:
            # self.log('STATE CHANGE: {} from "{}" to "{}"; attr={}'.format(entity, old, new, attribute))
            remote.set_state(self._master_ha_api, entity + self._sufix, new,
                             attributes=self.get_state(entity, 'attributes'))
        else:
            remote.set_state(self._master_ha_api, entity + self._sufix, new, **kwargs)
