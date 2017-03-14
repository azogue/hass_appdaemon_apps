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
NOTIF_MASK_ALARM_SILENT = "Se silencia la alarma a las {:%d/%m/%y %H:%M:%S}, desde '{}'."
NOTIF_MASK_ALARM_RESET = "Se ignora el estado de alarma, reset a las {:%d/%m/%y %H:%M:%S}, desde '{}'."
NOTIF_MASK_ALARM_OFF = "ALARMA DESCONECTADA en {:%d/%m/%y %H:%M:%S}, desde '{}'."
NOTIF_MASK_TOGGLE_AMB = "Cambio en modo Ambilight{:%d/%m/%y %H:%M:%S}, desde '{}'."
NOTIF_MASK_TOGGLE_AMB_CONF = "Cambio en configuración de Ambilight (# de bombillas) {:%d/%m/%y %H:%M:%S}, desde '{}'."
NOTIF_MASK_POSTPONE_ALARMCLOCK = "{:%d/%m/%y %H:%M:%S}: Postponer despertador (desde '{}')."
NOTIF_MASK_LAST_VALIDATION = "Last validation: {:%d/%m/%y %H:%M:%S}, from '{}'."


# noinspection PyClassHasNoInit
class EventListener(appapi.AppDaemon):
    """Event listener for ios.notification_action_fired."""

    _config = None
    _lights_notif = None
    _lights_notif_state = None
    _lights_notif_state_attrs = None
    _notifier = None

    # Family Tracker
    _devs_to_track = None
    _tracking_state = None

    # Alarm state
    _alarm_state = False

    # _sended_notifications = {}

    def initialize(self):
        """AppDaemon required method for app init."""
        self._config = dict(self.config['AppDaemon'])
        self._notifier = self._config.get('notifier').replace('.', '/')

        # self._lights_notif = 'light.cuenco,light.bola_grande'
        self._lights_notif = 'light.cuenco'
        self.listen_event(self.receive_event, 'ios.notification_action_fired')
        self.listen_event(self.receive_event, 'ios_iphone.notification_action_fired')
        # self.listen_event(self.new_event_service_call, 'call_service')
        # self.listen_event(self.new_event_service_call, 'service_executed')

        # Alarm mode controller
        self.listen_state(self.alarm_mode_controller, entity='input_select.alarm_mode')
        self.listen_state(self.alarm_mode_controller_master_switch, entity='switch.switch_master_alarm')
        self._alarm_state = self.get_state('switch.switch_master_alarm') == 'on'

        # Tracking:
        self._devs_to_track = self.get_state('group.family', attribute='attributes')['entity_id']
        # self._devs_to_track = self.get_state('group.eugenio', attribute='attributes')['entity_id']
        self._tracking_state = {dev: [self.get_state(dev), self.get_state(dev, attribute='last_changed')]
                                for dev in self._devs_to_track}
        [self.listen_state(self.track_zone_ch, dev, old="home", duration=10) for dev in self._tracking_state.keys()]
        [self.listen_state(self.track_zone_ch, dev, new="home", duration=10) for dev in self._tracking_state.keys()]
        self.log("**TRACKING STATE: {} -> {}".format(self._devs_to_track, self._tracking_state))

        # DEBUG:
        # self._test_notification_actions()

    # noinspection PyUnusedLocal
    def alarm_mode_controller(self, entity, attribute, old, new, kwargs):
        """Cambia el master switch cuando se utiliza el input_select"""
        self.log('ALARM_MODE_CONTROLLER {} -> {}'.format(old, new))
        if new == 'Desconectada':
            self._alarm_state = False
            self.turn_off("switch.switch_master_alarm")
        elif new == 'Fuera de casa':  # and (old == 'Desconectada'):
            self._alarm_state = True
            self.turn_on("switch.switch_master_alarm")
        # TODO modo vigilancia "en casa" / "fuera", "vacaciones"

    # noinspection PyUnusedLocal
    def alarm_mode_controller_master_switch(self, entity, attribute, old, new, kwargs):
        """Cambia el input_select cuando se utiliza el master switch"""
        self.log('ALARM_MODE_CONTROLLER_MASTER_SWITCH {} -> {}'.format(old, new))
        selected_mode = self.get_state('input_select.alarm_mode')
        if new == 'on':
            self._alarm_state = True
            if selected_mode == 'Desconectada':
                self.select_option("input_select.alarm_mode", option="Fuera de casa")
        elif new == 'off':
            self._alarm_state = False
            if selected_mode != 'Desconectada':
                self.select_option("input_select.alarm_mode", option="Desconectada")

    def _alguien_mas_en_casa(self, entity_exclude='no_excluir_nada'):
        res = any([x[0] == 'home' for k, x in self._tracking_state.items() if k != entity_exclude])
        if self._alarm_state:
            self.log('alguien_mas_en_casa? -> {}. De {}, excl={}'.format(res, self._tracking_state, entity_exclude))
        return res

    # noinspection PyUnusedLocal
    def track_zone_ch(self, entity, attribute, old, new, kwargs):
        last_st, last_ch = self._tracking_state[entity]
        self._tracking_state[entity] = [new, self.datetime()]
        if last_st != old:
            self.log('TRACKING_STATE_CHANGE "{}" from "{}" [!="{}", changed at {}] to "{}"'
                       .format(entity.lstrip('device_tracker.'), old, last_st, last_ch, new))
        else:
            self.log('TRACKING_STATE_CHANGE "{}" from "{}" [{}] to "{}"'
                     .format(entity.lstrip('device_tracker.'), old, last_ch, new))
            if (new == 'home') and not self._alguien_mas_en_casa():
                # Llegada a casa:
                # if self._alarm_state:
                data_msg = {"title": "Bienvenido a casa",
                            "message": "¿Qué puedo hacer por ti?",
                            "data": {"push": {"badge": 0, "category": "INHOME"}}}
                self.log('INHOME NOTIF: {}'.format(data_msg))
                self.call_service(self._notifier, **data_msg)
            elif (old == 'home') and not self._alguien_mas_en_casa() and not self._alarm_state:
                # Salida de casa:
                data_msg = {"title": "Vuelve pronto!",
                            "message": "¿Apagamos luces o encendemos alarma?",
                            "data": {"push": {"badge": 0, "category": "AWAY"}}}
                self.log('AWAY NOTIF: {}'.format(data_msg))
                self.call_service(self._notifier, **data_msg)

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
        if 'notification_action_fired' in event_id:
            action_name = payload_event['actionName']
            if action_name == 'com.apple.UNNotificationDefaultActionIdentifier':  # iOS Notification discard
                self.log('NOTIFICATION Discard: {} - Args={}, more={}'.format(event_id, payload_event, args))
            else:
                self.log('RESPONSE_TO_ACTION "{}" from dev="{}", otherArgs ={}'
                         .format(payload_event['actionName'], payload_event['sourceDeviceName'], payload_event))
                self.response_to_action(action_name, payload_event, *args)
        else:
            self.log('NOTIFICATION WTF: "{}", payload={}, otherArgs={}'.format(event_id, payload_event, args))

    def frontend_notif(self, action_name, payload_event, mask=DEFAULT_NOTIF_MASK, title=None):
        """Set a persistent_notification in frontend."""
        message = mask.format(dt.datetime.now(tz=conf.tz), payload_event['sourceDeviceName'], payload_event)
        self.persistent_notification(message, title=action_name if title is None else title, id=action_name)

    def _turn_off_lights_and_appliances(self, turn_off_heater=False):
        self.turn_off('group.all_lights', transition=2)
        self.turn_off("switch.calefactor")
        self.turn_off("switch.cocina")
        self.turn_off("switch.altavoz")
        self.turn_off("switch.kodi_tv_salon")
        if turn_off_heater:
            self.turn_off("switch.caldera")

    def response_to_action(self, action_name, payload_event, *args):
        """Respond to defined action events."""
        # AWAY category
        if action_name == 'ALARM_ARM_NOW':  # Activar alarma
            self.log('ACTIVANDO ALARMA')
            self.frontend_notif(action_name, payload_event, mask=NOTIF_MASK_ALARM_ON,
                                title='Activación remota de alarma')
            self._turn_off_lights_and_appliances()
            self.select_option("input_select.alarm_mode", option="Fuera de casa")
        elif action_name == 'ALARM_HOME':  # Activar vigilancia
            self.frontend_notif(action_name, payload_event, mask=NOTIF_MASK_ALARM_HOME,
                                title='Activación remota de vigilancia')
            self.log('ACTIVANDO VIGILANCIA SIMPLE')
            self._turn_off_lights_and_appliances()
            self.select_option("input_select.alarm_mode", option="En casa")
        elif action_name == 'LIGHTS_OFF':  # Apagar luces
            self.log('APAGANDO LUCES')
            self._turn_off_lights_and_appliances()

        # INHOME category
        elif action_name == 'WELCOME_HOME':  # Desactivar alarma, encender luces
            self.log(action_name)
            self.select_option("input_select.alarm_mode", option="Desconectada")
            self.turn_on("switch.cocina")
            self.call_service('light/hue_activate_scene', group_name="Salón", scene_name='Semáforo')
            self.frontend_notif(action_name, payload_event, mask=NOTIF_MASK_ALARM_OFF,
                                title='Llegando a casa, luces ON')
            self.log('*iOS Action "{}" received. ALARM OFF. Kitchen ON, "Semáforo"("Salón")'.format(action_name))
            self.light_flash(XY_COLORS['green'], persistence=2, n_flashes=2)
        elif action_name == 'WELCOME_HOME_TV':  # Desactivar alarma, encender luces
            self.select_option("input_select.alarm_mode", option="Desconectada")
            self.turn_on("switch.kodi_tv_salon")
            self.call_service('light/hue_activate_scene', group_name="Salón", scene_name='Aurora boreal')
            self.frontend_notif(action_name, payload_event, mask=NOTIF_MASK_ALARM_OFF,
                                title='Llegando a casa, tele ON')
            self.log('*iOS Action "{}" received. ALARM OFF. TV ON, "Aurora boreal"("Salón")'.format(action_name))
            self.light_flash(XY_COLORS['green'], persistence=2, n_flashes=2)
        elif action_name == 'IGNORE_HOME':  # Reset del estado de alarma
            self.fire_event('reset_alarm_state')
            self.frontend_notif(action_name, payload_event, mask=NOTIF_MASK_ALARM_RESET)
            self.log('*iOS Action "{}" received. reset_alarm_state & alarm continues ON'.format(action_name))

        elif action_name == 'ALARM_SILENT':  # Silenciar alarma (sólo la sirena)
            self.frontend_notif(action_name, payload_event, mask=NOTIF_MASK_ALARM_SILENT)
            self.fire_event('silent_alarm_state')
        elif action_name == 'ALARM_RESET':  # Ignorar armado y resetear
            self.fire_event('reset_alarm_state')
            self.frontend_notif(action_name, payload_event, mask=NOTIF_MASK_ALARM_RESET)
            self.log('*iOS Action "{}" received. reset_alarm_state & alarm continues ON'.format(action_name))
        elif action_name == 'ALARM_CANCEL':  # Desconectar alarma
            self.log('DESACTIVANDO ALARMA')
            self.frontend_notif(action_name, payload_event, mask=NOTIF_MASK_ALARM_OFF)
            self.select_option("input_select.alarm_mode", option="Desconectada")
            self.light_flash(XY_COLORS['green'], persistence=2, n_flashes=5)

        # CONFIRM category
        elif action_name == 'CONFIRM_OK':  # Validar
            self.frontend_notif(action_name, payload_event, mask=NOTIF_MASK_LAST_VALIDATION)
            self.light_flash(XY_COLORS['yellow'], persistence=3, n_flashes=1)

        # CAMERA category
        elif action_name == 'CAM_YES':  # Validar
            self.frontend_notif(action_name, payload_event)
            self.light_flash(XY_COLORS['green'], persistence=3, n_flashes=1)
        elif action_name == 'CAM_NO':  # Validar
            self.frontend_notif(action_name, payload_event)
            self.light_flash(XY_COLORS['red'], persistence=3, n_flashes=1)

        # KODIPLAY category
        elif action_name == 'LIGHTS_ON':  # Lights ON!
            self.call_service('input_slider/select_value', entity_id="input_slider.light_main_slider_salon", value=254)
            self.log('*iOS Action "{}" received. LIGHTS ON: LIGHT_MAIN_SLIDER_SALON -> 254'.format(action_name))
        elif action_name == 'HYPERION_TOGGLE':  # Toggle Ambilight
            self.frontend_notif(action_name, payload_event, mask=NOTIF_MASK_TOGGLE_AMB)
            self.toggle("switch.toggle_kodi_ambilight")
            self.log('*iOS Action "{}" received. TOGGLE_KODI_AMBILIGHT'.format(action_name))
            self.light_flash(XY_COLORS['blue'], persistence=2, n_flashes=2)
        elif action_name == 'HYPERION_CHANGE':  # Change Ambilight conf
            self.frontend_notif(action_name, payload_event, mask=NOTIF_MASK_TOGGLE_AMB_CONF)
            self.toggle("switch.toggle_config_kodi_ambilight")
            self.log('*iOS Action "{}" received. CHANGE AMBILIGHT CONF'.format(action_name))
            self.light_flash(XY_COLORS['violet'], persistence=2, n_flashes=2)

        # ALARMCLOCK category
        elif action_name == 'INIT_DAY':  # A la ducha: Luces Energy + Calefactor!
            self.frontend_notif(action_name, payload_event)
            self.call_service('light/hue_activate_scene', group_name="Dormitorio", scene_name='Energía')
            self.turn_on('switch.calefactor')
            self.log('*iOS Action "{}" received. A NEW DAY STARTS WITH A WARM SHOWER'.format(action_name))
        elif action_name == 'POSTPONE_ALARMCLOCK':  # Postponer despertador
            self.frontend_notif(action_name, payload_event, mask=NOTIF_MASK_POSTPONE_ALARMCLOCK)
            self.turn_off('input_boolean.manual_trigger_lacafetera')
            self.log('*iOS Action "{}" received. Dormilón!'.format(action_name))
            # TODO postponer_despertador listen_event en morning_alarm_clock
            self.fire_event("postponer_despertador", jam="true")
        elif action_name == 'ALARMCLOCK_OFF':  # Luces Energy
            self.frontend_notif(action_name, payload_event)
            self.turn_off('input_boolean.manual_trigger_lacafetera')

        # TODO EXECORDER category with textInput no funciona!
        elif action_name == 'INPUTORDER':  # Tell me ('textInput')
            self.frontend_notif(action_name, payload_event)
            self.light_flash(XY_COLORS['blue'], persistence=3, n_flashes=1)
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
                                          "category": category}}}
            self.log('TEST PUSH_CATEGORY {} --> {}'.format(category, data_msg))
            self.call_service(self._notifier, **data_msg)

        # noinspection PyUnusedLocal
        def _push_camera(*args):
            data_msg = {"title": "Test camera",
                        "message": "camera test iOS notif->{}".format(self._notifier),
                        "data": {"push": {"target": "28ab3a8f-3ff6-30cd-b93b-8bb854cbf483",
                                          "category": "camera",
                                          "hide-thumbnail": False},
                                 "entity_id": "camera.escam_qf001"}}  # "camera.picamera_salon"
            self.log('TEST PUSH_CAMERA --> {}'.format(data_msg))
            self.call_service(self._notifier, **data_msg)

        # self.run_in(_flash_color, 5, color='orange')
        # self.run_in(_push_camera, 2)
        # self.run_in(_push_category, 25, category='KODIPLAY', badge=1)
        # self.run_in(_push_category, 50, category='ALARMSOUNDED', badge=2)
        self.run_in(_push_category, 3, category='ALARMCLOCK', badge=3)
        self.run_in(_push_category, 60, category='AWAY', badge=3)
        self.run_in(_push_category, 120, category='INHOME', badge=3)
        # self.run_in(_push_category, 40, category='AWAY', badge=3)
        # self.run_in(_push_category, 60, category='INHOME', badge=3)
        # self.run_in(_push_category, 100, category='EXECORDER', badge=0)
