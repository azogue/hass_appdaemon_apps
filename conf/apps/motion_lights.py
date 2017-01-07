# -*- coding: utf-8 -*-
"""
Automation task as a AppDaemon App for Home Assistant

This little app controls some hue lights for turning them ON with motion detection,
only under some custom circunstances, like the media player is not running,
or there aren't any more lights in 'on' state in the room.

"""
import appdaemon.appapi as appapi


LOG_LEVEL = 'DEBUG'


# noinspection PyClassHasNoInit
class MotionLights(appapi.AppDaemon):
    """App for control lights with a motion sensor."""

    _pir = None
    _motion_light_timeout = None
    _lights_motion = None
    _other_lights_room = None
    _media_player = None
    _extra_constrain_input_boolean = None

    _handle_motion_on = None
    _handle_motion_off = None

    _motion_lights_running = False
    _extra_condition = True
    _media_player_active = False
    _lights_motion_active = {}

    def initialize(self):
        """AppDaemon required method for app init."""
        conf_data = dict(self.config['AppDaemon'])
        pir = self.args.get('pir', None)
        self._extra_constrain_input_boolean = self.args.get('constrain_input_boolean_2', None)
        motion_light_timeout_slider = self.args.get('motion_light_timeout', None)
        self._lights_motion = self.args.get('lights_motion', '')
        self._other_lights_room = self.args.get('lights_check_off', '').split(',')
        self._media_player = conf_data.get('media_player', None)

        if pir and motion_light_timeout_slider and self._lights_motion:
            for l in self._lights_motion.split(','):
                self._lights_motion_active[l] = self.get_state(l) == 'on'
                self.listen_state(self._light_motion_state, l)
            self._motion_light_timeout = int(round(float(self.get_state(motion_light_timeout_slider))))
            self.listen_state(self._set_motion_timeout, motion_light_timeout_slider)
            self._pir = pir
            self._handle_motion_on = self.listen_state(self.turn_on_motion_lights, self._pir,
                                                       new="on", duration=2)
            # self.handle_motion_off = self.listen_state(self.motion_state_off, self.pir,
            #                                            new="off", duration=self.motion_light_timeout)
            if self._media_player is not None:
                self._media_player_active = self.get_state(self._media_player) == 'playing'
                self.listen_state(self._media_player_state_ch, self._media_player)

            if self._extra_constrain_input_boolean is not None:
                self._extra_condition = self.get_state(self._extra_constrain_input_boolean) == 'off'
                self.listen_state(self._extra_switch_change, self._extra_constrain_input_boolean)
        else:
            self.log('No se inicializa MotionLights, faltan parámetros (req: {})'
                     .format('motion_light_timeout, switch_light_motion, lights_motion, pir'), level='ERROR')

    # noinspection PyUnusedLocal
    def _media_player_state_ch(self, entity, attribute, old, new, kwargs):
        self.log('media_player_state_ch change: {} from {} to {}'.format(entity, old, new))
        self._media_player_active = new == 'playing'

    # noinspection PyUnusedLocal
    def _extra_switch_change(self, entity, attribute, old, new, kwargs):
        self.log('Extra switch condition change: {} from {} to {}'.format(entity, old, new))
        self._extra_condition = new == 'off'

    # noinspection PyUnusedLocal
    def _set_motion_timeout(self, entity, attribute, old, new, kwargs):
        self._motion_light_timeout = int(round(float(new)))
        self.log('Se establece nuevo timeout para MotionLights: {} segs'.format(self._motion_light_timeout))

    # noinspection PyUnusedLocal
    def _light_motion_state(self, entity, attribute, old, new, kwargs):
        # self.log('New state light {}, old={}, new={}'.format(entity, old, new))
        self._lights_motion_active[entity] = new == 'on'

    # noinspection PyUnusedLocal
    def turn_on_motion_lights(self, entity, attribute, old, new, kwargs):
        """Method for turning on the motion-controlled lights."""
        if (not self._motion_lights_running and not any(self._lights_motion_active.values()) and
                self._extra_condition and not self._media_player_active):
            self._motion_lights_running = True
            self.log('TURN_ON MOTION_LIGHTS ({}), with timeout: {} sec'
                     .format(self._lights_motion, self._motion_light_timeout), LOG_LEVEL)
            self.call_service("light/turn_on", entity_id=self._lights_motion,
                              color_temp=300, brightness=200, transition=0)
            if self._handle_motion_off is not None:
                self.log('Cancelling {}'.format(self._handle_motion_off))
                self.cancel_listen_state(self._handle_motion_off)
            self._handle_motion_off = self.listen_state(self.turn_off_motion_lights, self._pir,
                                                        new="off", duration=self._motion_light_timeout)

    # noinspection PyUnusedLocal
    def turn_off_motion_lights(self, entity, attribute, old, new, kwargs):
        """Method for turning off the motion-controlled lights after some time without any movement."""
        if self._motion_lights_running and self._extra_condition and not self._media_player_active:
            if all([(self.get_state(l) == 'off') or (self.get_state(l) is None) for l in self._other_lights_room]):
                self.log('TURNING_OFF MOTION_LIGHTS, id={}, old={}, new={}'.format(entity, old, new), LOG_LEVEL)
                self.call_service("light/turn_off", entity_id=self._lights_motion, transition=1)
            else:
                self.log('NO TURN_OFF MOTION_LIGHTS (other lights in the room are ON={})'
                         .format([self.get_state(l) for l in self._other_lights_room]), LOG_LEVEL)
            self.cancel_listen_state(self._handle_motion_off)
            self._handle_motion_off = None
        self._motion_lights_running = False
