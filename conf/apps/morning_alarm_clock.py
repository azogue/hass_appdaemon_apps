# -*- coding: utf-8 -*-
"""
Automation task as a AppDaemon App for Home Assistant

This little app is a not too simple alarm clock, which simulates a fast dawn with Hue lights,
while waking up the home cinema system, waiting for the start of the broadcast of La Cafetera radio program to
start playing it (or, if the alarm is at a different time of the typical emmision time,
it just play the last published episode).

For doing that, it talks directly with Kodi through its JSONRPC API,
which has to run a specific Kodi Add-On: plugin.audio.lacafetera.

"""
import appdaemon.appapi as appapi
import datetime as dt
from functools import reduce
import json
import pandas as pd
import requests

# Defaults para La Cafetera:
DEFAULT_DURATION = 1  # h
DEFAULT_EMISION_TIME = "08:30:00"
MAX_WAIT_TIME = pd.Timedelta(minutes=15)
STEP_RETRYING = pd.Timedelta(seconds=15)
WARM_UP_TIME_DELTA = pd.Timedelta(seconds=35)
MIN_INTERVAL_BETWEEN_EPS = pd.Timedelta(hours=6)


# LOG_LEVEL = 'DEBUG'
LOG_LEVEL = 'INFO'
WEEKDAYS_DICT = {'mon': 0, 'tue': 1, 'wed': 2, 'thu': 3, 'fri': 4, 'sat': 5, 'sun': 6}


def get_info_last_ep(tz, limit=1):
    """Extrae la información del último (o 'n-último') episodio disponible de La Cafetera de Radiocable.com"""
    base_url_v2 = 'https://api.spreaker.com/v2/'
    cafetera_showid = 1060718
    mask_url = base_url_v2 + 'shows/' + str(cafetera_showid) + '/episodes?limit=' + str(limit)
    r = requests.get(mask_url)
    if r.ok:
        data = r.json()
        if ('response' in data) and ('items' in data['response']):
            episode = data['response']['items'][-1]
            published = pd.Timestamp(episode['published_at'], tz='UTC').tz_convert(tz)
            is_live = episode['type'] == 'LIVE'
            duration = dt.timedelta(hours=DEFAULT_DURATION)
            if not is_live:
                duration = dt.timedelta(seconds=episode['duration'] / 1000)
            return True, {'published': published, 'is_live': is_live, 'duration': duration, 'episode': episode}
        return False, data
    return False, None


def is_last_episode_ready_for_play(tz, debug_delta_now=None, debug_limit_eps=None):
    """Comprueba si hay un nuevo episodio disponible de La Cafetera.

    :param tz: timezone, para corregir las fechas en UTC a local
    :param debug_delta_now: opcional, para debug. Aplica un ∆T a la hora actual
    :param debug_limit_eps: opcional, para debug. Aplica un ∆N a la lista de episodios disponibles
    :return: (play_now, info_last_episode)
    :rtype: tuple(bool, dict)
    """
    now = pd.Timestamp.now(tz=tz)
    if debug_delta_now is not None:
        now += pd.Timedelta(debug_delta_now)
        print('DEBUG: work with now={}'.format(now))
    estimated_today_ep = pd.Timestamp('{} {}'.format(now.date(), DEFAULT_EMISION_TIME), tz=tz)
    limit = 1 if debug_limit_eps is None else debug_limit_eps
    ok, info = get_info_last_ep(tz, limit)
    if ok:
        if (info['is_live'] or (now - info['published'] < MIN_INTERVAL_BETWEEN_EPS) or
                (now > estimated_today_ep + MAX_WAIT_TIME)):
            # Reproducir YA
            return True, info
        else:
            # Esperar un poco más a que empiece
            return False, info
    # Network error?
    return False, None


def make_notification_episode(ep_info):
    """Crea los datos para la notificación de alarma, con información del episodio de La Cafetera a reproducir."""
    message = ("La Cafetera [{}]: {}\n(Publicado: {})"
               .format(ep_info['episode']['title'], 'LIVE' if ep_info['is_live'] else 'RECORDED', ep_info['published']))
    data_msg = {"title": "Comienza el día en positivo!",
                "message": message,
                "data": {"push": {"badge": 0, "sound": "US-EN-Morgan-Freeman-Good-Morning.wav", "category": "ALARM"}}}
    # TODO corregir img-attachment en ios notification
    # img_url = ep_info['episode']['image_url']
    # "data": {"attachment": img_url, "content-type": "jpg", "hide-thumbnail": "false"}}
    return data_msg


def _weekday(str_wday):
    str_wday = str_wday.lower().rstrip().lstrip()
    if str_wday in WEEKDAYS_DICT:
        return WEEKDAYS_DICT[str_wday]
    print('Error parsing weekday: "{}" -> mon,tue,wed,thu,fri,sat,sun'.format(str_wday))
    return -1


# noinspection PyClassHasNoInit
class AlarmClock(appapi.AppDaemon):
    """App for run a some-complex morning alarm,
    with sunrise light simulation and launch of a playing task to KODI within a Kodi add-on,
    after waking up the home-cinema system."""

    alarm_time_sensor = None
    weekdays_alarm = None
    notifier = None
    lights_alarm = None
    transit_time = None
    phases_sunrise = []
    tz = None

    kodi_ip = None
    kodi_port = None
    kodi_user = None
    kodi_pass = None

    next_alarm = None
    handle_alarm = None

    def initialize(self):
        """AppDaemon required method for app init."""
        conf_data = dict(self.config['AppDaemon'])
        self.tz = conf_data.get('time_zone', 'Europe/Madrid')
        self.alarm_time_sensor = self.args.get('alarm_time')
        self.listen_state(self.alarm_time_change, self.alarm_time_sensor)
        self.weekdays_alarm = [_weekday(d) for d in self.args.get('alarmdays', 'mon,tue,wed,thu,fri').split(',')
                               if _weekday(d) >= 0]

        self.lights_alarm = self.args.get('lights_alarm', None)
        self.notifier = self.args.get('notifier', None)
        total_duration = int(self.args.get('sunrise_duration', 60))
        if not self.phases_sunrise:
            self.phases_sunrise.append({'brightness': 4, 'xy_color': [0.6051, 0.282], 'rgb_color': (62, 16, 17)})
            self.phases_sunrise.append({'brightness': 30, 'xy_color': [0.672, 0.327], 'rgb_color': (183, 66, 0)})
            self.phases_sunrise.append({'brightness': 60, 'xy_color': [0.629, 0.353], 'rgb_color': (224, 105, 19)})
            self.phases_sunrise.append({'brightness': 147, 'xy_color': [0.533, 0.421], 'rgb_color': (255, 175, 53)})
            self.phases_sunrise.append({'brightness': 196, 'xy_color': [0.4872, 0.4201], 'rgb_color': (255, 191, 92)})
            self.phases_sunrise.append({'brightness': 222, 'xy_color': [0.4587, 0.4103], 'rgb_color': (255, 199, 117)})
            self.phases_sunrise.append({'brightness': 254, 'xy_color': [0.449, 0.4078], 'rgb_color': (255, 203, 124)})
        self.transit_time = total_duration // len(self.phases_sunrise) + 1

        self.kodi_ip = self.args.get('kodi_ip', '127.0.0.1')
        self.kodi_port = self.args.get('kodi_port', 8080)
        self.kodi_user = self.args.get('kodi_user', None)
        self.kodi_pass = self.args.get('kodi_pass', None)

        self._set_dt_next_trigger()
        self.run_hourly(self._check_alarm_day, None)
        # self.log('INIT WITH NEXT ALARM IN: {:%d-%m-%Y %H:%M:%S}'.format(self.next_alarm), LOG_LEVEL)
        # self.listen_state(self.turn_on_lights_as_sunrise, 'input_boolean.testing_alarm', new='on')

    # noinspection PyUnusedLocal
    def alarm_time_change(self, entity, attribute, old, new, kwargs):
        """Re-schedule next alarm when alarm time sliders change."""
        self._set_dt_next_trigger()
        self.log('CHANGING ALARM TIME TO: {:%H:%M:%S}'.format(self.next_alarm), LOG_LEVEL)

    # noinspection PyUnusedLocal
    def _check_alarm_day(self, *args):
        now = dt.datetime.now()
        if self.next_alarm + WARM_UP_TIME_DELTA < now:  # - dt.timedelta(minutes=1):
            next_day = self.next_alarm + dt.timedelta(days=1)
            while next_day.weekday() not in self.weekdays_alarm:
                next_day += dt.timedelta(days=1)
            self.log('DEBUG: change day in check_alarm_day. From {} to {}'.format(self.next_alarm, next_day), LOG_LEVEL)
            self.next_alarm = next_day

    # noinspection PyUnusedLocal
    def _set_dt_next_trigger(self, *args):
        if self.handle_alarm is not None:
            self.log('Cancelling timer "{}" -> {}'.format(self.handle_alarm, self.next_alarm), LOG_LEVEL)
            self.cancel_timer(self.handle_alarm)
        time_alarm = reduce(lambda x, y: x.replace(**{y[1]: int(y[0])}),
                            zip(self.get_state(self.alarm_time_sensor).split(':'), ['hour', 'minute', 'second']),
                            dt.datetime.now().replace(second=0, microsecond=0))
        self.next_alarm = time_alarm - WARM_UP_TIME_DELTA
        self._check_alarm_day()
        self.handle_alarm = self.run_at(self.run_alarm, self.next_alarm)
        self.log('Creating timer for {} --> {}'.format(self.next_alarm, self.handle_alarm), LOG_LEVEL)

    # noinspection PyUnusedLocal
    def turn_on_lights_as_sunrise(self, *args):
        """Turn on the lights with a sunrise simulation done with multiple transitions."""

        def _set_sunrise_phase(*args_runin):
            self.log('SET_SUNRISE_PHASE: XY={xy_color}, BRIGHT={brightness}, TRANSITION={transition}'
                     .format(**args_runin[0]))
            self.call_service('light/turn_on', **args_runin[0])

        self.log('RUN_SUNRISE')
        self.call_service('light/turn_off', entity_id=self.lights_alarm, transition=0,
                          xy_color=self.phases_sunrise[0]['xy_color'], brightness=1)
        self.call_service('light/turn_on', entity_id=self.lights_alarm, transition=0,
                          xy_color=self.phases_sunrise[0]['xy_color'], brightness=1)
        run_in = 2
        for phase in self.phases_sunrise:
            # noinspection PyTypeChecker
            xy_color, brightness = phase['xy_color'], phase['brightness']
            self.run_in(_set_sunrise_phase, run_in, entity_id=self.lights_alarm,
                        xy_color=xy_color, transition=self.transit_time, brightness=brightness)
            run_in += self.transit_time + 1

    def run_kodi_addon_lacafetera(self, mode="playlast"):
        """Run Kodi add-on with parameters vith JSONRPC API."""
        self.log('RUN_KODI_ADDON_LACAFETERA with mode={}'.format(mode), LOG_LEVEL)
        url_base = 'http://{}:{}/'.format(self.kodi_ip, self.kodi_port)
        auth = (self.kodi_user, self.kodi_pass) if self.kodi_user is not None else None
        data = {"request": json.dumps({"id": 1, "jsonrpc": "2.0", "method": "Addons.ExecuteAddon",
                                       "params": {"params": {"mode": mode},
                                                  "addonid": "plugin.audio.lacafetera"}})}
        r = requests.get(url_base + 'jsonrpc', params=data, auth=auth,
                         headers={'Content-Type': 'application/json'}, timeout=5)
        if r.ok:
            return True
        self.log('KODI NOT PRESENT? -> {}'.format(r.content), 'ERROR')
        return False

    def prepare_context_alarm(self):
        """Initialize the alarm context (turn on devices, get ready the context, etc.)"""
        self.log('PREPARE_CONTEXT_ALARM', LOG_LEVEL)
        self.call_service('switch/turn_on', entity_id="switch.tele")
        self.run_kodi_addon_lacafetera(mode='wakeup')

    # noinspection PyUnusedLocal
    def trigger_service_in_alarm(self, *args):
        """Launch alarm secuence if ready, or set itself to retry in the short future."""
        # Wake device
        self.run_kodi_addon_lacafetera(mode='wakeup')
        # Check if alarm is ready to launch
        alarm_ready, alarm_info = is_last_episode_ready_for_play(self.tz)
        self.log('is_alarm_ready_to_trigger? {}, info={}'.format(alarm_ready, alarm_info), LOG_LEVEL)
        if alarm_ready:
            # self.call_service('light/turn_on', entity_id=self.lights_alarm,
            #                   profile='energize', transition=30, brightness=255)
            self.turn_on_lights_as_sunrise()
            self.run_kodi_addon_lacafetera(mode='playlast')
            # Notification:
            self.call_service(self.notifier.replace('.', '/'), **make_notification_episode(alarm_info))
        else:
            self.log('POSTPONE ALARM, alarm_info={}'.format(alarm_info), LOG_LEVEL)
            self.run_in(self.trigger_service_in_alarm, STEP_RETRYING)

    # noinspection PyUnusedLocal
    def run_alarm(self, *args):
        """Run the alarm main secuence: prepare, trigger & schedule next"""
        self.prepare_context_alarm()
        self.run_in(self.trigger_service_in_alarm, WARM_UP_TIME_DELTA.total_seconds())
        # Resetting
        self.run_in(self._set_dt_next_trigger, 10 * WARM_UP_TIME_DELTA.total_seconds())

