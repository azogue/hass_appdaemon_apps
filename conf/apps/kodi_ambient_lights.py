# -*- coding: utf-8 -*-
"""
Automation task as a AppDaemon App for Home Assistant

This little app controls the ambient light when Kodi plays video,
dimming some lights and turning off others, and returning to the
initial state when the playback is finished.

In addition, it also sends notifications when starting the video playback,
reporting the video info in the message.
For that, it talks with Kodi through its JSONRPC API

"""
import datetime as dt
from urllib import parse
import appdaemon.appapi as appapi
import appdaemon.homeassistant as ha
from homeassistant.components.media_player.kodi import (
    EVENT_KODI_CALL_METHOD_RESULT)


# LOG_LEVEL = 'DEBUG'
LOG_LEVEL = 'INFO'

# {"method": "Player.GetItem", "entity_id": "media_player.kodi", "playerid": 1,
# "properties": ["title", "artist", "albumartist", "genre", "year", "rating",
# ... "dateadded", "runtime", "starttime", "endtime"]}
# {"method": "Player.GetItem", "entity_id": "media_player.kodi", "playerid": 1, "properties": ["title", "artist", "albumartist", "genre", "year", "rating", "album", "track", "duration", "playcount", "fanart", "plot", "originaltitle", "lastplayed", "firstaired", "season", "episode", "showtitle", "thumbnail", "file", "tvshowid", "watchedepisodes", "art", "description", "theme", "dateadded", "runtime", "starttime", "endtime"]}
# {"method": "Player.GetPlayers", "entity_id": "media_player.kodi"}

# {"method": "Player.GetItem", "entity_id": "media_player.kodi", "playerid": "1"}

METHOD_GET_PLAYERS = "Player.GetPlayers"
METHOD_GET_ITEM = "Player.GetItem"
PARAMS_GET_ITEM = {
    "playerid": 1,
    "properties": ["title", "artist", "albumartist", "genre", "year",
                   "rating", "album", "track", "duration", "playcount",
                   "fanart", "plot", "originaltitle", "lastplayed",
                   "firstaired", "season", "episode", "showtitle",
                   "thumbnail", "file", "tvshowid", "watchedepisodes",
                   "art", "description", "theme", "dateadded", "runtime",
                   "starttime", "endtime"]}
TYPE_ITEMS_NOTIFY = ['movie', 'episode']
# TYPE_ITEMS_IGNORE = ['channel', 'unknown']  # grabaciones: 'unknown'
# TELEGRAM_KEYBOARD_KODI = ['/luceson', '/ambilighttoggle, /ambilightconfig',
#                           '/pitemps, /tvshowsnext']
TELEGRAM_INLINEKEYBOARD_KODI = [
    [('Luces ON', '/luceson')],
    [('Switch Ambilight', '/ambilighttoggle'),
     ('Ch. config', '/ambilightconfig')],
    [('Tª', '/pitemps'), ('Next TvShows', '/tvshowsnext')]]


def _get_max_brightness_ambient_lights():
    if ha.now_is_between('09:00:00', '19:00:00'):
        return 200
    elif ha.now_is_between('19:00:00', '22:00:00'):
        return 150
    elif ha.now_is_between('22:00:00', '04:00:00'):
        return 75
    return 25


# noinspection PyClassHasNoInit
class KodiAssistant(appapi.AppDaemon):
    """App for Ambient light control when playing video with KODI."""

    _lights_dim = None
    _lights_off = None

    _media_player = None
    _kodi_ip = None
    _kodi_url = None
    _kodi_auth = None

    _notifier = None
    _notifier_bot = None

    _light_states = {}
    _is_playing_video = False
    _item_playing = None
    _last_play = None

    def initialize(self):
        """AppDaemon required method for app init."""
        self._lights_dim = self.args.get('lights_dim', '').split(',')
        self._lights_off = self.args.get('lights_off', '').split(',')

        conf_data = dict(self.config['AppDaemon'])
        self._media_player = conf_data.get('media_player')
        self._notifier = conf_data.get('notifier').replace('.', '/')
        self._notifier_bot = conf_data.get('bot_group').replace('.', '/')

        # Listen for Kodi changes:
        self.listen_state(self.kodi_state, self._media_player)
        self.listen_event(self._receive_kodi_result,
                          EVENT_KODI_CALL_METHOD_RESULT)
        self.log('KodiAssist Initialized with dim_lights={}, off_lights={}'
                 .format(self._lights_dim, self._lights_off))

    def _ask_for_playing_item(self):
        self.call_service('media_player/kodi_call_method',
                          entity_id=self._media_player,
                          method=METHOD_GET_ITEM, **PARAMS_GET_ITEM)

    # noinspection PyUnusedLocal
    def _receive_kodi_result(self, event_id, payload_event, *args):
        result = payload_event['result']
        method = payload_event['input']['method']
        if event_id == EVENT_KODI_CALL_METHOD_RESULT \
                and method == METHOD_GET_ITEM:
            self.log('DEBUG RECEIVE KODI IN AMBIENT LIGHTS: {}'.format(result))
            if 'item' in result:
                item_playing = result['item']
                self._is_playing_video = item_playing['type'] == 'video'
                if ((self._item_playing is None) or
                        (self._item_playing != item_playing)):
                    self._item_playing = item_playing
                    self._last_play = ha.get_now()
            else:
                self.log('RECEIVED BAD KODI RESULT: {}'
                         .format(result), 'warning')
        elif event_id == EVENT_KODI_CALL_METHOD_RESULT \
                and method == METHOD_GET_PLAYERS:
            self.log('KODI GET_PLAYERS RECEIVED: {}'.format(result))

    def _get_kodi_info_params(self, item):
        if item['type'] == 'episode':
            title = "{} S{:02d}E{:02d} {}".format(
                item['showtitle'], item['season'],
                item['episode'], item['title'])
        else:
            title = "Playing: {}".format(item['title'])
            if item['year']:
                title += " [{}]".format(item['year'])
        message = "{}\n∆T: {}.".format(
            item['plot'], dt.timedelta(hours=item['runtime'] / 3600))
        img_url = None
        try:
            if 'thumbnail' in item:
                raw_img_url = item['thumbnail']
            elif 'thumb' in item:
                raw_img_url = item['thumb']
            elif 'poster' in item['art']:
                raw_img_url = item['art']['poster']
            elif 'season.poster' in item['art']:
                raw_img_url = item['art']['season.poster']
            else:
                self.log('No poster in item[art]={}'.format(item['art']))
                k = list(item['art'].keys())[0]
                raw_img_url = item['art'][k]
            img_url = parse.unquote_plus(
                raw_img_url).rstrip('/').lstrip('image://')
            if (self._kodi_ip not in img_url) \
                    and img_url.startswith('http://'):
                img_url = img_url.replace('http:', 'https:')
            self.log('MESSAGE: T={}, M={}, URL={}'
                     .format(title, message, img_url))
        except KeyError as e:
            self.log('MESSAGE KeyError: {}; item={}'.format(e, item))
        return title, message, img_url

    def _make_ios_message(self, item):
        title, message, img_url = self._get_kodi_info_params(item)
        if img_url is not None:
            data_msg = {"title": title, "message": message,
                        "data": {"attachment": {"url": img_url},
                                 "push": {"category": "KODIPLAY"}}}
        else:
            data_msg = {"title": title, "message": message,
                        "data": {"push": {"category": "KODIPLAY"}}}
        return data_msg

    def _make_telegram_message(self, item):
        title, message, img_url = self._get_kodi_info_params(item)
        title = '*{}*'.format(title)
        if img_url is not None:
            message += "\n{}\n".format(img_url)
        data_msg = {"title": title, "message": message,
                    "data": {
                        # "keyboard": TELEGRAM_KEYBOARD_KODI,
                        "inline_keyboard": TELEGRAM_INLINEKEYBOARD_KODI,
                        "disable_notification": True}}
        return data_msg

    def _adjust_kodi_lights(self, play=True):
        for light_id in self._lights_dim + self._lights_off:
            if play:
                light_state = self.get_state(light_id)
                attrs_light = self.get_state(light_id, attribute='attributes')
                attrs_light.update({"state": light_state})
                self._light_states[light_id] = attrs_light
                max_brightness = _get_max_brightness_ambient_lights()
                if light_id in self._lights_off:
                    self.log('Apagando light {} para KODI PLAY'
                             .format(light_id), LOG_LEVEL)
                    self.call_service(
                        "light/turn_off", entity_id=light_id, transition=2)
                elif ("brightness" in attrs_light.keys()
                      ) and (attrs_light["brightness"] > max_brightness):
                    self.log('Atenuando light {} para KODI PLAY'
                             .format(light_id), LOG_LEVEL)
                    self.call_service("light/turn_on", entity_id=light_id,
                                      transition=2, brightness=max_brightness)
            else:
                try:
                    state_before = self._light_states[light_id]
                except KeyError:
                    state_before = {}
                if ('state' in state_before) \
                        and (state_before['state'] == 'on'):
                    try:
                        new_state_attrs = {
                            "xy_color": state_before["xy_color"],
                            "brightness": state_before["brightness"]}
                    except KeyError:
                        new_state_attrs = {
                            "color_temp": state_before["color_temp"],
                            "brightness": state_before["brightness"]}
                    self.log('Reponiendo light {}, con state_before={}'
                             .format(light_id, state_before), LOG_LEVEL)
                    self.call_service("light/turn_on", entity_id=light_id,
                                      transition=2, **new_state_attrs)
                else:
                    self.log('Doing nothing with light {}, state_before={}'
                             .format(light_id, state_before), LOG_LEVEL)

    # noinspection PyUnusedLocal
    def _kodi_react_to_state(self, kwargs):
        old = kwargs['old']
        new = kwargs['new']
        delta = ha.get_now() - self._last_play
        self.log('KODI START. old:{}, new:{}, is_playing_video={}'
                 .format(old, new, self._is_playing_video), LOG_LEVEL)
        if (self._is_playing_video
                and delta < dt.timedelta(seconds=15)
                and self._item_playing['type'] in TYPE_ITEMS_NOTIFY):
            self._adjust_kodi_lights(play=True)
            # Notifications
            self.call_service(
                self._notifier,
                **self._make_ios_message(self._item_playing))
            self.call_service(
                self._notifier_bot,
                **self._make_telegram_message(self._item_playing))

    # noinspection PyUnusedLocal
    def kodi_state(self, entity, attribute, old, new, kwargs):
        """Kodi state change main control."""
        if new == 'playing':
            self._ask_for_playing_item()
            self.run_in(self._kodi_react_to_state, 5, new=new, old=old)
        elif (old == 'playing') and (new == 'idle') and self._is_playing_video:
            self._is_playing_video = False
            self._last_play = ha.get_now()
            self.log('KODI STOP. old:{}, new:{}, type_lp={}'
                     .format(old, new, type(self._last_play)), LOG_LEVEL)
            self._item_playing = None
            self._adjust_kodi_lights(play=False)
