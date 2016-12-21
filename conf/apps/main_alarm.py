# -*- coding: utf-8 -*-
"""
Automation task as a AppDaemon App for Home Assistant

This little app has to control the alarm state of the house, sending notifications on alert & more.
This is a work in progress...

"""
import appdaemon.appapi as appapi
from itertools import cycle


LOG_LEVEL = 'DEBUG'
# LOG_LEVEL = 'INFO'
DEFAULT_ALARM_COLORS = [(255, 0, 0), (50, 0, 255)]


# noinspection PyClassHasNoInit
class MyAlarm(appapi.AppDaemon):
    """App for handle the main intrusion alarm."""
    pir = None
    camera = None
    light_notify = None
    alarm_lights = None
    notifier = None
    manual_trigger = None

    alarm_state = False
    camera_state = False
    cycle_colors = cycle(DEFAULT_ALARM_COLORS)

    def initialize(self):
        """AppDaemon required method for app init."""
        self.pir = self.args.get('pir')
        self.camera = self.args.get('camera', None)
        self.manual_trigger = self.args.get('manual_trigger', None)
        self.light_notify = self.args.get('light_notify', '')
        self.alarm_lights = self.args.get('lights_alarm', 'group.all_lights')
        self.listen_state(self._motion_detected, self.pir, new="on")
        if self.camera:
            self.listen_state(self._camera_state_change, self.camera)
        if self.manual_trigger:
            self.listen_state(self._manual_trigger_switch, self.manual_trigger)

    # noinspection PyUnusedLocal
    def _motion_detected(self, entity, attribute, old, new, kwargs):
        if not self.alarm_state:
            self.log('ALARM BY motion_detected in {}'.format(entity), LOG_LEVEL)
            self.turn_on_alarm()
            param_st = {'state': 'on'}
            self.set_state(self.manual_trigger, **param_st)

    # noinspection PyUnusedLocal
    def _camera_state_change(self, entity, attribute, old, new, kwargs):
        if not self.alarm_state:
            self.log('ALARM BY camera_state_change -> {}, attrs={}, old={}, new={}'
                     .format(entity, attribute, old, new), 'WARNING')
            self.camera_state = new

    # noinspection PyUnusedLocal
    def _manual_trigger_switch(self, entity, attribute, old, new, kwargs):
        self.log('manual_trigger_switch {}, "{}" -> "{}"'.format(entity, old, new), LOG_LEVEL)
        if (new == 'on') and not self.alarm_state:
            self.turn_on_alarm()
        elif (new == 'off') and self.alarm_state:
            self.turn_off_alarm()

    def turn_on_alarm(self):
        """Turn ON alarm state (Start flashing lights)."""
        self.log('TURN_ON_ALARM', 'INFO')
        self.alarm_state = True
        if self.manual_trigger is not None:
            self.call_service("input_boolean/turn_on", entity_id=self.manual_trigger)
        if self.light_notify is not None:
            self.call_service("light/turn_on", entity_id=self.light_notify, rgb_color=(200, 10, 20),
                              brightness=255, transition=0)
        self._flash()

    def turn_off_alarm(self):
        """Turn OFF alarm state."""
        self.log('TURN OFF ALARM', 'INFO')
        self.alarm_state = False
        if self.manual_trigger is not None:
            self.call_service("input_boolean/turn_off", entity_id=self.manual_trigger)
        self.call_service("light/turn_off", transition=0)
        if self.light_notify is not None:
            self.call_service("light/turn_on", entity_id=self.light_notify, rgb_color=(0, 255, 0),
                              brightness=255, transition=2)
        self.call_service("light/turn_on", entity_id=self.alarm_lights, rgb_color=(255, 255, 255),
                          brightness=255, transition=2)

    # noinspection PyUnusedLocal
    def _flash(self, *args):
        """Recursive method for flashing lights with cycling colors"""
        self.call_service("light/turn_on", entity_id=self.alarm_lights,
                          rgb_color=next(self.cycle_colors), brightness=255, transition=1)
        # self.call_service("light/turn_off", entity_id=light_id, transition=1)
        if self.alarm_state:
            self.run_in(self._flash, 3)
