# Personal automation apps (for [Home Assistant](https://home-assistant.io/) as [AppDaemon](https://github.com/home-assistant/appdaemon) apps)

Some home automation tasks for my personal use, integrated with my [personal config](https://github.com/azogue/hass_config) of [Home Assistant](https://home-assistant.io/), which is running 24/7 on a Raspberry PI 3 at home.

- **[enerpi_alarm.py](https://github.com/azogue/hass_appdaemon_apps/blob/master/conf/apps/enerpi_alarm.py)**: App for rich iOS notifications on power peaks (for *custom_component* **[enerPI current meter](https://github.com/azogue/enerpi)**).
- **[kodi_ambient_lights.py](https://github.com/azogue/hass_appdaemon_apps/blob/master/conf/apps/kodi_ambient_lights.py)**: Set ambient light when playing something with KODI; also, send iOS notifications with the plot of what's playing and custom actions for light control.
- **[morning_alarm_clock.py](https://github.com/azogue/hass_appdaemon_apps/blob/master/conf/apps/morning_alarm_clock.py)**: Alarm clock app which simulates a fast dawn with Hue lights, while waking up the home cinema system, waiting for the start of the broadcast of La Cafetera radio program to start playing it (or, if the alarm is at a different time of the typical emision time, it just plays the last published episode). It talks directly with KODI (through its JSONRPC API), which has to run a specific Kodi Add-On: [plugin.audio.lacafetera](https://github.com/azogue/plugin.audio.lacafetera). It also runs with Mopidy without any add-on, to play the audio stream in another RPI. Also, with custom iOS notifications, I can postpone the alarm (+X min) or turn off directly.
- **[motion_lights.py](https://github.com/azogue/hass_appdaemon_apps/blob/master/conf/apps/motion_lights.py)**: App for control some hue lights for turning them ON with motion detection, only under some custom circunstances, like the media player is not running, or there aren't any more lights in 'on' state in the room.
- **[publish_states_in_master.py](https://github.com/azogue/hass_appdaemon_apps/blob/master/conf/apps/publish_states_in_master.py)**: App for posting state changes from sensors & binary_sensors from a 'slave' HA instance to another 'master' HA Instance.
- **[bot_event_listener.py](https://github.com/azogue/hass_appdaemon_apps/blob/master/conf/apps/bot_event_listener.py)**: App for listen to and produce feedback in a conversation with a Telegram Bot (including not only sending complex commands but a HASS wizard too), or from iOS notification action pressed.
- **[motion_alarm_push_email.py](https://github.com/azogue/hass_appdaemon_apps/blob/master/conf/apps/enerpi_alarm.py):** Complex motion detection alarm with multiple actuators, BT sensing, pre-alarm logic, push notifications, rich html emails, and some configuration options.
- ... Other automations in active? development ...

```

*Switchs*:
{% for state in states.switch%}
- {{state.attributes.friendly_name}} --> {{state.state}} [{{relative_time(state.last_changed)}}]{% endfor %}

*Binary sensors*:
{% for state in states.binary_sensor%}
- {{state.attributes.friendly_name}} [{{state.attributes.device_class}}] --> {{state.state}} [{{relative_time(state.last_changed)}}]{% endfor %}

*Sensors*:
{% for state in states.sensor%}
- {{state.attributes.friendly_name}} --> {{state.state}} [{{relative_time(state.last_changed)}}]{% endfor %}

*Lights*:
{% for state in states.light%}
- {{state.attributes.friendly_name}} --> {{state.state}} [{{relative_time(state.last_changed)}}]{% endfor %}


```

**v0.7** - Cambios en sistema de alarma:
- Se puede definir un tiempo máximo de alarma conectada (pasado éste, la alarma sigue activada pero vuelve al estado de reposo; también apaga los relés asociados)
- Se puede definir un tiempo de repetición del aviso de alarma activada, mientras no se apague o resetee.
- Se pueden definir luces RGB para simular una sirena visual cuando salte la alarma.
- Con la alarma activada, se toma nota de los dispositivos BT que entran en escena.



# '''*Switchs*:
# {% for state in states.switch%}
# - {{state.attributes.friendly_name}} --> {{state.state}} [{{relative_time(state.last_changed)}}]{% endfor %}
#
# *Binary sensors*:
# {% for state in states.binary_sensor%}
# - {{state.attributes.friendly_name}} [{{state.attributes.device_class}}] --> {{state.state}} [{{relative_time(state.last_changed)}}]{% endfor %}
#
# *Sensors*:
# {% for state in states.sensor%}
# - {{state.attributes.friendly_name}} --> {{state.state}} [{{relative_time(state.last_changed)}}]{% endfor %}
#
# *Lights*:
# {% for state in states.light%}
# - {{state.attributes.friendly_name}} --> {{state.state}} [{{relative_time(state.last_changed)}}]{% endfor %}
#
#
# *Switchs*:
# {% for state in states.switch%}
# - {{state.attributes.entity_id}} --> {{state.state}} [{{relative_time(state.last_changed)}}]{% endfor %}
#
# *Binary sensors*:
# {% for state in states.binary_sensor%}
# - {{state.entity_id}} [{{state.attributes.device_class}}] --> {{state.state}} [{{relative_time(state.last_changed)}}]{% endfor %}
#
# *Sensors*:
# {% for state in states.sensor%}
# - {{state.entity_id}} --> {{state.state}} [{{relative_time(state.last_changed)}}]{% endfor %}
#
# *Lights*:
# {% for state in states.light%}
# - {{state.entity_id}} --> {{state.state}} [{{relative_time(state.last_changed)}}]{% endfor %}
#

#
#
# - switch.systemd_appdaemon --> on [1 hour]
# - switch.systemd_homebridge --> on [1 hour]
# - switch.toggle_config_kodi_ambilight --> on [1 hour]
#
# *Binary sensors*:
#
# - binary_sensor.email_online [connectivity] --> on [1 hour]
# - binary_sensor.internet_online [connectivity] --> on [1 hour]
# - binary_sensor.ios_online [connectivity] --> on [1 hour]
# - binary_sensor.kodi_online [connectivity] --> on [1 hour]
#
# - binary_sensor.pushbullet_online [connectivity] --> on [1 hour]
# - binary_sensor.router_on [connectivity] --> on [1 hour]
# - binary_sensor.services_notok [safety] --> off [1 hour]
# - binary_sensor.telegram_online [connectivity] --> on [1 hour]
#
# *Sensors*:
#
# - sensor.alarm_clock_hour --> 8 [1 hour]
# - sensor.alarm_clock_minute --> 0 [1 hour]
#
# - sensor.cpu_use --> 3 [27 seconds]
# - sensor.cpu_use_rpi2h --> 4 [16 seconds]
# - sensor.cpu_use_rpi2mpd --> 2 [1 minute]
#
# - sensor.disk_use_home --> 30.0 [59 minutes]
# - sensor.error_counter_notifiers --> 0 [1 hour]
#
#
# - sensor.ip_externa --> 185.97.169.163 [1 hour]
# - sensor.iphone_battery_level --> 74 [1 hour]
# - sensor.iphone_battery_state --> Unplugged [1 hour]
# - sensor.last_boot --> 2017-03-24 [1 hour]
# - sensor.ram_free --> 654.7 [27 seconds]
# - sensor.ram_free_rpi2h --> 393.2 [47 seconds]
# - sensor.ram_free_rpi2mpd --> 594.3 [1 second]
#
# - sensor.speedtest_download --> 46.81 [11 minutes]
# - sensor.speedtest_ping --> 19.21 [11 minutes]
# - sensor.speedtest_upload --> 9.14 [11 minutes]
#
# - sensor.villena_cloud_coverage --> 20 [1 hour]
# - sensor.villena_condition --> few clouds [1 hour]
# - sensor.villena_forecast --> Clouds [1 hour]
# - sensor.villena_humidity --> 50 [58 minutes]
# - sensor.villena_pressure --> 1013 [1 hour]
# - sensor.villena_rain --> not raining [1 hour]
# - sensor.villena_temperature --> 14.0 [1 hour]
# - sensor.villena_wind_speed --> 2.6 [8 seconds]
# - sensor.warning_counter_core --> 0 [1 hour]
# - sensor.yr_symbol --> 2 [1 hour]
