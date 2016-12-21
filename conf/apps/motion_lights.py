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

    extra_constrain_input_boolean = None
    pir = None
    motion_light_timeout = None
    lights_motion = None
    other_lights_room = None
    media_player = None

    handle_motion_on = None
    handle_motion_off = None

    motion_lights_running = False
    extra_condition = True
    media_player_active = False
    lights_motion_active = {}

    def initialize(self):
        """AppDaemon required method for app init."""
        pir = self.args.get('pir', None)
        self.extra_constrain_input_boolean = self.args.get('constrain_input_boolean_2', None)
        motion_light_timeout_slider = self.args.get('motion_light_timeout', None)
        self.lights_motion = self.args.get('lights_motion', '')
        g_all_lights = self.args.get('all_lights_group', 'group.light')
        all_lights = self.get_state(g_all_lights, 'attributes')['entity_id']
        self.other_lights_room = [l for l in all_lights if l not in self.lights_motion.split(',')]
        self.media_player = self.args.get('media_player', None)

        if pir and motion_light_timeout_slider and self.lights_motion:
            for l in self.lights_motion.split(','):
                self.lights_motion_active[l] = self.get_state(l) == 'on'
                self.listen_state(self._light_motion_state, l)
            self.motion_light_timeout = int(round(float(self.get_state(motion_light_timeout_slider))))
            self.listen_state(self._set_motion_timeout, motion_light_timeout_slider)
            self.pir = pir
            self.handle_motion_on = self.listen_state(self.turn_on_motion_lights, self.pir, new="on")
            # self.handle_motion_off = self.listen_state(self.motion_state_off, self.pir,
            #                                            new="off", duration=self.motion_light_timeout)
            if self.media_player is not None:
                self.media_player_active = self.get_state(self.media_player) == 'playing'
                self.listen_state(self._media_player_state_ch, self.media_player)

            if self.extra_constrain_input_boolean is not None:
                self.extra_condition = self.get_state(self.extra_constrain_input_boolean) == 'off'
                self.listen_state(self._extra_switch_change, self.extra_constrain_input_boolean)
        else:
            self.log('No se inicializa MotionLights, faltan parámetros (req: {})'
                     .format('motion_light_timeout, switch_light_motion, lights_motion, pir'), level='ERROR')

    # noinspection PyUnusedLocal
    def _media_player_state_ch(self, entity, attribute, old, new, kwargs):
        self.log('media_player_state_ch change: {} from {} to {}'.format(entity, old, new))
        self.media_player_active = new == 'playing'

    # noinspection PyUnusedLocal
    def _extra_switch_change(self, entity, attribute, old, new, kwargs):
        self.log('Extra switch condition change: {} from {} to {}'.format(entity, old, new))
        self.extra_condition = new == 'off'

    # noinspection PyUnusedLocal
    def _set_motion_timeout(self, entity, attribute, old, new, kwargs):
        self.motion_light_timeout = int(round(float(new)))
        self.log('Se establece nuevo timeout para MotionLights: {} segs'.format(self.motion_light_timeout))

    # noinspection PyUnusedLocal
    def _light_motion_state(self, entity, attribute, old, new, kwargs):
        # self.log('New state light {}, old={}, new={}'.format(entity, old, new))
        self.lights_motion_active[entity] = new == 'on'

    # noinspection PyUnusedLocal
    def turn_on_motion_lights(self, entity, attribute, old, new, kwargs):
        """Method for turning on the motion-controlled lights."""
        if (not self.motion_lights_running and not any(self.lights_motion_active.values()) and
                self.extra_condition and not self.media_player_active):
            self.motion_lights_running = True
            self.log('TURN_ON MOTION_LIGHTS ({}), with timeout: {} sec'
                     .format(self.lights_motion, self.motion_light_timeout), LOG_LEVEL)
            self.call_service("light/turn_on", entity_id=self.lights_motion,
                              color_temp=300, brightness=200, transition=0)
            if self.handle_motion_off is not None:
                self.log('Cancelling {}'.format(self.handle_motion_off))
                self.cancel_listen_state(self.handle_motion_off)
            self.handle_motion_off = self.listen_state(self.turn_off_motion_lights, self.pir,
                                                       new="off", duration=self.motion_light_timeout)

    # noinspection PyUnusedLocal
    def turn_off_motion_lights(self, entity, attribute, old, new, kwargs):
        """Method for turning off the motion-controlled lights after some time without any movement."""
        if self.motion_lights_running and self.extra_condition and not self.media_player_active:
            self.log('EN TURN_OFF MOTION_LIGHTS, other lights={}'
                     .format([self.get_state(l) for l in self.other_lights_room]), LOG_LEVEL)
            if all([self.get_state(l) == 'off' for l in self.other_lights_room]):
                self.log('TURNING_OFF MOTION_LIGHTS, id={}, old={}, new={}'.format(entity, old, new), LOG_LEVEL)
                self.call_service("light/turn_off", entity_id=self.lights_motion, transition=1)
            self.cancel_listen_state(self.handle_motion_off)
            self.handle_motion_off = None
        self.motion_lights_running = False
