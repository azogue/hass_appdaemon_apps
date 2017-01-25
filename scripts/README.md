# Script for running **Appdaemon HASS** as a service (systemd mode) in RPI Raspbian Jessie

Copy it in `/etc/systemd/system/appdaemon.service` and `sudo systemd enable appdaemon` to make it start at boot time.

## Appdaemon start / stop / status:

```
    sudo service appdaemon start | stop | status
```
