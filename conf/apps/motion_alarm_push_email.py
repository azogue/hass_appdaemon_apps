
# -*- coding: utf-8 -*-
"""
# Alarma de activación por detección de movimiento.

Activada con estímulos en sensores binarios (PIR's, de sonido, vibración, inclinación, movimiento en cámaras),
zonificación con cámaras y sensores asociados a cada zona, para la captura de eventos que se envían como html por
email, además de emitir notificaciones push para los eventos típicos de activación, alarma, desactivación e inicio.

Ante estímulos de los sensores de movimiento, genera "eventos" con el estado de los sensores y capturas jpg de
las cámaras asociadas. Estos eventos, tipificados, forman los informes generados, que se guardan en disco para estar
disponibles por el servidor web de HomeAssistant como ficheros locales.

En el disparo de alarma, activa 2 relés (sirena y opcional), si la alarma no está definida como "silenciosa", en cuyo
caso opera igualmente, excepto por el encendido de los relés asociados.

Los tiempos de espera a armado, periodo de pre-alarma, ∆T min entre eventos, ∆T para la captura periódica de eventos
en estado de alarma, y el # máximo de eventos (con imágenes) en los informes (para reducir el peso de los emails),
son editables en la configuración de la AppDaemon app:

```
    [Alarm]
    module = motion_alarm_push_email
    class = MotionAlarm


    # Hora de envío del informe diario de eventos detectados (si los ha habido). Comentar con # para desactivar
    hora_informe = 07:30
    # Parámetro de tiempo de espera desde conexión a armado de alarma:
    espera_a_armado_sec = 20
    # Parámetro de tiempo de espera en pre-alarma para conectar la alarma si ocurre un nuevo evento:
    reset_prealarm_time_sec = 15
    # Segundos entre captura de eventos con la alarma conectada
    min_delta_sec_events = 3
    delta_secs_trigger = 150
    # Número de eventos máx. a incluir por informe en correo electrónico. Se limita eliminando eventos de baja prioridad
    num_max_eventos_por_informe = 10
```

"""
import appdaemon.appapi as appapi
import appdaemon.conf as conf
# import asyncio
# from base64 import b64encode
from collections import OrderedDict
import datetime as dt
from dateutil.parser import parse
from functools import reduce
from itertools import cycle
from jinja2 import Environment, FileSystemLoader
import json
from math import ceil
import os
import re
import requests
from time import time, sleep
import yaml


# LOG_LEVEL = 'DEBUG'
LOG_LEVEL = 'INFO'

NUM_RETRIES_MAX_GET_JPG_FROM_CAM = 10
BYTES_MIN_FOR_JPG = 10.
MIN_TIME_BETWEEN_MOTION = 1  # secs

DEFAULT_RAWBS_SECS_OFF = 5
DEFAULT_ESPERA_A_ARMADO_SEC = 10
DEFAULT_RESET_PREALARM_TIME_SEC = 15
DEFAULT_MIN_DELTA_SEC_EVENTS = 6
DEFAULT_DELTA_SECS_TRIGGER = 60
DEFAULT_NUM_MAX_EVENTOS_POR_INFORME = 15
DIR_INFORMES = 'alarm_reports'
DIR_CAPTURAS = 'eventos'

# jinja2 template environment
basedir = os.path.dirname(os.path.abspath(__file__))
PATH_TEMPLATES = os.path.join(basedir, 'templates')
JINJA2_ENV = Environment(loader=FileSystemLoader(PATH_TEMPLATES), trim_blocks=True)

# Leyenda de eventos:
EVENT_INICIO = "INICIO"
EVENT_ACTIVACION = "ACTIVACION"
EVENT_DESCONEXION = "DESCONEXION"
EVENT_PREALARMA = "PRE-ALARMA"
EVENT_ALARMA = "ALARMA"
EVENT_EN_ALARMA = "EN ALARMA (ACTIVACION)"
EVENT_ALARMA_ENCENDIDA = "ALARMA ENCENDIDA"
AVISO_RETRY_ALARMA_ENCENDIDA_TITLE = "ALARMA ENCENDIDA"
AVISO_RETRY_ALARMA_ENCENDIDA_MSG = "La alarma sigue encendida, desde las {:%H:%M:%S}. {}"
HASS_COLOR = '#58C1F0'
DEFAULT_ALARM_COLORS = [(255, 0, 0), (50, 0, 255)]  # para cycle en luces RGB (simulación de sirena)
# Título, color, es_prioritario, subject_report
EVENT_TYPES = OrderedDict(zip([EVENT_INICIO, EVENT_ACTIVACION, EVENT_DESCONEXION, EVENT_PREALARMA,
                               EVENT_ALARMA, EVENT_EN_ALARMA, EVENT_ALARMA_ENCENDIDA],
                              [('Inicio del sistema', "#1393f0", 1, 'Informe de eventos'),
                               ('Activación de sistema', "#1393f0", 3, 'Informe de eventos'),
                               ('Desconexión de sistema', "#1393f0", 3, 'Informe de desconexión de alarma'),
                               ('PRE-ALARMA', "#f0aa28", 1, 'Informe de eventos'),
                               ('ALARMA!', "#f00a2d", 10, 'ALARMA ACTIVADA'),
                               ('en ALARMA', "#f0426a", 5, 'ALARMA ACTIVADA'),
                               ('Alarma encendida', "#f040aa", 0, 'ALARMA ACTIVADA')]))
SOUND_MOTION = "US-EN-Morgan-Freeman-Motion-Detected.wav"


def _read_hass_secret_conf(path_ha_conf):
    """Read config values from secrets.yaml file & get also the known_devices.yaml path"""
    path_secrets = os.path.join(path_ha_conf, 'secrets.yaml')
    path_known_dev = os.path.join(path_ha_conf, 'known_devices.yaml')
    with open(path_secrets) as _file:
        secrets = yaml.load(_file.read())
    return dict(secrets=secrets, hass_base_url=secrets['base_url'], path_known_dev=path_known_dev,
                email_target=secrets['email_target'], pb_target=secrets['pb_target'])


def _get_events_path(path_base_data):
    path_reports = os.path.join(path_base_data, DIR_INFORMES)
    path_captures = os.path.join(path_base_data, DIR_CAPTURAS)
    if not os.path.exists(path_reports):
        os.mkdir(path_reports)
    if not os.path.exists(path_captures):
        os.mkdir(path_captures)
    return path_captures, path_reports


# noinspection PyClassHasNoInit
class MotionAlarm(appapi.AppDaemon):
    """App for handle the main intrusion alarm."""
    _lock = None
    _path_captures = None
    _path_reports = None
    _secrets = None

    _pirs = None
    _use_pirs = None
    _camera_movs = None
    _use_cams_movs = None
    _extra_sensors = None
    _use_extra_sensors = None
    _dict_asign_switchs_inputs = None

    _videostreams = {}
    _cameras_jpg_ip = None
    _cameras_jpg_params = None

    _main_switch = None
    _rele_sirena = None
    _rele_secundario = None
    _led_act = None
    _use_push_notifier_switch = None
    _email_notifier = None
    _push_notifier = None
    _silent_mode_switch = None

    _tz = None

    _time_report = None
    _espera_a_armado_sec = None
    _reset_prealarm_time_sec = None
    _min_delta_sec_events = None
    _delta_secs_trigger = None
    _use_push_notifier = False
    _retry_push_alarm = None
    _max_time_sirena_on = None
    _max_report_events = None
    _alarm_lights = None
    _cycle_colors = None

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
    _dict_sensor_classes = None
    _handler_periodic_trigger = None
    _handler_retry_alert = None
    _handler_armado_alarma = None
    _ts_lastbeat = None

    _known_devices = None

    _raw_sensors = None
    _raw_sensors_sufix = None
    _raw_sensors_seconds_to_off = None
    _raw_sensors_last_states = {}
    _raw_sensors_attributes = {}

    def initialize(self):
        """AppDaemon required method for app init."""
        self._lock = conf.callbacks_lock
        self._tz = conf.tz
        # self.log('INIT w/conf_data: {}'.format(conf_data))
        # Paths
        _path_base_data = self.args.get('path_base_data')
        _path_hass_conf = self.args.get('path_ha_conf')
        self._path_captures, self._path_reports = _get_events_path(_path_base_data)
        self._secrets = _read_hass_secret_conf(_path_hass_conf)

        # Interruptor principal
        self._main_switch = self.args.get('main_switch')

        # Sensores de movimiento (PIR's, cam_movs, extra)
        self._raw_sensors = self.args.get('raw_binary_sensors', None)
        self._pirs = self._listconf_param(self.args, 'pirs')
        self._camera_movs = self._listconf_param(self.args, 'camera_movs')
        self._extra_sensors = self._listconf_param(self.args, 'extra_sensors')
        self._use_pirs = self._listconf_param(self.args, 'use_pirs', min_len=len(self._pirs), default=True)
        self._use_cams_movs = self._listconf_param(self.args, 'use_cam_movs',
                                                   min_len=len(self._camera_movs), default=True)
        self._use_extra_sensors = self._listconf_param(self.args, 'use_extra_sensors',
                                                       min_len=len(self._extra_sensors), default=True)
        # self.log('_use_pirs: {}'.format(self._use_pirs))
        # self.log('_use_cams_movs: {}'.format(self._use_cams_movs))
        # self.log('use_extra_sensors: {}'.format(self._use_extra_sensors))

        # Video streams asociados a sensores para notif
        _streams = self._listconf_param(self.args, 'videostreams')
        if _streams:
            self._videostreams = {sensor: cam
                                  for cam, list_triggers in _streams[0].items()
                                  for sensor in list_triggers}

        # Streams de vídeo (HA entities, URLs + PAYLOADS for request jpg images)
        self._cameras_jpg_ip = self._listconf_param(self.args, 'cameras_jpg_ip_secret', is_secret=True)
        self._cameras_jpg_params = self._listconf_param(self.args, 'cameras_jpg_params_secret',
                                                        is_secret=True, is_json=True, min_len=len(self._cameras_jpg_ip))

        # Actuadores en caso de alarma (relays, LED's, ...)
        self._rele_sirena = self.args.get('rele_sirena', None)
        self._rele_secundario = self.args.get('rele_secundario', None)
        self._led_act = self.args.get('led_act', None)

        # Switch de modo silencioso (sin relays)
        self._silent_mode_switch = self.args.get('silent_mode', 'False')
        # Configuración de notificaciones
        self._email_notifier = self.args.get('email_notifier')
        self._push_notifier = self.args.get('push_notifier')
        self._use_push_notifier_switch = self.args.get('usar_push_notifier', 'True')

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
        self._alarm_lights = self.args.get('alarm_rgb_lights', None)

        # Insistencia de notificación de alarma encendida
        self._retry_push_alarm = self.args.get('retry_push_alarm', None)
        if self._retry_push_alarm is not None:
            self._retry_push_alarm = int(self._retry_push_alarm)
        # Persistencia de alarma encendida
        self._max_time_sirena_on = self.args.get('max_time_alarm_on', None)
        if self._max_time_sirena_on is not None:
            self._max_time_sirena_on = int(self._max_time_sirena_on)
        # self.log('Insistencia de notificación de alarma: {};'
        #          ' Persistencia de sirena: {}'
        #          .format(self._retry_push_alarm, self._max_time_sirena_on))

        # RAW SENSORS:
        if self._raw_sensors is not None:
            self._raw_sensors = self._raw_sensors.split(',')
            self._raw_sensors_sufix = self.args.get('raw_binary_sensors_sufijo', '_raw')
            # Persistencia en segundos de último valor hasta considerarlos 'off'
            self._raw_sensors_seconds_to_off = int(self.args.get('raw_binary_sensors_time_off', DEFAULT_RAWBS_SECS_OFF))

            # Handlers de cambio en raw binary_sensors:
            l1, l2 = 'attributes', 'last_changed'
            for s in self._raw_sensors:
                self._raw_sensors_attributes[s] = (s.replace(self._raw_sensors_sufix, ''), self.get_state(s, l1))
                # self._raw_sensors_last_states[s] = [parse(self.get_state(s, l2)).replace(tzinfo=None), False]
                self._raw_sensors_last_states[s] = [self.datetime(), False]
                self.listen_state(self._turn_on_raw_sensor_on_change, s)
            # self.log('seconds_to_off: {}'.format(self._raw_sensors_seconds_to_off))
            # self.log('attributes_sensors: {}'.format(self._raw_sensors_attributes))
            # self.log('last_changes: {}'.format(self._raw_sensors_last_states))
            [self.set_state(dev, state='off', attributes=attrs) for dev, attrs in self._raw_sensors_attributes.values()]
            next_run = self.datetime() + dt.timedelta(seconds=self._raw_sensors_seconds_to_off)
            self.run_every(self._turn_off_raw_sensor_if_not_updated, next_run, self._raw_sensors_seconds_to_off)

        self._events_data = []

        # Main switches:
        self._alarm_on = self._listen_to_switch('main_switch', self._main_switch, self._main_switch_ch)

        # set_global(self, GLOBAL_ALARM_STATE, self._alarm_on)
        self._use_push_notifier = self._listen_to_switch('push_n', self._use_push_notifier_switch, self._main_switch_ch)
        self._silent_mode = self._listen_to_switch('silent_mode', self._silent_mode_switch, self._main_switch_ch)

        # Sensors states & input usage:
        all_sensors = self._pirs + self._camera_movs + self._extra_sensors
        all_sensors_use = self._use_pirs + self._use_cams_movs + self._use_extra_sensors
        self._dict_asign_switchs_inputs = {s_use: s_input for s_input, s_use in zip(all_sensors, all_sensors_use)
                                           if type(s_use) is not bool}
        self._dict_use_inputs = {s_input: self._listen_to_switch(s_input, s_use, self._switch_usar_input)
                                 for s_input, s_use in zip(all_sensors, all_sensors_use)}
        self._dict_friendly_names = {s: self.get_state(s, attribute='friendly_name') for s in all_sensors}
        # self._dict_friendly_names.update({c: self.get_state(c, attribute='friendly_name') for c in self._videostreams})
        self._dict_sensor_classes = {s: self.get_state(s, attribute='device_class') for s in all_sensors}

        # Movement detection
        for s_mov in all_sensors:
            self.listen_state(self._motion_detected, s_mov, new="on", duration=1)

        # Programación de informe de actividad
        if self._time_report is not None:
            time_alarm = reduce(lambda x, y: x.replace(**{y[1]: int(y[0])}),
                                zip(self._time_report.split(':'), ['hour', 'minute', 'second']),
                                self.datetime().replace(second=0, microsecond=0))
            self.run_daily(self.email_events_data, time_alarm.time())
            self.log('Creado timer para informe diario de eventos a las {} de cada día'.format(time_alarm.time()))

        # Simulación de alarma visual con luces RBG (opcional)
        if self._alarm_lights is not None:
            self._cycle_colors = cycle(DEFAULT_ALARM_COLORS)
            self.log('Alarma visual con luces RGB: {}; colores: {}'.format(self._alarm_lights, self._cycle_colors))

        # Listen to main events:
        self.listen_event(self.receive_init_event, 'ha_started')
        self.listen_event(self.device_tracker_new_device, 'device_tracker_new_device')
        self.listen_event(self._reset_alarm_state, 'reset_alarm_state')
        self.listen_event(self._turn_off_sirena_in_alarm_state, 'silent_alarm_state')

    def _listconf_param(self, conf_args, param_name, is_secret=False, is_json=False, min_len=None, default=None):
        """Carga de configuración de lista de entidades de HA"""
        p_config = conf_args.get(param_name, default)
        # self.log('DEBUG listconf_param: {}, min_l={} --> {}'.format(param_name, min_len, p_config))
        if (type(p_config) is str) and ',' in p_config:
            p_config = p_config.split(',')
            if is_json and is_secret:
                return [json.loads(self._secrets['secrets'][p]) for p in p_config]
            if is_json:
                return [json.loads(p) for p in p_config]
            elif is_secret:
                return [self._secrets['secrets'][p] for p in p_config]
            else:
                return p_config
        elif p_config is not None:
            if is_secret:
                p_config = self._secrets['secrets'][p_config]
            if is_json:
                p_config = json.loads(p_config)
            if min_len is not None:
                return [p_config] * min_len
            return [p_config]
        if min_len is not None:
            return [default] * min_len
        return []

    # noinspection PyUnusedLocal
    def _turn_on_raw_sensor_on_change(self, entity, attribute, old, new, kwargs):
        _, last_st = self._raw_sensors_last_states[entity]
        self._raw_sensors_last_states[entity] = [self.datetime(), True]
        if not last_st:
            name, attrs = self._raw_sensors_attributes[entity]
            self.set_state(name, state='on', attributes=attrs)
            # self.log('TURN ON "{}" (de {} a {} --> {})'.format(entity, old, new, name))

    # noinspection PyUnusedLocal
    def _turn_off_raw_sensor_if_not_updated(self, *kwargs):
        now = self.datetime()
        for s, (ts, st) in self._raw_sensors_last_states.copy().items():
            if st and ceil((now - ts).total_seconds()) >= self._raw_sensors_seconds_to_off:
                # self.log('TURN OFF "{}" (last ch: {})'.format(s, ts))
                name, attrs = self._raw_sensors_attributes[s]
                self._raw_sensors_last_states[s] = [now, False]
                self.set_state(name, state='off', attributes=attrs)

    def _listen_to_switch(self, identif, entity_switch, func_listen_change):
        if type(entity_switch) is bool:
            # self.log('FIXED BOOL: {} -> {}'
            #          .format(identif, entity_switch), LOG_LEVEL)
            return entity_switch
        if entity_switch.lower() in ['true', 'false', 'on', 'off', '1', '0']:
            fixed_bool = entity_switch.lower() in ['true', 'on', '1']
            # self.log('FIXED SWITCH: {} -> "{}": {}'
            #          .format(identif, entity_switch, fixed_bool), LOG_LEVEL)
            return fixed_bool
        else:
            state = self.get_state(entity_switch) == 'on'
            self.listen_state(func_listen_change, entity_switch)
            # self.log('LISTEN TO CHANGES IN SWITCH: {} -> {}, ST={}'
            #          .format(identif, entity_switch, state), LOG_LEVEL)
            return state

    def _is_too_old(self, ts, delta_secs):
        if ts is None:
            return True
        else:
            now = dt.datetime.now(tz=self._tz)
            return (now - ts).total_seconds() > delta_secs

    # noinspection PyUnusedLocal
    def track_device_in_zone(self, entity, attribute, old, new, kwargs):
        if self._alarm_on:
            self.log('* DEVICE: "{}", from "{}" to "{}"'.format(entity, kwargs['codename'], old, new))

    # noinspection PyUnusedLocal
    def _reload_known_devices(self, *args):
        # Reload known_devices from yaml file:
        with open(self._secrets['path_known_dev']) as f:
            new_known_devices = yaml.load(f.read())
        if self._known_devices is None:
            self.log('KNOWN_DEVICES: {}'.format(['{name} [{mac}]'.format(**v) for v in new_known_devices.values()]))
        else:
            if any([dev not in self._known_devices.keys() for dev in new_known_devices.keys()]):
                for dev, dev_data in new_known_devices.items():
                    if dev not in new_known_devices.keys():
                        new_dev = '{name} [{mac}]'.format(**dev_data)
                        self.listen_state(self.track_device_in_zone, dev, old="home", codename=new_dev)
                        self.log('NEW KNOWN_DEV: {}'.format(new_dev))
        self._known_devices = new_known_devices

    # noinspection PyUnusedLocal
    def device_tracker_new_device(self, event_id, payload_event, *args):
        """Event listener."""
        dev = payload_event['entity_id']
        self.log('* DEVICE_TRACKER_NEW_DEVICE RECEIVED * --> {}: {}'.format(dev, payload_event))
        self.run_in(self._reload_known_devices, 5)

    # noinspection PyUnusedLocal
    def receive_init_event(self, event_id, payload_event, *args):
        """Event listener."""
        self.log('* INIT_EVENT * RECEIVED: "{}", payload={}'.format(event_id, payload_event))
        self.append_event_data(dict(event_type=EVENT_INICIO))
        self.text_notification()
        self._reload_known_devices()

    def _make_event_path(self, event_type, id_cam):
        now = dt.datetime.now(tz=self._tz)
        ev_clean = re.sub('\(|\)', '', re.sub(':|-|\+| |\.', '_', event_type))
        name = 'evento_{}_cam{}_ts{:%Y%m%d_%H%M%S}.jpg'.format(ev_clean, id_cam, now)
        sub_dir = 'ts_{:%Y_%m_%d}'.format(now.date())
        base_path = os.path.join(self._path_captures, sub_dir)
        if not os.path.exists(base_path):
            os.mkdir(base_path)
        url = '{}/{}/{}/{}/{}'.format(self._secrets['hass_base_url'], 'local', DIR_CAPTURAS, sub_dir, name)
        return name, os.path.join(base_path, name), url

    def _append_pic_to_data(self, data, event_type, index, url, params=None):
        # Get PIC from IP cams or from MotionEye in LocalHost:
        pic, ok, retries = None, False, 0
        name_pic, path_pic, url_pic = 'NONAME', None, None
        while not ok and (retries < NUM_RETRIES_MAX_GET_JPG_FROM_CAM):
            try:
                r = requests.get(url, params=params, timeout=5)
                length = float(r.headers['Content-Length'])
                if r.ok and (r.headers['Content-type'] == 'image/jpeg') and (length > BYTES_MIN_FOR_JPG):
                    pic = r.content
                    ok = True
                    if retries > 5:
                        self.log('CGI PIC OK CON {} INTENTOS: {}, length={}'
                                 .format(retries + 1, url, length), 'WARNING')
                    break
                elif not r.ok:
                    self.log('ERROR {} EN CGI PIC: {}, length={}'.format(r.status_code, url, length), 'WARNING')
            except requests.ConnectionError:
                if retries > 0:
                    self.log('ConnectionError EN CGI PIC en {}?{}'.format(url, params), 'ERROR')
                    break
            except requests.Timeout:
                if retries > 0:
                    self.log('Timeout EN CGI PIC en {}?{}'.format(url, params), 'ERROR')
                    break
            retries += 1
            # TODO ASYNC!!
            # asyncio.sleep(.2)
            sleep(.2)

        # Save PIC & (opc) b64 encode:
        if ok:
            name_pic, path_pic, url_pic = self._make_event_path(event_type, index + 1)
            with open(path_pic, 'wb') as f:
                f.write(pic)
            # pic_b64 = b64encode(pic).decode()
            data['ok_img{}'.format(index + 1)] = True
        else:
            # pic_b64 = 'NOIMG'
            data['ok_img{}'.format(index + 1)] = False
            # data['incluir'] = False
            self.log('ERROR EN CAPTURE PIC con event_type: "{}", cam #{}'.format(event_type, index + 1))
        data['path_img{}'.format(index + 1)] = path_pic
        data['url_img{}'.format(index + 1)] = url_pic
        data['name_img{}'.format(index + 1)] = name_pic
        # data['base64_img{}'.format(index + 1)] = pic_b64

    def _append_state_to_data(self, data, entity, prefix):
        st = self.get_state(entity)
        ts = self.get_state(entity, attribute='last_changed')
        if ts:
            ts = '{:%-H:%M:%S %-d/%-m}'.format(parse(ts).astimezone(self._tz))
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
        entity_trigger = kwargs.get('entity_trigger', None)
        prioridad = EVENT_TYPES[event_type][2]

        proceed = False
        with self._lock:
            tic = time()
            if not self._in_capture_mode:
                proceed = (prioridad > 1) or self._is_too_old(self._ts_lastcap, self._min_delta_sec_events)
                self._in_capture_mode = proceed
        if proceed:
            now = dt.datetime.now(tz=self._tz)
            params = dict(ts=now, ts_event='{:%H:%M:%S}'.format(now), incluir=True, prioridad=prioridad,
                          event_type=event_type, event_color=EVENT_TYPES[event_type][1], entity_trigger=entity_trigger)

            # Binary sensors: PIR's, camera_movs, extra_sensors:
            for i, p in enumerate(self._pirs):
                mask_pirs = 'pir_{}'
                self._append_state_to_data(params, p, 'pir_{}'.format(i + 1))
            for i, cm in enumerate(self._camera_movs):
                self._append_state_to_data(params, cm, 'cam_mov_{}'.format(i + 1))
            for extra_s in self._extra_sensors:
                # extra_sensor_usar = extra_s.replace('_raw', '')
                self._append_state_to_data(params, extra_s, self._dict_sensor_classes[extra_s])

            # image captures:
            if self._cameras_jpg_ip:
                if self._cameras_jpg_params is not None:
                    for i, (url, params_req) in enumerate(zip(self._cameras_jpg_ip, self._cameras_jpg_params)):
                        self._append_pic_to_data(params, event_type, i, url, params_req)
                else:
                    for i, url in enumerate(self._cameras_jpg_ip):
                        self._append_pic_to_data(params, event_type, i, url)

            params['took'] = time() - tic
            self.log('Nuevo evento "{}" adquirido en {:.2f}s, con ts={}'
                     .format(event_type, params['took'], params['ts']))
            self._events_data.append(params)

            with self._lock:
                self._in_capture_mode = False
                # self._ts_lastcap = now + dt.timedelta(seconds=params['took'])
                self._ts_lastcap = now
        else:
            if prioridad > 1:
                self.log('SOLAPAMIENTO DE LLAMADAS A APPEND_EVENT. POSPUESTO. "{}"; ts_lastcap={}'
                         .format(event_type, self._ts_lastcap), 'WARNING')
                self.run_in(self.append_event_data, 1, **kwargs)
            else:
                self.log('SOLAPAMIENTO DE LLAMADAS A APPEND_EVENT. DESECHADO. "{}"; ts_lastcap={}'
                         .format(event_type, self._ts_lastcap))

    def _reset_session_data(self):
        with self._lock:
            self._in_capture_mode = False
            self._alarm_state = False
            self._alarm_state_ts_trigger = None
            self._alarm_state_entity_trigger = None
            self._pre_alarm_on = False
            self._pre_alarm_ts_trigger = None
            self._pre_alarms = []
            self._post_alarms = []
            self._handler_periodic_trigger = None
            self._handler_retry_alert = None

    # noinspection PyUnusedLocal
    def _armado_sistema(self, *args):
        with self._lock:
            self._handler_armado_alarma = None
            self._alarm_on = True
            # set_global(self, GLOBAL_ALARM_STATE, True)
        self._reset_session_data()
        self.append_event_data(dict(event_type=EVENT_ACTIVACION))
        self.text_notification()

    # noinspection PyUnusedLocal
    def _main_switch_ch(self, entity, attribute, old, new, kwargs):
        if entity == self._main_switch:
            alarm_on = new == 'on'
            if alarm_on and (old == 'off'):  # turn_on_alarm with delay
                self._handler_armado_alarma = self.run_in(self._armado_sistema, self._espera_a_armado_sec)
                self.log('--> ALARMA CONECTADA DENTRO DE {} SEGUNDOS'.format(self._espera_a_armado_sec))
            elif not alarm_on and (old == 'on'):  # turn_off_alarm
                if self._handler_armado_alarma is not None:
                    self.cancel_timer(self._handler_armado_alarma)
                    self._handler_armado_alarma = None

                with self._lock:
                    self._alarm_on = False
                    # set_global(self, GLOBAL_ALARM_STATE, False)
                    self._alarm_state = False

                # Operación con relés en apagado de alarma:
                [self.call_service('{}/turn_off'.format(ent.split('.')[0]), entity_id=ent)
                 for ent in [self._rele_sirena, self._rele_secundario, self._led_act] if ent is not None]

                # send & reset events
                if self._events_data:
                    self.append_event_data(dict(event_type=EVENT_DESCONEXION))
                    self.text_notification()
                    self.email_events_data()

                # reset ts alarm & pre-alarm
                self._reset_session_data()
                if self._alarm_lights is not None:
                    self.call_service("light/turn_off", entity_id=self._alarm_lights, transition=1)
                self.log('--> ALARMA DESCONECTADA')
        elif entity == self._use_push_notifier_switch:
            self._use_push_notifier = new == 'on'
            self.log('SWITCH USAR PUSH NOTIFS: de "{}" a "{}" --> {}'.format(old, new, self._use_push_notifier))
        elif entity == self._silent_mode_switch:
            self._silent_mode = new == 'on'
            self.log('SILENT MODE: {}'.format(self._silent_mode))
            if self._alarm_state and self._silent_mode and (self._rele_sirena is not None):
                self.call_service('{}/turn_off'.format(self._rele_sirena.split('.')[0]), entity_id=self._rele_sirena)
        else:
            self.log('Entity unknown in _main_switch_ch: {} (from {} to {}, attrs={}'
                     .format(entity, old, new, attribute), 'ERROR')

    # noinspection PyUnusedLocal
    def _switch_usar_input(self, entity, attribute, old, new, kwargs):
        k = self._dict_asign_switchs_inputs[entity]
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
    def _reset_alarm_state(self, *args):
        """Reset del estado de alarma ON. La alarma sigue encendida, pero se pasa a estado inactivo en espera"""
        process = False
        with self._lock:
            if self._alarm_on and self._alarm_state:
                self._alarm_state = False
                self._alarm_state_ts_trigger = None
                self._alarm_state_entity_trigger = None
                # self._events_data = []
                self._pre_alarms = []
                self._post_alarms = []
                self._pre_alarm_on = False
                self._pre_alarm_ts_trigger = None
                self._handler_periodic_trigger = None
                self._handler_retry_alert = None
                process = True
        if process:
            self.log('** RESET OF ALARM STATE')
            # apagado de relés de alarma:
            [self.call_service('{}/turn_off'.format(ent.split('.')[0]), entity_id=ent)
             for ent in [self._rele_sirena, self._rele_secundario, self._led_act] if ent is not None]
            if self._alarm_lights is not None:
                self.call_service("light/turn_off", entity_id=self._alarm_lights, transition=1)

    # noinspection PyUnusedLocal
    def _turn_off_sirena_in_alarm_state(self, *args):
        """Apaga el relé asociado a la sirena.
        La alarma sigue encendida y grabando eventos en activaciones de sensor y periódicamente."""
        process = False
        with self._lock:
            if self._alarm_on and self._alarm_state and not self._silent_mode:
                # self._silent_mode = True
                process = True
        if process:
            # apagado de relés de alarma:
            self.log('** Apagado del relé de la sirena de alarma')
            if self._rele_sirena is not None:
                self.call_service('{}/turn_off'.format(self._rele_sirena.split('.')[0]), entity_id=self._rele_sirena)
            if self._alarm_lights is not None:
                self.call_service("light/turn_off", entity_id=self._alarm_lights, transition=1)

    # noinspection PyUnusedLocal
    def _turn_off_prealarm(self, *args):
        proceed = False
        with self._lock:
            if self._pre_alarm_on and not self._alarm_state:
                self._pre_alarm_ts_trigger = None
                self._pre_alarm_on = False
                proceed = True
        if proceed:
            if self._led_act is not None:
                self.call_service('switch/turn_off', entity_id=self._led_act)
            self.log('*PREALARMA DESACTIVADA*')

    # noinspection PyUnusedLocal
    def _motion_detected(self, entity, attribute, old, new, kwargs):
        """Lógica de activación de alarma por detección de movimiento.
         - El 1º evento pone al sistema en 'pre-alerta', durante un tiempo determinado. Se genera un evento.
         - Si se produce un 2º evento en estado de pre-alerta, comienza el estado de alerta, se genera un evento,
            se disparan los relés asociados, se notifica al usuario con push_notif + email, y se inician los actuadores
            periódicos.
         - Las siguientes detecciones generan nuevos eventos, que se acumulan hasta que se desconecte la alarma y se
            notifique al usuario por email.
        """
        # self.log('DEBUG MOTION: {}, {}->{}'.format(entity, old, new))
        if self._validate_input(entity):
            # Actualiza persistent_notification de entity en cualquier caso
            # self._persistent_notification(entity)
            now = dt.datetime.now(tz=self._tz)
            delta_beat = 100

            # LOCK
            priority = 0
            with self._lock:
                if self._ts_lastbeat is not None:
                    delta_beat = (now - self._ts_lastbeat).total_seconds()
                if delta_beat > MIN_TIME_BETWEEN_MOTION:
                    if self._alarm_state:
                        priority = 1
                    elif self._pre_alarm_on:
                        priority = 3
                        self._alarm_state = True
                    else:
                        priority = 2
                        self._pre_alarm_on = True
                    self._ts_lastbeat = now

            # self.log('DEBUG MOTION "{}": "{}"->"{}" at {:%H:%M:%S.%f}. A={}, ST_A={}, ST_PRE-A={}'
            #          .format(entity, old, new, now, self._alarm_on, self._alarm_state, self._pre_alarm_on))
            # Nuevo evento, con alarma conectada. Se ignora por ahora
            # if self._alarm_state:
            if priority == 1:
                self.log('(IN ALARM MODE) motion_detected in {}, ∆Tbeat={:.6f}s'.format(entity, delta_beat))
                if self._led_act is not None:
                    self.call_service('switch/toggle', entity_id=self._led_act)
                if self._is_too_old(self._ts_lastcap, self._min_delta_sec_events):
                    self.append_event_data(dict(event_type=EVENT_EN_ALARMA, entity_trigger=entity))
                self.alarm_persistent_notification(entity, now)
            # Trigger ALARMA después de pre-alarma
            # elif self._pre_alarm_on:
            elif priority == 3:
                self.log('**** ALARMA!! **** activada por "{}", ∆Tbeat={:.6f}s'.format(entity, delta_beat))
                # self.turn_on_alarm()
                self._alarm_state_ts_trigger = now
                self._alarm_state_entity_trigger = entity
                self._alarm_state = True
                if self._handler_periodic_trigger is None:  # Sólo 1ª vez!
                    if not self._silent_mode and (self._rele_sirena is not None):
                        self.call_service('{}/turn_on'.format(self._rele_sirena.split('.')[0]),
                                          entity_id=self._rele_sirena)
                    if self._rele_secundario is not None:
                        self.call_service('{}/turn_on'.format(self._rele_secundario.split('.')[0]),
                                          entity_id=self._rele_secundario)
                    self.append_event_data(dict(event_type=EVENT_ALARMA, entity_trigger=entity))
                    self.text_notification(append_extra_data=True)
                    self.alarm_persistent_notification()
                    self.email_events_data()
                    # Empieza a grabar eventos periódicos cada DELTA_SECS_TRIGGER:
                    self._handler_periodic_trigger = self.run_in(self.periodic_capture_mode, self._delta_secs_trigger)
                    if self._max_time_sirena_on is not None:
                        # Programa el apagado automático de la sirena pasado cierto tiempo desde la activación.
                        self.run_in(self._turn_off_sirena_in_alarm_state, self._max_time_sirena_on)
                    if (self._handler_retry_alert is None) and (self._retry_push_alarm is not None):  # Sólo 1ª vez!
                        # Empieza a notificar la alarma conectada cada X minutos
                        self._handler_retry_alert = self.run_in(self.periodic_alert, self._retry_push_alarm)
                    # Sirena visual con RGB lights:
                    if self._alarm_lights is not None:
                        self.run_in(self._flash_alarm_lights, 2)
            # Dispara estado pre-alarma
            elif priority == 2:
                self.log('** PRE-ALARMA ** activada por "{}"'.format(entity), LOG_LEVEL)
                self._pre_alarm_ts_trigger = now
                self._pre_alarm_on = True
                self.run_in(self._turn_off_prealarm, self._reset_prealarm_time_sec)
                self.prealarm_persistent_notification(entity, now)
                self.append_event_data(dict(event_type=EVENT_PREALARMA, entity_trigger=entity))
                if self._led_act is not None:
                    self.call_service('switch/turn_on', entity_id=self._led_act)
            else:
                self.log('** MOVIMIENTO DESECHADO ** activado por "{}", ∆Tbeat={:.6f}s'.format(entity, delta_beat))

    # noinspection PyUnusedLocal
    def periodic_capture_mode(self, *args):
        """Ejecución periódica con la alarma encendida para capturar eventos cada cierto tiempo."""
        # self.log('EN PERIODIC_CAPTURE_MODE con ∆T={} s'.format(self._delta_secs_trigger))
        proceed = append_event = False
        with self._lock:
            if self._alarm_state:
                proceed = True
                append_event = self._is_too_old(self._ts_lastbeat, self._min_delta_sec_events)
        if proceed:
            if append_event:
                self.append_event_data(dict(event_type=EVENT_ALARMA_ENCENDIDA))
            self.run_in(self.periodic_capture_mode, self._delta_secs_trigger)
        else:
            # self.log('STOP PERIODIC CAPTURE MODE')
            self._handler_periodic_trigger = None

    # noinspection PyUnusedLocal
    def periodic_alert(self, *args):
        """Ejecución periódica con la alarma encendida para enviar una notificación recordando dicho estado."""
        self.log('EN PERIODIC_ALERT con ∆T={} s'.format(self._retry_push_alarm))
        proceed = False
        with self._lock:
            if self._alarm_state:
                proceed = True
        if proceed:
            self.periodic_alert_notification()
            self.run_in(self.periodic_alert, self._retry_push_alarm)
        else:
            self.log('STOP PERIODIC ALERT')
            self._handler_retry_alert = None

    # def _persistent_notification(self, trigger_entity, ts, title=None, unique_id=True):
    #     f_name = notif_id = self._dict_friendly_names[trigger_entity]
    #     if not unique_id:
    #         notif_id += '_{:%y%m%d%H%M%S}'.format(ts)
    #     message = 'Activación a las {:%H:%M:%S de %d/%m/%Y} por "{}"'.format(ts, f_name)
    #     params = dict(message=message, title=title if title is not None else f_name, id=notif_id)
    #     self._post_alarms.append((self._dict_friendly_names[trigger_entity], '{:%H:%M:%S}'.format(ts)))
    #     self.persistent_notification(**params)
    #     # self.log('PERSISTENT NOTIFICATION: {}'.format(params))

    def alarm_persistent_notification(self, trigger_entity=None, ts=None):
        """Notificación en el frontend de alarma activada."""
        if trigger_entity is not None:
            self._post_alarms.append((self._dict_friendly_names[trigger_entity], '{:%H:%M:%S}'.format(ts)))
        params_templ = dict(ts='{:%H:%M:%S}'.format(self._alarm_state_ts_trigger),
                            entity=self._dict_friendly_names[self._alarm_state_entity_trigger],
                            postalarms=self._post_alarms[::-1])
        message = JINJA2_ENV.get_template('persistent_notif_alarm.html').render(**params_templ)
        params = dict(message=message, title="ALARMA!!", id='alarm')
        # self.log('DEBUG ALARM PERSISTENT NOTIFICATION: {}'.format(params))
        self.persistent_notification(**params)

    def prealarm_persistent_notification(self, trigger_entity, ts):
        """Notificación en el frontend de pre-alarma activada."""
        self._pre_alarms.append((self._dict_friendly_names[trigger_entity], '{:%H:%M:%S}'.format(ts)))
        message = JINJA2_ENV.get_template('persistent_notif_prealarm.html').render(prealarms=self._pre_alarms[::-1])
        params = dict(message=message, title="PRE-ALARMA", id='prealarm')
        # self.log('DEBUG PRE-ALARM PERSISTENT NOTIFICATION: {}'.format(params))
        self.persistent_notification(**params)

    def _update_ios_notify_params(self, params, url_usar):
        if ((self._alarm_state_entity_trigger is not None) and
                (self._videostreams.get(self._alarm_state_entity_trigger))):
            # Get the camera video stream as function of trigger
            cam_entity = self._videostreams.get(
                self._alarm_state_entity_trigger)
            params.update(
                data=dict(
                    push=dict(badge=10, sound=SOUND_MOTION,
                              category="camera"),
                    entity_id=cam_entity,
                    attachment=dict(url=url_usar)))
        else:
            params.update(
                data=dict(
                    push=dict(badge=10, sound=SOUND_MOTION,
                              category="ALARMSOUNDED"),
                    attachment=dict(url=url_usar)))
        return params

    def periodic_alert_notification(self):
        """Notificación de recordatorio de alarma encendida."""
        if self._alarm_state:
            extra = ''
            if self._rele_sirena is not None:
                extra += 'Sirena: {}. '.format(self.get_state(self._rele_sirena))
            msg = AVISO_RETRY_ALARMA_ENCENDIDA_MSG.format(self._alarm_state_ts_trigger, extra)
            params = dict(title=AVISO_RETRY_ALARMA_ENCENDIDA_TITLE, message=msg)
            if self._use_push_notifier:
                service = self._push_notifier
                if self._events_data and ('url_img1' in self._events_data[-1]):
                    url_usar = self._events_data[-1]['url_img1']
                else:
                    url_usar = self._secrets['hass_base_url']
                if 'ios' in service:
                    params = self._update_ios_notify_params(params, url_usar)
                elif 'pushbullet' in service:
                    # params.update(data=dict(url=url_usar))
                    params.update(target=self._secrets['pb_target'], data=dict(url=url_usar))

                self.log('PUSH TEXT NOTIFICATION "{title}": {message}, {data}'.format(**params))
            else:
                params.update(target=self._secrets['email_target'])
                params['message'] += '\n\nURL del sistema de vigilancia: {}'.format(self._secrets['hass_base_url'])
                service = self._email_notifier
                self.log('EMAIL RAW TEXT NOTIFICATION: {title}: {message}'.format(**params))
            self.call_service(service, **params)

    def text_notification(self, append_extra_data=False):
        """Envía una notificación de texto plano con el status del último evento añadido."""
        if self._events_data:
            last_event = self._events_data[-1]
            event_type = last_event['event_type']
            pre_alarm_ts = '{:%H:%M:%S}'.format(self._pre_alarm_ts_trigger) if self._pre_alarm_ts_trigger else None
            alarm_ts = '{:%H:%M:%S}'.format(self._alarm_state_ts_trigger) if self._alarm_state_ts_trigger else None
            params_templ = dict(pre_alarm_ts=pre_alarm_ts, alarm_ts=alarm_ts,
                                alarm_entity=self._alarm_state_entity_trigger, evento=last_event,
                                pirs=self._pirs, cam_movs=self._camera_movs,
                                extra_sensors=[(s, self._dict_sensor_classes[s]) for s in self._extra_sensors],
                                friendly_names=self._dict_friendly_names)
            msg = JINJA2_ENV.get_template('raw_text_pbnotif.html').render(**params_templ)
            msg_text = msg.replace('</pre>', '').replace('<pre>', '')
            params = dict(title=EVENT_TYPES[event_type][0], message=msg_text)
            if self._use_push_notifier:
                service = self._push_notifier
                if 'pushbullet' in service:
                    params.update(target=self._secrets['pb_target'])
                if append_extra_data:
                    if 'url_img1' in last_event:
                        url_usar = last_event['url_img1']
                    else:
                        url_usar = self._secrets['hass_base_url']
                    if 'ios' in service:
                        params = self._update_ios_notify_params(
                            params, url_usar)
                    elif 'pushbullet' in service:
                        params.update(data=dict(url=url_usar))
                # self.log('PUSH TEXT NOTIFICATION "{title}: {message}"'.format(**params))
                self.log('PUSH TEXT NOTIFICATION "{title}"'.format(**params))
            else:
                params.update(target=self._secrets['email_target'])
                service = self._email_notifier
                self.log('EMAIL RAW TEXT NOTIFICATION: {title}: {message}'.format(**params))
            self.call_service(service, **params)

    def get_events_for_email(self):
        """Devuelve los eventos acumulados filtrados y ordenados, junto a los paths de las imágenes adjuntadas."""

        def _count_included_events(evs):
            """Cuenta los eventos marcados para inclusión."""
            return len(list(filter(lambda x: x['incluir'], evs)))

        def _ok_num_events(evs, num_max, prioridad_filtro, logger):
            """Marca 'incluir' = False para eventos de prioridad < X, hasta reducir a num_max."""
            n_included = n_included_init = _count_included_events(evs)
            if n_included > num_max:
                # Filtrado eliminando eventos periódicos, después prealarmas
                idx = len(evs) - 1
                while (idx >= 0) and (n_included > num_max):
                    if evs[idx]['incluir'] and (evs[idx]['prioridad'] < prioridad_filtro):
                        evs[idx]['incluir'] = False
                        n_included -= 1
                    idx -= 1
                logger('Filtrado de eventos con P < {} por exceso. De {}, quedan {} eventos.'
                       .format(prioridad_filtro, n_included_init, n_included))
            return n_included <= num_max

        eventos = self._events_data.copy()
        self._events_data = []

        # Filtrado de eventos de baja prioridad si hay demasiados
        ok_filter, prioridad_min = False, 1
        while (not _ok_num_events(eventos, self._max_report_events, prioridad_min, self.log)
               and (prioridad_min <= 5)):
            # self.log('Filtrado de eventos con P < {} por exceso. De {}, quedan {} eventos.'
            #          .format(prioridad_min, len(self._events_data), _count_included_events(self._events_data)))
            prioridad_min += 1

        # Eventos e imágenes para email attachments (cid:#):
        num_included_events = _count_included_events(eventos)
        eventos = eventos[::-1]
        counter_imgs, paths_imgs = 0, []
        for event in filter(lambda x: x['incluir'], eventos):
            for i in range(len(self._cameras_jpg_ip)):
                if event['ok_img{}'.format(i + 1)]:
                    event['id_img{}'.format(i + 1)] = event['name_img{}'.format(i + 1)]
                    paths_imgs.append(event['path_img{}'.format(i + 1)])
                    counter_imgs += 1
        return eventos, paths_imgs, num_included_events

    # noinspection PyUnusedLocal
    def email_events_data(self, *args):
        """Envía por email los eventos acumulados."""
        tic = time()
        if self._events_data:
            now = dt.datetime.now(tz=self._tz)
            eventos, paths_imgs, num_included_events = self.get_events_for_email()

            # Informe
            r_name = 'report_{:%Y%m%d_%H%M%S}.html'.format(now)
            last_event = eventos[0]
            color_title = last_event['event_color'] if EVENT_TYPES[last_event['event_type']][2] else HASS_COLOR
            url_local_path_report = '{}/{}/{}/{}'.format(self._secrets['hass_base_url'], 'local', DIR_INFORMES, r_name)
            title = EVENT_TYPES[last_event['event_type']][3]
            ts_title = '{:%-d-%-m-%Y}'.format(now.date())

            # Render html reports for email & static server
            report_templ = JINJA2_ENV.get_template('report_template.html')
            params_templ = dict(title=title, ts_title=ts_title, color_title=color_title,
                                eventos=eventos, include_images_base64=False,
                                num_cameras=len(self._cameras_jpg_ip),
                                pirs=self._pirs, cam_movs=self._camera_movs,
                                extra_sensors=[(s, self._dict_sensor_classes[s]) for s in self._extra_sensors],
                                friendly_names=self._dict_friendly_names)
            html_email = report_templ.render(is_email=True, url_local_report=url_local_path_report, **params_templ)
            html_static = report_templ.render(is_email=False, **params_templ)

            path_disk_report = os.path.join(self._path_reports, r_name)
            try:
                with open(path_disk_report, 'w') as f:
                    f.write(html_static)
                self.log('INFORME POR EMAIL con {} eventos ({} con imágenes [{}]) generado y guardado en {} en {:.2f} s'
                         .format(len(eventos), num_included_events, len(paths_imgs), path_disk_report, time() - tic))
            except Exception as e:
                self.log('ERROR EN SAVE REPORT TO DISK: {} [{}]'.format(e, e.__class__))
            self._events_data = []
            params = dict(title="{} - {}".format(title, ts_title), target=self._secrets['email_target'],
                          message='No text!', data=dict(html=html_email, images=paths_imgs))
            self.call_service(self._email_notifier, **params)
        else:
            self.log('Se solicita enviar eventos, pero no hay ninguno! --> {}'.format(self._events_data), 'ERROR')

    # noinspection PyUnusedLocal
    def _flash_alarm_lights(self, *args):
        """Recursive-like method for flashing lights with cycling colors."""
        if self._alarm_lights is not None:
            if self._alarm_state:
                self.call_service("light/turn_on", entity_id=self._alarm_lights,
                                  rgb_color=next(self._cycle_colors), brightness=255, transition=1)
                self.run_in(self._flash_alarm_lights, 3)