# -*- coding: utf-8 -*-
"""
Automation task as a AppDaemon App for Home Assistant

Event listener for actions triggered from iOS notifications.
Harcoded custom logic for controlling HA with feedback from iOS notification actions.

"""
import appdaemon.appapi as appapi
import appdaemon.conf as conf
import datetime as dt


LOG_LEVEL = 'INFO'

XY_COLORS = {"red": [0.6736, 0.3221], "blue": [0.1684, 0.0416], "orange": [0.5825, 0.3901],
             "yellow": [0.4925, 0.4833], "green": [0.4084, 0.5168], "violet": [0.3425, 0.1383]}

DEFAULT_NOTIF_MASK = "Recibido en {:%d/%m/%y %H:%M:%S} desde {}. Raw: {}."
NOTIF_MASK_ALARM_ON = "ALARMA CONECTADA en {:%d/%m/%y %H:%M:%S}, desde '{}'."
NOTIF_MASK_ALARM_HOME = "Vigilancia conectada en casa a las {:%d/%m/%y %H:%M:%S}, desde '{}'."
NOTIF_MASK_ALARM_OFF = "ALARMA DESCONECTADA en {:%d/%m/%y %H:%M:%S}, desde '{}'."
NOTIF_MASK_TOGGLE_AMB = "Ambilight toggle {:%d/%m/%y %H:%M:%S}, from '{}'."
NOTIF_MASK_TOGGLE_AMB_CONF = "Ambilight configuration toggle {:%d/%m/%y %H:%M:%S}, from '{}'."
NOTIF_MASK_LAST_VALIDATION = "Last validation: {:%d/%m/%y %H:%M:%S}, from '{}'."


# noinspection PyClassHasNoInit
class EventListener(appapi.AppDaemon):
    """Event listener for ios.notification_action_fired."""

    _config = None
    _lights_notif = None
    _lights_notif_state = None
    _lights_notif_state_attrs = None
    _notifier = None

    def initialize(self):
        """AppDaemon required method for app init."""
        self._config = dict(self.config['AppDaemon'])
        self._notifier = self._config.get('notifier', None)

        # self._lights_notif = 'light.cuenco,light.bola_grande'
        self._lights_notif = 'light.cuenco'
        self.listen_event(self.receive_event, 'ios.notification_action_fired')

        # DEBUG:
        # self._test_notification_actions()

    def light_flash(self, xy_color, persistence=5, n_flashes=3):
        """Flash hue lights as visual notification."""

        def _turn_on(*args_runin):
            self.call_service('light/turn_on', **args_runin[0])

        def _turn_off(*args_runin):
            self.call_service('light/turn_off', **args_runin[0])

        # noinspection PyUnusedLocal
        def _restore_state(*args):
            for light, st, attrs in zip(self._lights_notif.split(','),
                                        self._lights_notif_state, self._lights_notif_state_attrs):
                if st == 'on':
                    self.call_service('light/turn_on', entity_id=light, transition=1,
                                      xy_color=attrs['xy_color'], brightness=attrs['brightness'])
                else:
                    self.call_service('light/turn_off', entity_id=light, transition=1)

        # Get prev state:
        self._lights_notif_state = [self.get_state(l) for l in self._lights_notif.split(',')]
        self._lights_notif_state_attrs = [self.get_state(l, 'attributes') for l in self._lights_notif.split(',')]
        self.log('Flashing "{}" {} times, persistence={}s.'.format(self._lights_notif, n_flashes, persistence))

        # Loop ON-OFF
        self.call_service('light/turn_off', entity_id=self._lights_notif, transition=0)
        self.call_service('light/turn_on', entity_id=self._lights_notif, transition=1,
                          xy_color=xy_color, brightness=254)
        run_in = 2
        for i in range(1, n_flashes):
            self.run_in(_turn_off, run_in, entity_id=self._lights_notif, transition=1)
            self.run_in(_turn_on, run_in + 2, entity_id=self._lights_notif,
                        xy_color=xy_color, transition=1, brightness=254)
            run_in += 4

        # Restore state
        self.run_in(_restore_state, run_in + persistence - 2, entity_id=self._lights_notif, transition=1)

    def receive_event(self, event_id, payload_event, *args):
        """Event listener."""
        if event_id == 'ios.notification_action_fired':
            action_name = payload_event['actionName']
            if action_name == 'com.apple.UNNotificationDefaultActionIdentifier':  # iOS Notification discard
                self.log('NOTIFICATION Discard: Args={}, more={}'.format(payload_event, args))
            else:
                self.response_to_action(action_name, payload_event, *args)
                self.log('NOTIFICATION actionName="{}" from dev="{}", otherArgs ={}'
                         .format(payload_event['actionName'], payload_event['sourceDeviceName'], payload_event))
        else:
            self.log('NOTIFICATION WTF: "{}", payload={}, otherArgs={}'.format(event_id, payload_event, args))

    def frontend_notif(self, action_name, payload_event, mask=DEFAULT_NOTIF_MASK):
        """Set a persistent_notification in frontend."""
        message = mask.format(dt.datetime.now(tz=conf.tz), payload_event['sourceDeviceName'], payload_event)
        params_frontend_notif = {"notification_id": action_name, "title": action_name, "message": message}
        self.call_service('persistent_notification/create', **params_frontend_notif)

    # TODO terminar feedback de iOS Notifications
    def response_to_action(self, action_name, payload_event, *args):
        """Respond to defined action events."""

        # AWAY category
        if action_name == 'ALARM_ARM_NOW':  # Activar alarma
            self.log('ACTIVANDO ALARMA')
            self.frontend_notif(action_name, payload_event, mask=NOTIF_MASK_ALARM_ON)
            self.call_service('light/turn_off', transition=2)
            params = {"entity_id": "input_select.alarm_mode", "option": "Fuera de casa"}
            self.call_service('input_select/select_option', **params)
        elif action_name == 'ALARM_HOME':  # Activar vigilancia
            self.frontend_notif(action_name, payload_event, mask=NOTIF_MASK_ALARM_HOME)
            self.log('ACTIVANDO VIGILANCIA SIMPLE')
            params = {"entity_id": "input_select.alarm_mode", "option": "En casa"}
            self.call_service('input_select/select_option', **params)
        elif action_name == 'LIGHTS_OFF':  # Apagar luces
            self.log('APAGANDO LUCES')
            self.call_service('light/turn_off', transition=2)
        elif action_name == 'NOTHING':  # No hacer nada
            self.log('DOING NOTHING')

        # TODO ALARMSOUNDED category
        elif action_name == 'TRIGGER_ALARM':  # ALARMA!
            self.frontend_notif(action_name, payload_event)
        elif action_name == 'ALARM_SLEEP':  # Ignorar
            self.frontend_notif(action_name, payload_event)
        elif action_name == 'ALARM_CANCEL':  # Desconectar alarma
            self.log('DESACTIVANDO ALARMA')
            self.frontend_notif(action_name, payload_event, mask=NOTIF_MASK_ALARM_OFF)
            params = {"entity_id": "input_select.alarm_mode", "option": "Desconectada"}
            self.call_service('input_select/select_option', **params)
            self.light_flash(XY_COLORS['green'], persistence=2, n_flashes=5)

        # CONFIRM category
        elif action_name == 'CONFIRM_OK':  # Validar
            self.frontend_notif(action_name, payload_event, mask=NOTIF_MASK_LAST_VALIDATION)
            self.light_flash(XY_COLORS['yellow'], persistence=3, n_flashes=1)

        # KODIPLAY category
        elif action_name == 'LIGHTS_ON':  # Lights ON!
            self.log('Lights ON!')
            self.call_service('input_slider/select_value', entity_id="input_slider.light_main_slider_salon", value=254)
        elif action_name == 'HYPERION_TOGGLE':  # Toggle Ambilight
            self.log('TOGGLE AMBILIGHT')
            self.frontend_notif(action_name, payload_event, mask=NOTIF_MASK_TOGGLE_AMB)
            self.call_service('switch/toggle', entity_id="switch.toggle_kodi_ambilight")
        elif action_name == 'HYPERION_CHANGE':  # Change Ambilight conf
            self.log('CHANGE AMBILIGHT CONF')
            self.frontend_notif(action_name, payload_event, mask=NOTIF_MASK_TOGGLE_AMB_CONF)
            selected = self.get_state(entity_id='input_select.salon_movie_mode')
            self.log('DEBUG STATE INPUT_SELECT: "{}"'.format(selected))
            if selected == 'Ambilight Day (4)':
                params = {"entity_id": "input_select.salon_movie_mode", "option": "Ambilight Night (6)"}
                self.call_service('input_select/select_option', **params)
            elif selected == 'Ambilight Night (6)':
                params = {"entity_id": "input_select.salon_movie_mode", "option": "Ambilight Day (4)"}
                self.call_service('input_select/select_option', **params)
            else:  # Activate
                self.call_service('switch/turn_on', entity_id="switch.toggle_kodi_ambilight")

        # TODO ALARM category
        elif action_name == 'SOUND_ALARM':  # Sound Alarm!
            self.frontend_notif(action_name, payload_event)
        elif action_name == 'SILENCE_ALARM':  # Silence Alarm ('textInput')
            self.frontend_notif(action_name, payload_event)

        # TODO OTHER category
        elif action_name == 'OTHERSOUNDALARM':  # Sound Alarm
            self.frontend_notif(action_name, payload_event)
        elif action_name == 'OTHERSILENCEALARM':  # Silence Alarm
            self.frontend_notif(action_name, payload_event)

        # TODO EXECORDER category with textInput
        elif action_name == 'INPUTORDER':  # Tell me ('textInput')
            self.frontend_notif(action_name, payload_event)
        # Unrecognized cat
        else:
            self.log('NOTIFICATION WTF: "{}", payload={}, otherArgs={}'.format(action_name, payload_event, args))
            self.frontend_notif(action_name, payload_event)

    # debug
    def _test_notification_actions(self):

        def _flash_color(args):
            self.light_flash(XY_COLORS[args['color']], persistence=3, n_flashes=1)

        # noinspection PyUnusedLocal
        def _push_category(args):
            category = args['category']
            data_msg = {"title": "Test {}".format(category),
                        "message": "{} test iOS notif->{}".format(category, self._notifier),
                        "data": {"push": {"badge": args['badge'],
                                          # "target": "28ab3a8f-3ff6-30cd-b93b-8bb854cbf483",
                                          "category": category}}}
            self.log('TEST PUSH_CATEGORY {} --> {}'.format(category, data_msg))
            self.call_service(self._notifier.replace('.', '/'), **data_msg)

        # noinspection PyUnusedLocal
        def _push_camera(*args):
            data_msg = {"title": "Test camera",
                        "message": "camera test iOS notif->{}".format(self._notifier),
                        "data": {"push": {"target": "28ab3a8f-3ff6-30cd-b93b-8bb854cbf483",
                                          "category": "camera",
                                          "hide-thumbnail": False},
                                 "entity_id": "camera.escam_qf001"}}  # "camera.picamera_salon"
            self.log('TEST PUSH_CAMERA --> {}'.format(data_msg))
            self.call_service(self._notifier.replace('.', '/'), **data_msg)

        # self.run_in(_flash_color, 5, color='orange')
        self.run_in(_push_camera, 2)
        # self.run_in(_push_category, 25, category='KODIPLAY', badge=1)
        # self.run_in(_push_category, 50, category='ALARMSOUNDED', badge=2)
        self.run_in(_push_category, 10, category='AWAY', badge=3)
        # self.run_in(_push_category, 100, category='EXECORDER', badge=0)
