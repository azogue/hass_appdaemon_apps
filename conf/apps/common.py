# -*- coding: utf-8 -*-
"""
Common vars and global variable setter
"""
import appdaemon.conf as conf


GLOBAL_ALARM_STATE = 'alarm_state'
GLOBAL_ANYBODY_HOME = 'anybody_home'
GLOBAL_BASE_URL = 'base_url'
GLOBAL_DEFAULT_CHATID = 'default_chat_id'
GLOBAL_PEOPLE_HOME = 'people_home'


def set_global(app, key, value):
    """Set a key, value pair in AppDaemon Global vars."""
    with conf.ha_state_lock:
        app.global_vars[key] = value


def get_global(app, key, default=None):
    """Get a value from AppDaemon Global vars."""
    with conf.ha_state_lock:
        if key in app.global_vars:
            return app.global_vars[key]
        else:
            return default
