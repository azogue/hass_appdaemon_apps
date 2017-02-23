# -*- coding: utf-8 -*-
"""
Automation task as a AppDaemon App for Home Assistant

This little app has to control the alarm state of the house, sending notifications on alert & more.
This is a work in progress...

"""
import appdaemon.appapi as appapi
# from base64 import b64encode
from collections import OrderedDict
import datetime as dt
import dateutil.parser as parser
from functools import reduce
from jinja2 import Environment, FileSystemLoader
import os
import re
import requests
from time import time, sleep
# from asyncio import sleep
import yaml


DEFAULT_ESPERA_A_ARMADO_SEC = 10
DEFAULT_RESET_PREALARM_TIME_SEC = 15
DEFAULT_MIN_DELTA_SEC_EVENTS = 6
DEFAULT_DELTA_SECS_TRIGGER = 60
DEFAULT_NUM_MAX_EVENTOS_POR_INFORME = 15

PATH_WWW_USB = '/media/usb32'
DIR_INFORMES = 'alarm_reports'
DIR_CAPTURAS = 'eventos'

LOG_LEVEL = 'INFO'

# Paths
basedir = os.path.dirname(os.path.abspath(__file__))
homedir = os.path.abspath(os.path.join(basedir, '..', '..'))
config_dir = os.path.join(homedir, '.homeassistant')
PATH_KNOWN_DEV = os.path.join(config_dir, 'known_devices.yaml')
PATH_SECRETS = os.path.join(config_dir, 'secrets.yaml')
PATH_TEMPLATES = os.path.join(basedir, 'templates')
# PATH_WWW = os.path.join(config_dir, 'www')
PATH_REPORTS_USB = os.path.join(PATH_WWW_USB, DIR_INFORMES)
PATH_CAPTURES_USB = os.path.join(PATH_WWW_USB, DIR_CAPTURAS)

# Configuration
with open(PATH_SECRETS) as _file:
    SECRETS = yaml.load(_file.read())
EXTERNAL_IP = SECRETS['base_url']
EMAIL_TARGET = SECRETS['email_target']
PB_TARGET = SECRETS['pb_target']

# jinja2 template environment
JINJA2_ENV = Environment(loader=FileSystemLoader(PATH_TEMPLATES), trim_blocks=True)

# Leyenda de eventos:
EVENT_INICIO = "INICIO"
EVENT_ACTIVACION = "ACTIVACION"
EVENT_DESCONEXION = "DESCONEXION"
EVENT_PREALARMA = "PRE-ALARMA"
EVENT_ALARMA = "ALARMA"
EVENT_EN_ALARMA = "EN ALARMA (ACTIVACION)"
EVENT_ALARMA_ENCENDIDA = "ALARMA ENCENDIDA"
HASS_COLOR = '#58C1F0'
# Título, color, es_prioritario, subject_report
EVENT_TYPES = OrderedDict(zip([EVENT_INICIO, EVENT_ACTIVACION, EVENT_DESCONEXION, EVENT_PREALARMA,
                               EVENT_ALARMA, EVENT_EN_ALARMA, EVENT_ALARMA_ENCENDIDA],
                              [('Inicio del sistema', "#1393f0", 1, 'Informe de eventos'),
                               ('Activación de sistema', "#1393f0", 3, 'Informe de eventos'),
                               ('Desconexión de sistema', "#1393f0", 3, 'Informe de desconexión de alarma'),
                               ('PRE-ALARMA activada', "#f0aa28", 1, 'Informe de eventos'),
                               ('ALARMA!', "#f00a2d", 5, 'ALARMA ACTIVADA'),
                               ('en ALARMA', "#f0426a", 5, 'ALARMA ACTIVADA'),
                               ('Alarma encendida', "#f040aa", 0, 'ALARMA ACTIVADA')]))


# noinspection PyClassHasNoInit
class MotionAlarm(appapi.AppDaemon):
    """App for handle the main intrusion alarm."""
    _use_raw_cams_capture = False  # True para capturar directamente las IP cams, False para capturar a MotionEye
    _pirs = ['binary_sensor.pir_zona_1', 'binary_sensor.pir_zona_2']
    _camera_movs = ['binary_sensor.cam_mov_zona_1', 'binary_sensor.cam_mov_zona_2']
    _extra_sensors = ['binary_sensor.sound_sensor',
                      'binary_sensor.vibration_sensor']
    _use_pirs = ['input_boolean.use_pir_1', 'input_boolean.use_pir_2']
    _use_cams_movs = ['switch.motioncam_zona_1', 'switch.motioncam_zona_2']
    _use_extra_sensors = ['input_boolean.use_sound_sensor', 'input_boolean.use_vibration_sensor']

    _d_asign_switchs_inputs = {s: s_input for s_input, s in zip(_pirs + _camera_movs + _extra_sensors,
                                                                _use_pirs + _use_cams_movs + _use_extra_sensors)}
    _cameras = ['camera.cam_zona_1', 'camera.cam_zona_2']
    _cameras_data_foscam = [(SECRETS['foscam_cam_1_ip'], SECRETS['foscam_cam_1_user'], SECRETS['foscam_cam_1_pass']),
                            (SECRETS['foscam_cam_2_ip'], SECRETS['foscam_cam_2_user'], SECRETS['foscam_cam_2_pass'])]
    _cameras_data_meye = [SECRETS['motioneye_url_cam_1'], SECRETS['motioneye_url_cam_2']]
    _main_switch = 'input_boolean.switch_alarm'
    _rele_sirena = 'switch.rele_1'
    _rele_secundario = 'switch.rele_2'
    _led_act = 'switch.led'
    _pushbullet_input_boolean = 'input_boolean.pushbullet_notif'
    _silent_mode_switch = 'input_boolean.silent_mode'

    _tz = None
    _time_report = None
    _espera_a_armado_sec = None
    _reset_prealarm_time_sec = None
    _min_delta_sec_events = None
    _delta_secs_trigger = None
    _use_pushbullet = False
    _max_report_events = None

    _alarm_on = False
    _silent_mode = False
    _alarm_state = False
    _alarm_state_ts_trigger = None
    _alarm_state_entity_trigger = None
    _pre_alarm_on = False
    _pre_alarm_ts_trigger = None
    _pre_alarms = []
    _post_alarms = []
    _events_data = None
    _in_capture_mode = False
    _ts_lastcap = None
    _dict_use_inputs = None
    _dict_friendly_names = None
    _handler_periodic_trigger = None
    _handler_armado_alarma = None

    _known_devices = None

    def initialize(self):
        """AppDaemon required method for app init."""
        conf_data = dict(self.config['AppDaemon'])
        self._tz = conf_data.get('time_zone', None)
        # self.log('INIT w/conf_data: {}'.format(conf_data))

        # Hora de envío del informe diario de eventos detectados (si los ha habido)
        self._time_report = self.args.get('hora_informe', None)
        # Parámetro de tiempo de espera desde conexión a armado de alarma:
        self._espera_a_armado_sec = int(self.args.get('espera_a_armado_sec', DEFAULT_ESPERA_A_ARMADO_SEC))
        # Parámetro de tiempo de espera en pre-alarma para conectar la alarma si ocurre un nuevo evento:
        self._reset_prealarm_time_sec = int(self.args.get('reset_prealarm_time_sec', DEFAULT_RESET_PREALARM_TIME_SEC))
        # Segundos entre captura de eventos con la alarma conectada
        self._min_delta_sec_events = int(self.args.get('min_delta_sec_events', DEFAULT_MIN_DELTA_SEC_EVENTS))
        self._delta_secs_trigger = int(self.args.get('delta_secs_trigger', DEFAULT_DELTA_SECS_TRIGGER))
        # Número de eventos máximo a incluir por informe en email. Se limita eliminando eventos de baja prioridad
        self._max_report_events = int(self.args.get('num_max_eventos_por_informe', DEFAULT_NUM_MAX_EVENTOS_POR_INFORME))

        # Listen to main events:
        self.listen_event(self.receive_init_event, 'ha_started')
        self.listen_event(self.device_tracker_new_device, 'device_tracker_new_device')
        self._events_data = []

        # Main switches:
        self._alarm_on = self.get_state(self._main_switch) == 'on'
        self._use_pushbullet = self.get_state(self._pushbullet_input_boolean) == 'on'
        self._silent_mode = self.get_state(self._silent_mode_switch) == 'on'
        [self.listen_state(self._main_switch_ch, s)
         for s in [self._main_switch, self._pushbullet_input_boolean, self._silent_mode_switch]]

        # Switches input:
        self._dict_use_inputs = {s_input: self.get_state(s) == 'on'
                                 for s, s_input in zip(self._use_pirs + self._use_cams_movs + self._use_extra_sensors,
                                                       self._pirs + self._camera_movs + self._extra_sensors)}
        for s in self._use_pirs + self._use_cams_movs + self._use_extra_sensors:
            self.listen_state(self._switch_usar_input, s)

        # Create binary_sensors in camera_movs:
        for i, bs in enumerate(self._camera_movs):
            self.set_state(bs, state='off',
                           attributes=dict(friendly_name="Movimiento en Vídeo de Zona {}".format(i + 1)))

        # Movement detection
        # wait for binary_changing_sensors to load: TODO MEJORAR para no tener que meter esta pausa de espera...
        sleep(5)
        for s_mov in self._pirs + self._camera_movs + self._extra_sensors:
            self.listen_state(self._motion_detected, s_mov, new="on", duration=1)
        self._dict_friendly_names = {s: self.get_state(s, attribute='friendly_name')
                                     for s in self._pirs + self._camera_movs + self._extra_sensors}
        # self._dict_friendly_names.update({sensor.replace('_raw', ''): self._dict_friendly_names[sensor]
        #                                   for sensor in self._extra_sensors if sensor.endswith('_raw')})

        # Programación de informe de actividad
        if self._time_report is not None:
            time_alarm = reduce(lambda x, y: x.replace(**{y[1]: int(y[0])}),
                                zip(self._time_report.split(':'), ['hour', 'minute', 'second']),
                                self.datetime().replace(second=0, microsecond=0))
            self.run_daily(self._email_events_data, time_alarm.time())
            self.log('Creado timer para informe diario de eventos a las {} de cada día'.format(time_alarm.time()))

        # Notifica inicio
        self.receive_init_event('inicio_appdaemon', None)

    # TODO BT devices con eventos de entrada en escena, procesar si alarm_on
    # def device_is_near(self, event_id, payload_event, *args):
    #     """Event listener."""
    #     self.log('INIT_EVENT RECEIVED: "{}", payload={}, otherArgs={}'.format(event_id, payload_event, args))

    def _is_too_old(self, ts, delta_secs):
        if ts is None:
            return True
        else:
            now = dt.datetime.now(tz=self._tz)
            return (now - ts).total_seconds() > delta_secs

    # noinspection PyUnusedLocal
    def device_tracker_new_device(self, event_id, payload_event, *args):
        """Event listener."""
        self.log('* DEVICE_TRACKER_NEW_DEVICE RECEIVED * --> {}: {}'.format(payload_event['entity_id'], payload_event))
        # TODO listener for new detected bt device
        # self.append_event_data(dict(event_type=EVENT_INICIO))
        # self._text_notification()
        # self.listen_state(self._track_devices, payload_event['entity_id'])

    # noinspection PyUnusedLocal
    def receive_init_event(self, event_id, payload_event, *args):
        """Event listener."""
        self.log('* INIT_EVENT * RECEIVED: "{}", payload={}'.format(event_id, payload_event))
        self.append_event_data(dict(event_type=EVENT_INICIO))
        self._text_notification()
        # Reload known_devices from yaml file:
        with open(PATH_KNOWN_DEV) as f:
            new_known_devices = yaml.load(f.read())
        if self._known_devices is None:
            self.log('KNOWN_DEVICES: {}'.format(['{name} [{mac}]'.format(**v) for v in new_known_devices.values()]))
        else:
            if any([dev not in self._known_devices.keys() for dev in new_known_devices.keys()]):
                self.log('NEW KNOWN_DEVS: {}'.format(['{name} [{mac}]'.format(**dev_data)
                                                      for dev, dev_data in new_known_devices.items()
                                                      if dev not in new_known_devices.keys()]))
                # TODO fijar listener para new devices
                # self.listen_event(self.device_tracker_new_device, 'device_tracker_new_device')
        self._known_devices = new_known_devices

    def _make_event_path(self, event_type, id_cam):
        now = dt.datetime.now(tz=self._tz)
        ev_clean = re.sub('\(|\)', '', re.sub(':|-|\+| |\.', '_', event_type))
        name = 'evento_{}_cam{}_ts{:%Y%m%d_%H%M%S}.jpg'.format(ev_clean, id_cam, now)
        sub_dir = 'ts_{:%Y_%m_%d}'.format(now.date())
        base_path = os.path.join(PATH_CAPTURES_USB, sub_dir)
        if not os.path.exists(base_path):
            os.mkdir(base_path)
        url = '{}{}/{}/{}/{}'.format(EXTERNAL_IP, 'local', DIR_CAPTURAS, sub_dir, name)
        return name, os.path.join(base_path, name), url

    def _append_pic_to_data(self, data, event_type, index, ip, user=None, pwd=None):
        # Get PIC from IP cams or from MotionEye in LocalHost:
        pic, ok, retries = None, False, 0
        if user is not None:  # Get IP cams
            url = 'http://{}:88/cgi-bin/CGIProxy.fcgi'.format(ip)
            params = dict(cmd='snapPicture2', usr=user, pwd=pwd)
        else:  # Vía motioneye:
            url, params = ip, None
        while not ok and (retries < 10):
            try:
                r = requests.get(url, params=params, timeout=5)
                length = float(r.headers['Content-Length'])
                if r.ok and (r.headers['Content-type'] == 'image/jpeg') and (length > 10.):
                    pic = r.content
                    ok = True
                    if retries > 5:
                        self.log('CGI PIC OK CON {} INTENTOS: {}, length={}'
                                 .format(retries + 1, url, length), 'WARNING')
                    break
                elif not r.ok:
                    self.log('ERROR {} EN CGI PIC: {}, length={}'.format(r.status_code, url, length), 'WARNING')
            except requests.ConnectionError:
                self.log('ConnectionError EN CGI PIC en {}?{}'.format(url, params), 'ERROR')
                if retries > 0:
                    break
            except requests.Timeout:
                self.log('Timeout EN CGI PIC en {}?{}'.format(url, params), 'ERROR')
                if retries > 0:
                    break
            retries += 1
            sleep(.3)

        # Save PIC & (opc) b64 encode:
        name_pic, path_pic, url_pic = 'NONAME', None, None
        if ok:
            name_pic, path_pic, url_pic = self._make_event_path(event_type, index + 1)
            with open(path_pic, 'wb') as f:
                f.write(pic)
            # pic_b64 = b64encode(pic).decode()
            data['ok_img{}'.format(index + 1)] = True
        else:
            # pic_b64 = 'NOIMG'
            data['ok_img{}'.format(index + 1)] = False
            self.log('ERROR EN CAPTURE PIC con event_type: "{}"'.format(event_type))
        data['path_img{}'.format(index + 1)] = path_pic
        data['url_img{}'.format(index + 1)] = url_pic
        data['name_img{}'.format(index + 1)] = name_pic
        # data['base64_img{}'.format(index + 1)] = pic_b64

    def _append_state_to_data(self, data, entity, prefix):
        st = self.get_state(entity)
        ts = self.get_state(entity, attribute='last_changed')
        if ts:
            ts = '{:%-H:%M:%S %-d/%-m}'.format(parser.parse(ts).astimezone(self._tz))
        data[prefix + '_st'] = st
        data[prefix + '_ts'] = ts
        data[prefix + '_fn'] = self._dict_friendly_names[entity]

    # noinspection PyUnusedLocal
    def append_event_data(self, kwargs, *args):
        """Creación de eventos.
        params = dict(pir_1_st='ON', pir_2_st='OFF', cam_mov_1_st='OFF', cam_mov_2_st='ON',
                      pir_1_ts='ON', pir_2_ts='OFF', cam_mov_1_ts='OFF', cam_mov_2_ts='ON',
                      base64_img1=b64encode(bytes_img1).decode(),
                      base64_img2=b64encode(bytes_img2).decode())
        """
        event_type = kwargs.get('event_type')
        prioridad = EVENT_TYPES[event_type][2]
        if not self._in_capture_mode or self._is_too_old(self._ts_lastcap, 2 * self._min_delta_sec_events):
            self._in_capture_mode = True
            tic = time()
            now = dt.datetime.now(tz=self._tz)
            params = dict(ts=now, ts_event='{:%H:%M:%S}'.format(now),
                          event_type=event_type, event_color=EVENT_TYPES[event_type][1])

            # Binary sensors: PIR's, camera_movs, extra_sensors:
            for i, p in enumerate(self._pirs):
                mask_pirs = 'pir_{}'
                self._append_state_to_data(params, p, 'pir_{}'.format(i + 1))
            for i, cm in enumerate(self._camera_movs):
                self._append_state_to_data(params, cm, 'cam_mov_{}'.format(i + 1))
            for extra_s in self._extra_sensors:
                # extra_sensor_usar = extra_s.replace('_raw', '')
                self._append_state_to_data(params, extra_s, extra_s.split('.')[1])

            # image captures:
            if self._use_raw_cams_capture:
                for i, (ip, user, pwd) in enumerate(self._cameras_data_foscam):
                    self._append_pic_to_data(params, event_type, i, ip, user, pwd)
            else:  # Capturas a MotionEye
                for i, meye_url in enumerate(self._cameras_data_meye):
                    self._append_pic_to_data(params, event_type, i, meye_url, None, None)

            params['took'] = time() - tic
            params['incluir'] = True
            params['prioridad'] = prioridad
            self.log('Nuevo evento "{}" adquirido en {:.2f}s, con ts={}'
                     .format(event_type, params['took'], params['ts']))
            self._events_data.append(params)
            self._in_capture_mode = False
            self._ts_lastcap = now + dt.timedelta(seconds=params['took'])
        else:
            self.log('SOLAPAMIENTO DE LLAMADAS A APPEND_EVENT. "{}" con kwargs:{}'
                     .format(event_type, kwargs), 'WARNING')
            if prioridad > 1:
                self.run_in(self.append_event_data, 3, **kwargs)

    def _reset_session_data(self):
        self._in_capture_mode = False
        self._alarm_state = False
        self._alarm_state_ts_trigger = None
        self._alarm_state_entity_trigger = None
        self._pre_alarm_on = False
        self._pre_alarm_ts_trigger = None
        self._pre_alarms = []
        self._post_alarms = []
        self._handler_periodic_trigger = None

    # noinspection PyUnusedLocal
    def _armado_sistema(self, *args):
        self._handler_armado_alarma = None
        self._alarm_on = True
        self._reset_session_data()
        self.append_event_data(dict(event_type=EVENT_ACTIVACION))
        self._text_notification()

    # noinspection PyUnusedLocal
    def _main_switch_ch(self, entity, attribute, old, new, kwargs):
        if entity == self._main_switch:
            alarm_on = new == 'on'
            if alarm_on:
                # turn_on_alarm with delay
                self._handler_armado_alarma = self.run_in(self._armado_sistema, self._espera_a_armado_sec)
                self.log('--> ALARMA CONECTADA DENTRO DE {} SEGUNDOS'.format(self._espera_a_armado_sec))
            else:
                # turn_off_alarm
                if self._handler_armado_alarma is not None:
                    self.cancel_timer(self._handler_armado_alarma)
                    self._handler_armado_alarma = None
                self._alarm_on = False
                # Operación con relés en apagado de alarma:
                self.call_service('switch/turn_off', entity_id=self._rele_sirena)
                self.call_service('switch/turn_off', entity_id=self._rele_secundario)
                self.call_service('switch/turn_off', entity_id=self._led_act)
                # send & reset events
                if self._events_data:
                    self.append_event_data(dict(event_type=EVENT_DESCONEXION))
                    self._text_notification()
                    self._email_events_data()
                # reset ts alarm & pre-alarm
                self._reset_session_data()
                self.log('--> ALARMA DESCONECTADA')
        elif entity == self._pushbullet_input_boolean:
            self._use_pushbullet = new == 'on'
            self.log('SWITCH USAR PB NOTIFS: de "{}" a "{}" --> {}'.format(old, new, self._use_pushbullet))
        elif entity == self._silent_mode_switch:
            self._silent_mode = new == 'on'
            self.log('SILENT MODE: {}'.format(self._silent_mode))
        else:
            self.log('Entity unknown in _main_switch_ch: {} (from {} to {}, attrs={}'
                     .format(entity, old, new, attribute), 'ERROR')

    def _get_dict_use_inputs(self):
        dict_use_inputs = {s_input: self.get_state(s) == 'on'
                           for s, s_input in zip(self._use_pirs + self._use_cams_movs + self._use_extra_sensors,
                                                 self._pirs + self._camera_movs + self._extra_sensors)}
        # self.log('GOT DICT_USE_INPUT: {}'.format(dict_use_inputs))
        return dict_use_inputs

    # noinspection PyUnusedLocal
    def _switch_usar_input(self, entity, attribute, old, new, kwargs):
        k = self._d_asign_switchs_inputs[entity]
        if (new == 'on') and (old == 'off'):
            # Turn ON input
            self._dict_use_inputs[k] = True
        elif (new == 'off') and (old == 'on'):
            # Turn OFF input
            self._dict_use_inputs[k] = False
        self.log('SWITCH USAR INPUT "{}" from {} to {}'.format(entity, old, new))

    def _validate_input(self, entity):
        # DEBUGGING NEW SENSORS
        # if entity in self._extra_sensors:
        #     self.log('EXTRA SENSOR "{}": {}->{}'.format(entity, old, new))
        if self._alarm_on:
            if (entity in self._dict_use_inputs) and (self._dict_use_inputs[entity]):
                return True
        return False

    # noinspection PyUnusedLocal
    def _turn_off_prealarm(self, *args):
        if self._pre_alarm_on and not self._alarm_state:
            self._pre_alarm_ts_trigger = None
            self._pre_alarm_on = False
            self.call_service('switch/turn_off', entity_id=self._led_act)
            self.log('*PREALARMA DESACTIVADA*')

    # noinspection PyUnusedLocal
    def _motion_detected(self, entity, attribute, old, new, kwargs):
        if self._validate_input(entity):
            # Actualiza persistent_notification de entity en cualquier caso
            # self._persistent_notification(entity)
            now = dt.datetime.now(tz=self._tz)
            # self.log('DEBUG MOTION "{}": "{}"->"{}" at {:%H:%M:%S.%f}. A={}, ST_A={}, ST_PRE-A={}'
            #          .format(entity, old, new, now, self._alarm_on, self._alarm_state, self._pre_alarm_on))
            # Nuevo evento, con alarma conectada. Se ignora por ahora
            if self._alarm_state:
                self.log('(IN ALARM MODE) motion_detected in {}'.format(entity))
                self.call_service('switch/toggle', entity_id=self._led_act)
                if self._is_too_old(self._ts_lastcap, self._min_delta_sec_events):
                    self.append_event_data(dict(event_type=EVENT_EN_ALARMA))
                self._alarm_persistent_notification(entity, now)
            # Trigger ALARMA después de pre-alarma
            elif self._pre_alarm_on:
                self.log('**** ALARMA!! **** activada por "{}"'.format(entity), LOG_LEVEL)
                # self.turn_on_alarm()
                self._alarm_state_ts_trigger = now
                self._alarm_state_entity_trigger = entity
                self._alarm_state = True
                if self._handler_periodic_trigger is None:  # Sólo 1ª vez!
                    self.call_service('switch/turn_on', entity_id=self._rele_sirena)
                    if not self._silent_mode:
                        self.call_service('switch/turn_on', entity_id=self._rele_secundario)
                    self.append_event_data(dict(event_type=EVENT_ALARMA, send_events=True))
                    self._text_notification()
                    self._alarm_persistent_notification()
                    self._email_events_data()
                    # Empieza a grabar eventos periódicos cada DELTA_SECS_TRIGGER:
                    self._handler_periodic_trigger = self.run_in(self.periodic_capture_mode, self._delta_secs_trigger)
            # Dispara estado pre-alarma
            else:
                self.log('** PRE-ALARMA ** activada por "{}"'.format(entity), LOG_LEVEL)
                self._pre_alarm_ts_trigger = now
                self._pre_alarm_on = True
                self.run_in(self._turn_off_prealarm, self._reset_prealarm_time_sec)
                self._prealarm_persistent_notification(entity, now)
                self.append_event_data(dict(event_type=EVENT_PREALARMA))
                self.call_service('switch/turn_on', entity_id=self._led_act)

    # noinspection PyUnusedLocal
    def periodic_capture_mode(self, *args):
        if self._alarm_state and self._is_too_old(self._ts_lastcap, self._min_delta_sec_events):
            # self.log('EN PERIODIC_CAPTURE_MODE con ∆T={} s'.format(self._delta_secs_trigger))
            self.append_event_data(dict(event_type=EVENT_ALARMA_ENCENDIDA))
            self.run_in(self.periodic_capture_mode, self._delta_secs_trigger)
        elif self._alarm_state:
            self.log('POSTPONE PERIODIC CAPTURE MODE con ∆T={} s'.format(self._delta_secs_trigger))
            self.run_in(self.periodic_capture_mode, self._delta_secs_trigger)
        else:
            # self.log('STOP PERIODIC CAPTURE MODE')
            self._handler_periodic_trigger = None

    # def _persistent_notification(self, trigger_entity, ts, title=None, unique_id=True):
    #     f_name = notif_id = self._dict_friendly_names[trigger_entity]
    #     if not unique_id:
    #         notif_id += '_{:%y%m%d%H%M%S}'.format(ts)
    #     message = 'Activación a las {:%H:%M:%S de %d/%m/%Y} por "{}"'.format(ts, f_name)
    #     params = dict(message=message, title=title if title is not None else f_name, id=notif_id)
    #     self._post_alarms.append((self._dict_friendly_names[trigger_entity], '{:%H:%M:%S}'.format(ts)))
    #     self.persistent_notification(**params)
    #     # self.log('PERSISTENT NOTIFICATION: {}'.format(params))

    def _alarm_persistent_notification(self, trigger_entity=None, ts=None):
        if trigger_entity is not None:
            self._post_alarms.append((self._dict_friendly_names[trigger_entity], '{:%H:%M:%S}'.format(ts)))
        params_templ = dict(ts='{:%H:%M:%S}'.format(self._alarm_state_ts_trigger),
                            entity=self._dict_friendly_names[self._alarm_state_entity_trigger],
                            postalarms=self._post_alarms[::-1])
        message = JINJA2_ENV.get_template('persistent_notif_alarm.html').render(**params_templ)
        params = dict(message=message, title="ALARMA Activada", id='alarm')
        # self.log('DEBUG ALARM PERSISTENT NOTIFICATION: {}'.format(params))
        self.persistent_notification(**params)

    def _prealarm_persistent_notification(self, trigger_entity, ts):
        self._pre_alarms.append((self._dict_friendly_names[trigger_entity], '{:%H:%M:%S}'.format(ts)))
        message = JINJA2_ENV.get_template('persistent_notif_prealarm.html').render(prealarms=self._pre_alarms[::-1])
        params = dict(message=message, title="PRE-ALARMA Activada", id='prealarm')
        # self.log('DEBUG PRE-ALARM PERSISTENT NOTIFICATION: {}'.format(params))
        self.persistent_notification(**params)

    def _text_notification(self):
        if self._events_data:
            last_event = self._events_data[-1]
            event_type = last_event['event_type']
            pre_alarm_ts = '{:%H:%M:%S}'.format(self._pre_alarm_ts_trigger) if self._pre_alarm_ts_trigger else None
            alarm_ts = '{:%H:%M:%S}'.format(self._alarm_state_ts_trigger) if self._alarm_state_ts_trigger else None
            msg = JINJA2_ENV.get_template('raw_text_pbnotif.html').render(pre_alarm_ts=pre_alarm_ts, alarm_ts=alarm_ts,
                                                                          alarm_entity=self._alarm_state_entity_trigger,
                                                                          evento=last_event)
            msg_text = msg.replace('</pre>', '').replace('<pre>', '')
            params = dict(title=EVENT_TYPES[event_type][0], message=msg_text)
            if self._use_pushbullet:
                params.update(target=PB_TARGET)
                service = 'notify/pushbullet'
                self.log('PB RAW TEXT NOTIFICATION "{}"'.format(params['title']))
            else:
                params.update(target=EMAIL_TARGET)
                service = 'notify/rich_gmail'
                self.log('EMAIL RAW TEXT NOTIFICATION: {}'.format(params))
            self.call_service(service, **params)

    # noinspection PyUnusedLocal
    def _email_events_data(self, *args):

        def _count_included_events(evs):
            """Cuenta los eventos marcados para inclusión."""
            return len(list(filter(lambda x: x['incluir'], evs)))

        def _ok_num_events(evs, num_max, prioridad_filtro, logger):
            """Marca 'incluir' = False para eventos de prioridad < X, hasta reducir a num_max."""
            n_included = n_included_init = _count_included_events(evs)
            if n_included > num_max:
                # Filtrado eliminando eventos periódicos, después prealarmas
                i = len(evs) - 1
                while (i >= 0) and (n_included > num_max):
                    if evs[i]['prioridad'] < prioridad_filtro:
                        evs[i]['incluir'] = False
                        n_included -= 1
                    i -= 1
                logger('Filtrado de eventos con P < {} por exceso. De {}, quedan {} eventos.'
                       .format(prioridad_filtro, n_included_init, n_included))
            return n_included <= num_max

        tic = time()
        if self._events_data:
            # Filtrado de eventos de baja prioridad si hay demasiados
            ok_filter, prioridad_min = False, 1
            while (not _ok_num_events(self._events_data, self._max_report_events, prioridad_min, self.log)
                   and (prioridad_min <= 5)):
                self.log('Filtrado de eventos con P < {} por exceso. De {}, quedan {} eventos.'
                         .format(prioridad_min, len(self._events_data), _count_included_events(self._events_data)))
                prioridad_min += 1

            # Informe
            now = dt.datetime.now(tz=self._tz)
            report_name = 'report_{:%Y%m%d_%H%M%S}.html'.format(now)
            last_event = self._events_data[-1]
            color_title = last_event['event_color'] if EVENT_TYPES[last_event['event_type']][2] else HASS_COLOR
            url_local_path_report = '{}{}/{}/{}'.format(EXTERNAL_IP, 'local', DIR_INFORMES, report_name)
            title = EVENT_TYPES[last_event['event_type']][3]
            ts_title = '{:%-d-%-m-%Y}'.format(now.date())

            # Eventos e imágenes para email attachments (cid:#):
            eventos = self._events_data[::-1]
            counter_imgs, paths_imgs = 0, []
            for event in filter(lambda x: x['incluir'], eventos):
                event['id_img1'] = counter_imgs
                paths_imgs.append(event['path_img1'])
                event['id_img2'] = counter_imgs + 1
                paths_imgs.append(event['path_img2'])
                counter_imgs += 2

            # Render html reports for email & static server
            report_templ = JINJA2_ENV.get_template('report_template.html')
            params_templ = dict(title=title, ts_title=ts_title, color_title=color_title,
                                eventos=eventos, include_images_base64=False)
            html_email = report_templ.render(is_email=True, url_local_report=url_local_path_report, **params_templ)
            html_static = report_templ.render(is_email=False, **params_templ)

            path_disk_report = os.path.join(PATH_REPORTS_USB, report_name)
            try:
                with open(path_disk_report, 'w') as f:
                    f.write(html_static)
                self.log('INFORME POR EMAIL con {} eventos generado y guardado en {} en {:.2f} s'
                         .format(len(self._events_data), path_disk_report, time() - tic))
            except Exception as e:
                self.log('ERROR EN SAVE REPORT TO USB: {} [{}]'.format(e, e.__class__))
            self._events_data = []
            params = dict(title="{} - {}".format(title, ts_title),
                          message='No text!', data=dict(html=html_email, images=paths_imgs), target=EMAIL_TARGET)
            self.call_service('notify/rich_gmail', **params)
        else:
            self.log('Se solicita enviar eventos, pero no hay ninguno! --> {}'.format(self._events_data), 'ERROR')
