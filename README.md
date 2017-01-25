# Personal automation apps (for [Home Assistant](https://home-assistant.io/) as [AppDaemon](https://github.com/home-assistant/appdaemon) apps)

Some home automation tasks for my personal use, integrated with my [personal config](https://github.com/azogue/hass_config) of [Home Assistant](https://home-assistant.io/), which is running 24/7 on a Raspberry PI 3 at home.

- **`enerpi_alarm.py`**: App for rich iOS notifications on power peaks (for *custom_component* **[enerPI current meter](https://github.com/azogue/enerpi)**).
- **`kodi_ambient_lights.py`**: Set ambient light when playing something with KODI; also, send iOS notifications with the plot of what's playing.
- **`morning_alarm_clock.py`**: Alarm clock app which simulates a fast dawn with Hue lights, while waking up the home cinema system, waiting for the start of the broadcast of La Cafetera radio program to start playing it (or, if the alarm is at a different time of the typical emision time, it just play the last published episode). It talks directly with KODI (through its JSONRPC API), which has to run a specific Kodi Add-On: [plugin.audio.lacafetera](https://github.com/azogue/plugin.audio.lacafetera). It also runs with Mopidy without any add-on, to play the audio stream in another RPI.
- **`motion_lights.py`**: App for control some hue lights for turning them ON with motion detection, only under some custom circunstances, like the media player is not running, or there aren't any more lights in 'on' state in the room.
- **`publish_states_in_master.py`**: App for posting state changes from sensors & binary_sensors in a 'slave' HA instance to another 'master' HA Instance.
- **`ios_events_listener.py`**: App for listen to and produce feedback from iOS notification actions.

- ... Other automations in active? development ...