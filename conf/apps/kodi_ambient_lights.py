# -*- coding: utf-8 -*-
"""
Automation task as a AppDaemon App for Home Assistant

This little app controls the ambient light when Kodi plays video, dimming some lights and turning off others,
and returning to the initial state when the playback is finished.
In addition, it also sends notifications when starting the video playback, reporting the video info in the message.
For that, it talks directly with Kodi through its JSONRPC API

"""
import datetime as dt
import appdaemon.appapi as appapi
import requests
import json
from urllib import parse
import appdaemon.homeassistant as ha


LOG_LEVEL = 'DEBUG'
MAX_BRIGHTNESS_KODI = 75


PARAMS_GET_ITEM = {"id": 1, "jsonrpc": "2.0", "method": "Player.GetItem",
                   "params": {"playerid": 1,
                              "properties": ["title", "artist", "albumartist", "genre", "year", "rating", "album",
                                             "track", "duration", "playcount", "fanart", "plot", "originaltitle",
                                             # "country","imdbnumber", "showlink", "streamdetails",
                                             # "resume", #"artistid", #"albumid", #"uniqueid",
                                             "lastplayed", "firstaired", "season", "episode", "showtitle", "thumbnail",
                                             "file", "tvshowid", "watchedepisodes", "art", "description", "theme",
                                             "dateadded", "runtime", "starttime", "endtime"]}}


# noinspection PyClassHasNoInit
class KodiAssistant(appapi.AppDaemon):
    """App for Ambient light control when playing video with KODI."""

    _lights_dim = None
    _lights_off = None

    _media_player = None
    _kodi_ip = None
    _kodi_port = None
    _kodi_user = None
    _kodi_pass = None

    _notifier = None

    _light_states = {}
    _is_playing_video = False
    _item_playing = None
    _last_play = None

    def initialize(self):
        """AppDaemon required method for app init."""
        self._lights_dim = self.args.get('lights_dim', '').split(',')
        self._lights_off = self.args.get('lights_off', '').split(',')

        conf_data = dict(self.config['AppDaemon'])
        self._media_player = conf_data.get('media_player', None)
        self._notifier = conf_data.get('notifier', None)
        self._kodi_ip = conf_data.get('kodi_ip', '127.0.0.1')
        self._kodi_port = conf_data.get('kodi_port', 8080)
        self._kodi_user = conf_data.get('kodi_user', None)
        self._kodi_pass = conf_data.get('kodi_pass', None)

        # Listen for Kodi changes:
        self.listen_state(self.kodi_state, self._media_player)
        self.log('KodiAssist Initialized with dim_lights={}, off_lights={}'.format(self._lights_dim, self._lights_off))

    def _urlbase_and_auth(self):
        url_base = 'http://{}:{}/'.format(self._kodi_ip, self._kodi_port)
        auth = (self._kodi_user, self._kodi_pass) if self._kodi_user is not None else None
        return url_base, auth

    def kodi_is_playing_video(self):
        """Return True if kodi is playing video, False in any other case."""
        url_base, auth = self._urlbase_and_auth()
        data = {"request": json.dumps({"id": 1, "jsonrpc": "2.0", "method": "Player.GetActivePlayers"})}
        r = requests.get(url_base + 'jsonrpc', params=data, auth=auth,
                         headers={'Content-Type': 'application/json'}, timeout=5)
        if r.ok:
            res = r.json()
            if ('result' in res) and (len(res['result']) > 0):
                return res['result'][0]['type'] == 'video'
            return False
        self.log('KODI_IS_PLAYING_VIDEO? -> {}'.format(r.content), 'ERROR')
        return False

    def get_current_playing_item(self):
        """When kodi is playing something, retrieves its info."""
        url_base, auth = self._urlbase_and_auth()
        data_getitem = {"request": json.dumps(PARAMS_GET_ITEM)}
        ri = requests.get(url_base + 'jsonrpc', params=data_getitem, auth=auth,
                          headers={'Content-Type': 'application/json'}, timeout=5)
        if ri.ok:
            item = ri.json()['result']['item']
            return item
        else:
            self.log('No current playing item? -> {}'.format(ri.content), 'WARNING')
            return None

    def _make_ios_message(self, state, item=None):
        if item is None:
            title = "KODI state"
            message = "New state is *{}*".format(state)
            data_msg = {"title": title, "message": message}
        else:
            title = "{}: {}".format(state.capitalize() if state is not None else 'Playing', item['title'])
            if item['year']:
                title += " [{}]".format(item['year'])
            message = "{}\n∆T:{:.2f}h.".format(item['plot'], item['runtime'] / 3600)
            try:
                if 'poster' in item['art']:
                    k = 'poster'
                elif 'season.poster' in item['art']:
                    k = 'season.poster'
                else:
                    self.log('No poster in item[art]={}'.format(item['art']))
                    k = list(item['art'].keys())[0]
                img_url = parse.unquote_plus(item['art'][k]).rstrip('/').lstrip('image://')
                data_msg = {"title": title, "message": message,
                            "data": {"attachment": {"url": img_url.replace('http://', 'https://')}}}
                                     # "content-type": "jpg", "hide-thumbnail": "false"}}
                self.log('iOS MESSAGE: {}'.format(data_msg))
            except KeyError:
                data_msg = {"title": title, "message": message}
        return data_msg

    def _adjust_kodi_lights(self, play=True):
        for light_id in self._lights_dim + self._lights_off:
            if play:
                light_state = self.get_state(light_id)
                attrs_light = self.get_state(light_id, attribute='attributes')
                attrs_light.update({"state": light_state})
                self._light_states[light_id] = attrs_light
                if light_id in self._lights_off:
                    self.log('Apagando light {} para KODI PLAY'.format(light_id), LOG_LEVEL)
                    self.call_service("light/turn_off", entity_id=light_id, transition=2)
                elif ("brightness" in attrs_light.keys()) and (attrs_light["brightness"] > MAX_BRIGHTNESS_KODI):
                    self.log('Atenuando light {} para KODI PLAY'.format(light_id), LOG_LEVEL)
                    self.call_service("light/turn_on", entity_id=light_id, transition=2, brightness=MAX_BRIGHTNESS_KODI)
                else:
                    self.log('WTF light: {} -> {}'.format(light_id, attrs_light), 'ERROR')
            else:
                state_before = self._light_states[light_id]
                if ('state' in state_before) and (state_before['state'] == 'on'):
                    try:
                        new_state_attrs = {"xy_color": state_before["xy_color"],
                                           "brightness": state_before["brightness"]}
                    except KeyError:
                        new_state_attrs = {"color_temp": state_before["color_temp"],
                                           "brightness": state_before["brightness"]}
                    self.log('Reponiendo light {}, con state_before={}'.format(light_id, state_before), LOG_LEVEL)
                    self.call_service("light/turn_on", entity_id=light_id, transition=2, **new_state_attrs)
                else:
                    self.log('Doing nothing with light {}, state_before={}'.format(light_id, state_before), LOG_LEVEL)
                    # self.call_service("light/turn_off", entity_id=light_id, transition=2)

    # noinspection PyUnusedLocal
    def kodi_state(self, entity, attribute, old, new, kwargs):
        """Kodi state change main control."""
        if new == 'playing':
            self._is_playing_video = self.kodi_is_playing_video()
            self.log('KODI START. old:{}, new:{}, is_playing_video={}'
                     .format(old, new, self._is_playing_video), LOG_LEVEL)
            if self._is_playing_video:
                item_playing = self.get_current_playing_item()
                new_video = False
                if (self._item_playing is not None) or (self._item_playing != item_playing):
                    self._item_playing = item_playing
                    new_video = True

                now = ha.get_now()
                if (self._last_play is None) or (now - self._last_play > dt.timedelta(minutes=1)):
                    self._last_play = now
                    if new_video and (self._notifier is not None):  # Notify
                        self.call_service(self._notifier.replace('.', '/'),
                                          **self._make_ios_message(new, item=self._item_playing))

                self._adjust_kodi_lights(play=True)
        elif (old == 'playing') and self._is_playing_video:
            self._is_playing_video = False
            self._last_play = ha.get_now()
            self.log('KODI STOP. old:{}, new:{}, type_lp={}'.format(old, new, type(self._last_play)), LOG_LEVEL)
            # self.call_service('notify/ios_iphone', **self._make_ios_message(new))
            self._item_playing = None
            self._adjust_kodi_lights(play=False)
