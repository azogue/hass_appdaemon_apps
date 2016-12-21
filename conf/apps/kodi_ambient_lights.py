# -*- coding: utf-8 -*-
import datetime as dt
import appdaemon.appapi as appapi
import requests
import json
from urllib import parse
import appdaemon.homeassistant as ha


LOG_LEVEL = 'DEBUG'
MAX_BRIGHTNESS_KODI = 75


data_getitem = {"request": json.dumps({"id": 1, "jsonrpc": "2.0", "method": "Player.GetItem",
                                       "params": {"playerid": 1,
                                                  "properties": ["title", "artist", "albumartist", "genre", "year",
                                                                 "rating", "album", "track", "duration", "playcount",
                                                                 "fanart", "plot", "originaltitle", "lastplayed",
                                                                 # "country","imdbnumber", "showlink", "streamdetails",
                                                                 # "resume", #"artistid", #"albumid", #"uniqueid",
                                                                 "firstaired", "season", "episode", "showtitle",
                                                                 "thumbnail", "file", "tvshowid", "watchedepisodes",
                                                                 "art", "description", "theme", "dateadded",
                                                                 "runtime", "starttime", "endtime"]}})}


# noinspection PyClassHasNoInit
class KodiAssistant(appapi.AppDaemon):
    """App for Ambient light control when playing video with KODI."""

    lights_dim = None
    lights_off = None

    media_player = None
    kodi_ip = None
    kodi_port = None
    kodi_user = None
    kodi_pass = None

    notifier = None

    light_states = {}
    is_playing_video = False
    item_playing = None
    last_play = None

    def initialize(self):
        """AppDaemon required method for app init."""
        self.lights_dim = self.args.get('lights_dim', '').split(',')
        self.lights_off = self.args.get('lights_off', '').split(',')

        self.media_player = self.args.get('media_player', None)
        self.notifier = self.args.get('notifier', None)
        self.kodi_ip = self.args.get('kodi_ip', '127.0.0.1')
        self.kodi_port = self.args.get('kodi_port', 8080)
        self.kodi_user = self.args.get('kodi_user', None)
        self.kodi_pass = self.args.get('kodi_pass', None)
        # Listen for Kodi changes:
        self.listen_state(self.kodi_state, self.media_player)
        # self.log('KodiAssist Initialized with dim_lights={}, off_lights={}'.format(self.lights_dim, self.lights_off))

    def _urlbase_and_auth(self):
        url_base = 'http://{}:{}/'.format(self.kodi_ip, self.kodi_port)
        auth = (self.kodi_user, self.kodi_pass) if self.kodi_user is not None else None
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
        ri = requests.get(url_base + 'jsonrpc', params=data_getitem, auth=auth,
                          headers={'Content-Type': 'application/json'}, timeout=5)
        if ri.ok:
            item = ri.json()['result']['item']
            # item['local_art'] = self.get_media_art(item)
            return item
        else:
            self.log('No current playing item? -> {}'.format(ri.content), 'WARNING')
            return None

    # def get_media_art(self, item):
    #     """Download art images to local file, from passed kodi media item."""
    #     d_art = item['art']
    #     # url_base, auth = self._urlbase_and_auth()
    #     d_art_local = {}
    #     for name, xbmc_path in d_art.items():
    #         image_url = parse.unquote_plus(xbmc_path).rstrip('/')
    #         self.log('image_url: "{}"'.format(image_url))
    #         # url_art = url_base + 'image/' + parse.quote_plus(xbmc_path)
    #         # rimg = requests.get(url_art, auth=auth, headers={'Content-Type': 'image/jpeg'})
    #         # if rimg.ok:
    #         #     ext = 'jpg' if 'jpg' in xbmc_path else 'png'
    #         #     local_file = os.path.join(t, '{}.{}'.format(name, ext))
    #         #     with open(local_file, 'wb') as f:
    #         #         f.write(rimg.content)
    #         #     d_art_local[name] = local_file
    #     return d_art_local

    @staticmethod
    def _make_ios_message(state, item=None):
        if item is None:
            title = "KODI state"
            message = "New state is *{}*".format(state)
            data_msg = {"title": title, "message": message}
        else:
            title = "KODI {} {} [{}]".format(state if state is not None else 'Playing:', item['title'], item['year'])
            message = "{}\nDuración: {:.2f}h.\nitem: {}".format(item['plot'], item['runtime'] / 3600, item)
            img_url = parse.unquote_plus(item['art']['poster']).rstrip('/').lstrip('image://')
            try:
                data_msg = {"title": title, "message": message,
                            "data": {"attachment": img_url, "content-type": "jpg", "hide-thumbnail": "false"}}
            except KeyError:
                data_msg = {"title": title, "message": message}
        return data_msg

    def _adjust_kodi_lights(self, play=True):
        for light_id in self.lights_dim + self.lights_off:
            if play:
                light_state = self.get_state(light_id)
                attrs_light = self.get_state(light_id, attribute='attributes')
                attrs_light.update({"state": light_state})
                self.light_states[light_id] = attrs_light
                if light_id in self.lights_off:
                    self.log('Apagando light {} para KODI PLAY'.format(light_id), LOG_LEVEL)
                    self.call_service("light/turn_off", entity_id=light_id, transition=2)
                elif ("brightness" in attrs_light.keys()) and (attrs_light["brightness"] > MAX_BRIGHTNESS_KODI):
                    self.log('Atenuando light {} para KODI PLAY'.format(light_id), LOG_LEVEL)
                    self.call_service("light/turn_on", entity_id=light_id, transition=2, brightness=MAX_BRIGHTNESS_KODI)
                else:
                    self.log('WTF light: {} -> {}'.format(light_id, attrs_light), 'ERROR')
            else:
                state_before = self.light_states[light_id]
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
                    self.log('Doing nothing with light {}, state_before={}'.format(light_id, state_before))
                    # self.call_service("light/turn_off", entity_id=light_id, transition=2)

    # noinspection PyUnusedLocal
    def kodi_state(self, entity, attribute, old, new, kwargs):
        """Kodi state change main control."""
        if new == 'playing':
            self.is_playing_video = self.kodi_is_playing_video()
            self.log('KODI START. old:{}, new:{}, is_playing_video={}'
                     .format(old, new, self.is_playing_video), LOG_LEVEL)
            if self.is_playing_video:
                item_playing = self.get_current_playing_item()

                new_video = False
                if (self.item_playing is not None) or (self.item_playing != item_playing):
                    self.item_playing = item_playing
                    new_video = True

                now = ha.get_now()
                if (self.last_play is None) or (now - self.last_play > dt.timedelta(minutes=1)):
                    self.last_play = now
                    if new_video and (self.notifier is not None):  # Notify
                        self.call_service(self.notifier, **self._make_ios_message(new, item=self.item_playing))

                self._adjust_kodi_lights(play=True)
        elif (old == 'playing') and self.is_playing_video:
            self.is_playing_video = False
            self.last_play = ha.get_now()
            self.log('KODI STOP. old:{}, new:{}, type_lp={}'.format(old, new, type(self.last_play)), LOG_LEVEL)
            # self.call_service('notify/ios_iphone', **self._make_ios_message(new))
            self.item_playing = None
            self._adjust_kodi_lights(play=False)
