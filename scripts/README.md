# Script for running **Appdaemon HASS** as a service (systemd mode) in RPI Raspbian Jessie

Copy it in `/etc/systemd/system/appdaemon.service` and, with user PI, `sudo systemd enable appdaemon` to make it start at boottime

## Appdaemon start / stop / status:

```
    sudo service appdaemon start | stop | status
```
