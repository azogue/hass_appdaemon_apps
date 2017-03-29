# -*- coding: utf-8 -*-
"""
Automation task as a AppDaemon App for Home Assistant

Event listener for actions triggered from a Telegram Bot chat
or from iOS notification actions.

Harcoded custom logic for controlling HA with feedback from these actions.

"""
import appdaemon.appapi as appapi
import appdaemon.conf as conf
import datetime as dt
import paramiko
import subprocess
from random import randrange
import re
from time import time


LOG_LEVEL = 'INFO'

##################################################
# Colors, regexprs...
##################################################
XY_COLORS = {"red": [0.6736, 0.3221], "blue": [0.1684, 0.0416],
             "orange": [0.5825, 0.3901], "yellow": [0.4925, 0.4833],
             "green": [0.4084, 0.5168], "violet": [0.3425, 0.1383]}
RG_COLOR = re.compile('(\\x1b\[\d{1,2}m)')

##################################################
# Text templates (persistent notifications)
##################################################
DEFAULT_NOTIF_MASK = "Recibido en {:%d/%m/%y %H:%M:%S} desde {}. Raw: {}."
NOTIF_MASK_ALARM_ON = "ALARMA CONECTADA en {:%d/%m/%y %H:%M:%S}, desde '{}'."
NOTIF_MASK_LIGHTS_ON = "Encendido de luces del salón a las " \
                       "{:%d/%m/%y %H:%M:%S}, desde '{}'."
NOTIF_MASK_LIGHTS_OFF = "APAGADO DE LUCES a las {:%d/%m/%y %H:%M:%S}, " \
                        "desde '{}'."
NOTIF_MASK_ALARM_HOME = "Vigilancia conectada en casa a las " \
                        "{:%d/%m/%y %H:%M:%S}, desde '{}'."
NOTIF_MASK_ALARM_SILENT = "Se silencia la alarma a las " \
                          "{:%d/%m/%y %H:%M:%S}, desde '{}'."
NOTIF_MASK_ALARM_RESET = "Se ignora el estado de alarma, reset a las " \
                         "{:%d/%m/%y %H:%M:%S}, desde '{}'."
NOTIF_MASK_ALARM_OFF = "ALARMA DESCONECTADA en {:%d/%m/%y %H:%M:%S}, " \
                       "desde '{}'."
NOTIF_MASK_TOGGLE_AMB = "Cambio en modo Ambilight: " \
                        "{:%d/%m/%y %H:%M:%S}, desde '{}'."
NOTIF_MASK_TOGGLE_AMB_CONF = "Cambio en configuración de Ambilight (# de " \
                             "bombillas) {:%d/%m/%y %H:%M:%S}, desde '{}'."
NOTIF_MASK_ALARMCLOCK_OFF = "{:%d/%m/%y %H:%M:%S}: Apagado de " \
                            "despertador (desde '{}')."
NOTIF_MASK_POSTPONE_ALARMCLOCK = "{:%d/%m/%y %H:%M:%S}: Postponer " \
                                 "despertador (desde '{}')."
NOTIF_MASK_INIT_DAY = "{:%d/%m/%y %H:%M:%S}: A la ducha! Luces y " \
                      "Calefactor ON (desde '{}')."
NOTIF_MASK_LAST_VALIDATION = "Validación a las {:%d/%m/%y %H:%M:%S}, " \
                             "desde '{}'."

##################################################
# Telegram commands & HASS wizard
##################################################
TELEGRAM_BOT_HELP = '''*Comandos disponibles*:
/start - Muestra el mensaje de bienvenida y un teclado con comandos de ejemplo.
/init - Ejecuta la misma acción que /start.
/hasswiz - Inicia el asistente para interactuar con Home Assistant.
/status - Devuelve información actual de los sensores de la casa.
/hastatus - Devuelve información sobre el funcionamiento de Home Assistant.
/getcams - Devuelve instantáneas de las cámaras de la casa.
/template - Render del texto pasado como argumentos.
/html - Render del texto pasado usando el parser HTML.
/enerpi - Muestra información general sobre el consumo eléctrico actual.
/enerpifact - IMPLEMENTAR
/enerpitiles - Gráficas de 24h del sensor enerPI.
/enerpikwh - Gráfica de 24h del consumo eléctrico en kWh y € de factura.
/enerpipower - Muestra la gráfica de 24h de la potencia eléctrica.
/armado - Activar la alarma.
/vigilancia - Activar modo de vigilancia simple.
/lucesoff - Apagar las luces de casa.
/llegada - Apagar la alarma y encender las luces.
/llegadatv - Apagar la alarma y encender las luces y la tele.
/ignorar - Resetear el estado de alarma.
/silenciar - Silenciar la sirena de alarma.
/resetalarm - Ignorar el armado de alarma y resetearla.
/desconectar - Desconectar la alarma.
/confirmar - Validar.
/luceson - Luces del salón al 100%.
/ambilighttoggle - Cambio del modo Ambilight (encender/apagar).
/ambilightconfig - Cambio de la configuración de Ambilight.
/ducha - Luces de dormitorio en 'Energy' y encendido del calefactor.
/posponer - Posponer despertador unos minutos más.
/despertadoroff - Luces de dormitorio en 'Energy'.
/pitemps - Muestra la temperatura de la RPI.
/cathass - Muestra el LOG de Home Assistant.
/catappd - Muestra el LOG de AppDaemon.
/catappderr - Muestra el LOG de errores de AppDaemon.
/shell - Ejecuta un comando en el shell del host de HA (RPI3).
/osmc - Ejecuta un comando en el shell de la RPI3 del Salón.
/osmcmail - Muestra el syslog de la máquina OSMC.
/rpi2 - Ejecuta un comando en el shell de la RPI2 del dormitorio.
/rpi2h - Ejecuta un comando en el shell de la RPI2 del Estudio.
/rpi - Ejecuta un comando en el shell de la RPI de Galería.
/tvshowscron - Muestra la tabla CRON del TvShows Downloader.
/tvshowsinfo - Muestra información sobre la serie pasada como argumento.
/tvshowsdd - Descarga de capítulos: '/tvshowsdd game of thrones s02e10'.
/tvshowsnext - Muestra los capítulos de series de próxima emisión.
/help - Muestra la descripción de los comandos disponibles.'''
# /confirmar - Validar.
# /yes': 'CAM_YES',  # Validar
# /no': 'CAM_NO',  # Validar
# /input': 'INPUTORDER'}  # Tell me ('textInput')

TELEGRAM_SHELL_CMDS = ['/shell', '/osmc', '/osmcmail', '/rpi2', '/rpi2h',
                       '/rpi', '/pitemps',
                       '/cathass', '/catappd', '/catappderr', '/tvshowscron',
                       '/tvshowsinfo', '/tvshowsdd', '/tvshowsnext']
TELEGRAM_HASS_CMDS = ['/getcams', '/status', '/hastatus', '/html', '/template',
                      '/help', '/start',
                      '/enerpi', '/enerpifact', '/enerpitiles',
                      '/enerpikwh', '/enerpipower', '/init', '/hasswiz']
TELEGRAM_IOS_COMMANDS = {  # AWAY category
                         '/armado': 'ALARM_ARM_NOW',  # Activar alarma
                         '/vigilancia': 'ALARM_HOME',  # Activar vigilancia
                         '/lucesoff': 'LIGHTS_OFF',  # Apagar luces
                         # INHOME category
                         '/llegada': 'WELCOME_HOME',  # Alarm OFF, lights ON
                         '/llegadatv': 'WELCOME_HOME_TV',  # AlarmOFF, lightsON
                         '/ignorar': 'IGNORE_HOME',  # Reset alarm state
                         # ALARM category
                         '/silenciar': 'ALARM_SILENT',  # Silenciar sirena
                         '/resetalarm': 'ALARM_RESET',  # Ignorar armado y reset
                         '/desconectar': 'ALARM_CANCEL',  # Desconectar alarma
                         # CONFIRM category
                         '/confirmar': 'CONFIRM_OK',  # Validar
                         # CAMERA category
                         '/yes': 'CAM_YES',  # Validar
                         '/no': 'CAM_NO',  # Validar
                         # KODIPLAY category
                         '/luceson': 'LIGHTS_ON',  # Lights ON!
                         '/ambilighttoggle': 'HYPERION_TOGGLE',
                         '/ambilightconfig': 'HYPERION_CHANGE',
                         # ALARMCLOCK category
                         '/ducha': 'INIT_DAY',  # Luces Energy + Calefactor ON
                         '/posponer': 'POSTPONE_ALARMCLOCK',  # Postponer alarm
                         '/despertadoroff': 'ALARMCLOCK_OFF',  # Luces Energy
                         '/input': 'INPUTORDER'}  # Tell me ('textInput')

COMMAND_PREFIX = '/'
COMMAND_WIZARD_OPTION = 'op:'
TELEGRAM_INLINE_KEYBOARD = [
    [('ARMADO', '/armado'), ('Apaga las luces', '/lucesoff')],
    [('Llegada', '/llegada'), ('Llegada con TV', '/llegadatv')],
    [('Enciende luces', '/luceson'), ('Ambilight', '/ambilighttoggle')],
    [('Estado general', '/status'), ('HA status', '/hastatus')],
    [('LOG HA', '/cathass'), ('LOG', '/catappd'), ('LOG ERR', '/catappderr')],
    [('ENERGY', '/enerpi'), ('CAMS', '/getcams')],
    [('Home assistant wizard!', '/hasswiz'), ('Ayuda', '/help')]
]
TELEGRAM_UNKNOWN = [
    'Cachis, no te he entendido eso de *{}*',
    'FORMATEAR TODO EN 5 segundos...\nEs broma, no voy a hacer ná de *{}*',
    'Prefiero no hacer eso de *{}*. No me van las cosas nuevas...',
    'Ein?, what is *{}*?',
    'Jopetas, no te pillo una, qué es eso de *{}*?',
    'No comprendo *{}*',
    'CMD *{}* NOT IMPLEMENTED!, Vamos, que ná de ná',
    "Sorry, I can't understand this: *{}*"
]

TELEGRAM_KEYBOARD = ['/armado, /lucesoff',
                     '/llegada, /llegadatv',
                     '/luceson, /ambilighttoggle',
                     '/cathass, /catappd, /catappderr',
                     '/enerpi, /enerpitiles, /getcams',
                     '/status, /hastatus, /help'
                     '/hasswiz, /init']
TELEGRAM_INLINE_KEYBOARD_ENERPI = [
    [('Apaga luces', '/lucesoff'), ('Enciende luces', '/luceson')],
    [('Potencia eléctrica', '/enerpi'), ('Consumo 24h', '/enerpikwh')],
    [('Potencia 24h', '/enerpipower'), ('Grafs. enerPI', '/enerpitiles')]
]
TELEGRAM_KEYBOARD_ENERPI = ['/lucesoff, /luceson',
                            '/enerpi, /enerpikwh',
                            '/enerpipower, /enerpitiles']
ENERPI_TILES = ['enerpi_tile_kwh', 'enerpi_tile_power', 'enerpi_tile_ldr']
ENERPI_TILES_DESC = ['Consumo en kWh y € (24h)', 'Potencia eléctrica, W (24h)',
                     'Iluminación']

HASSWIZ_MENU_ACTIONS = [("Anterior ⬅︎", "op:back"),
                        ("Inicio ▲", "op:reset"), ("Salir ✕", "op:exit")]
HASSWIZ_TYPES = ["switch", "light", "group", "sensor", "binary_sensor"]
HASSWIZ_STEPS = [
    {
        "question": "¿Qué *tipo de elemento* quieres controlar o consultar?",
        "options": [[("Interruptor", "op:switch"), ("Luz", "op:light")],
                    [("Grupo", "op:group"), ("Sensor", "op:sensor"),
                     ("Indicador", "op:binary_sensor")],
                    HASSWIZ_MENU_ACTIONS[2:]]
    },
    {
        "question": "¿Qué acción quieres realizar "
                    "con el tipo de elemento *{}*?",
        "options": [[("Encender", "op:turn_on"), ("Apagar", "op:turn_off")],
                    [("Estado", "op:state"), ("Atributos", "op:attributes")],
                    HASSWIZ_MENU_ACTIONS[1:]]
    },
    {
        "question": "Selecciona un elemento para "
                    "realizar acciones *{}* sobre él:",
        "options": None
    },
]

##################################################
# Remote SSH shell control
##################################################
PATH_SSH_KEY = '/home/homeassistant/.ssh/id_rsa'
SSH_PYTHON_ENVS_PREFIX = {
    'rpi3osmc': "/bin/bash /home/{0}/.bashrc; "
                "export PYTHONPATH=$PYTHONPATH:/home/{0}/PYTHON/; "
                "/home/{0}/miniconda/envs/py35/bin/",
    'rpi2h': "/bin/bash /home/{0}/.bashrc;"
             "export PYTHONPATH=$PYTHONPATH:/home/{0}/PYTHON/;"
             "/home/{0}/.pyenv/shims/",
    'rpi2': "/bin/bash /home/{0}/.bashrc;"
             "export PYTHONPATH=$PYTHONPATH:/home/{0}/PYTHON/;"
             "source /home/{0}/PYTHON/py35/bin/activate"
             "export PYTHONPATH=$PYTHONPATH:/home/{0}/PYTHON/:"
             "/home/{0}/PYTHON/py35/lib/python3.5/site-packages"
             "/home/{0}/PYTHON/py35/bin/"
}

##################################################
# Templates
##################################################
CMD_STATUS_TITLE = "*Estado de la casa*:"
CMD_STATUS_TEMPL_SALON = '''*Salón*:
*LUCES* -> {{states.light.salon.state}} ({{relative_time(states.light.salon.last_changed)}})
- Tª: {% if states.sensor.salon_temperature %}{{(((states.sensor.salon_temperature.state|float) + (states.sensor.t_salon.state|float)) / 2)|round(1)}}{% else %}{{ states.sensor.t_salon.state }}{% endif %} ºC
- HR: {{states.sensor.salon_humidity.state}} %
- Mov: {{states.binary_sensor.pir_salon.state}} ({{relative_time(states.binary_sensor.pir_salon.last_changed)}})
- VMov: {{states.binary_sensor.motioncam_salon.state}} ({{relative_time(states.binary_sensor.motioncam_salon.last_changed)}})
{{states.switch.camara.attributes.friendly_name}}: {{states.switch.camara.state}} ({{relative_time(states.switch.camara.last_changed)}})
{{states.switch.kodi_tv_salon.attributes.friendly_name}}: {{states.switch.kodi_tv_salon.state}} ({{relative_time(states.switch.kodi_tv_salon.last_changed)}})
Ambilight: {{states.switch.toggle_kodi_ambilight.state}} ({{relative_time(states.switch.toggle_kodi_ambilight.last_changed)}})
KODI: {{states.media_player.kodi.state}} ({{relative_time(states.media_player.kodi.last_changed)}})

*{{states.light.bola_grande.attributes.friendly_name}}* -> {{states.light.bola_grande.state}} ({{relative_time(states.light.bola_grande.last_changed)}})
*{{states.light.bola_pequena.attributes.friendly_name}}* -> {{states.light.bola_pequena.state}} ({{relative_time(states.light.bola_pequena.last_changed)}})
*{{states.light.cuenco.attributes.friendly_name}}* -> {{states.light.cuenco.state}} ({{relative_time(states.light.cuenco.last_changed)}})
*{{states.light.lamparita.attributes.friendly_name}}* -> {{states.light.lamparita.state}} ({{relative_time(states.light.lamparita.last_changed)}})
*{{states.light.pie_tv.attributes.friendly_name}}* -> {{states.light.pie_tv.state}} ({{relative_time(states.light.pie_tv.last_changed)}})
*{{states.light.pie_sofa.attributes.friendly_name}}* -> {{states.light.pie_sofa.state}} ({{relative_time(states.light.pie_sofa.last_changed)}})'''
CMD_STATUS_TEMPL_DORM = '''*Dormitorio*:
*LUCES* -> {{states.light.dormitorio.state}} ({{relative_time(states.light.dormitorio.last_changed)}})
- Tª: {% if states.sensor.dht22_dormitorio_temperature_rpi2mpd.state != 'unknown' %}{{(((states.sensor.dht22_dormitorio_temperature_rpi2mpd.state|float) + (states.sensor.temperatura_dormitorio_rpi2mpd.state|float)) / 2)|round(1)}}{% else %}{{ states.sensor.temperatura_dormitorio_rpi2mpd.state }}{% endif %} ºC
- HR: {{states.sensor.dht22_dormitorio_humidity_rpi2mpd.state}} %
- Mov: {{states.binary_sensor.pir_dormitorio_rpi2mpd.state}} ({{relative_time(states.binary_sensor.pir_dormitorio_rpi2mpd.last_changed)}})
Altavoz: {{states.switch.altavoz.state}} ({{relative_time(states.switch.altavoz.last_changed)}})
Mopidy: {{states.media_player.dormitorio_mopidy.state}} ({{relative_time(states.media_player.dormitorio_mopidy.last_changed)}})
Despertador ({{states.switch.alarm_clock_status.state}}) a las {{states.sensor.alarm_clock_time.state}}.
{{states.switch.calefactor.attributes.friendly_name}}: {{states.switch.calefactor.state}} ({{relative_time(states.switch.calefactor.last_changed)}})

*Luz* -> {{states.light.hue_habitacion.state}} ({{relative_time(states.light.hue_habitacion.last_changed)}})
*Lamparita* -> {{states.light.aura_habitacion.state}} ({{relative_time(states.light.aura_habitacion.last_changed)}})'''
CMD_STATUS_TEMPL_ESTUDIO = '''*Estudio*:
*LUCES* -> {{states.light.estudio.state}} ({{relative_time(states.light.estudio.last_changed)}})
- Tª: {% if states.sensor.dht22_temperature_rpi2h.state != 'unknown' %}{{(((states.sensor.dht22_temperature_rpi2h.state|float) + (states.sensor.temperatura_estudio_rpi2h.state|float)) / 2)|round(1)}}{% else %}{{ states.sensor.temperatura_estudio_rpi2h.state }}{% endif %} ºC
- HR: {{states.sensor.dht22_humidity_rpi2h.state}} %
- Tªh: {{states.sensor.temperature_rpi2h.state}} ºC
- HRh: {{states.sensor.humidity_rpi2h.state}} %
- Presión: {{states.sensor.pressure_rpi2h.state}} mbar
- Mov: {{states.binary_sensor.pir_estudio_rpi2h.state}} ({{relative_time(states.binary_sensor.pir_estudio_rpi2h.last_changed)}})
- VMov: {{states.binary_sensor.motioncam_estudio.state}} ({{relative_time(states.binary_sensor.motioncam_estudio.last_changed)}})
- Vibr: {{states.binary_sensor.vibration_sensor_rpi2h.state}} ({{relative_time(states.binary_sensor.vibration_sensor_rpi2h.last_changed)}})
Enchufe Impresora: {{states.switch.impresora.state}} ({{relative_time(states.switch.impresora.last_changed)}})

*Flexo* -> {{states.light.flexo.state}} ({{relative_time(states.light.flexo.last_changed)}})'''
CMD_STATUS_TEMPL_GALERIA = '''*Galería*:
- Tª: {{states.sensor.galeria_dht22_temperature.state}} ºC
- HR: {{states.sensor.galeria_dht22_humidity.state}} %'''
CMD_STATUS_TEMPL_HEATER = '''*Caldera*:
{{states.switch.caldera.attributes.friendly_name}}: {{states.switch.caldera.state}} ({{relative_time(states.switch.caldera.last_changed)}})
- Calefacción: {{states.binary_sensor.heating.state}} ({{relative_time(states.binary_sensor.heating.last_changed)}}), status: {{states.sensor.calefaccion.state}} ({{relative_time(states.sensor.calefaccion.last_changed)}})
- ACS: {{states.sensor.galeria_acs.state}} ºC
- Impulsión: {{states.sensor.galeria_impulsion_calefaccion.state}} ºC
- Retorno: {{states.sensor.galeria_retorno_calefaccion.state}} ºC'''
CMD_STATUS_TEMPL_RESTO = '''*Resto*:
*{{states.switch.switch_master_alarm.attributes.friendly_name}}: {{states.switch.switch_master_alarm.state}} ({{relative_time(states.switch.switch_master_alarm.last_changed)}})*

*{{states.switch.cocina.attributes.friendly_name}}* -> {{states.switch.cocina.state}} ({{relative_time(states.switch.cocina.last_changed)}})
'''
CMD_STATUS_TEMPL_ENERPI = '''*Consumo eléctrico*:
- Potencia: *{{states.sensor.enerpi_power.state}} W* ({{states.sensor.enerpi.state}}, P5min: {{ states.sensor.enerpi.attributes['Power 5min (W)']|round() }} W)
- Pico hoy: {{ states.sensor.enerpi.attributes['Power Peak (today)'] }} W
- Consumo hoy: *{{ states.sensor.enerpi.attributes['Consumption Day (Wh)']|multiply(0.001)|round(2) }} kWh*
- Consumo últimos días: {{ states.sensor.enerpi.attributes['Consumption Week (kWh)'] |replace(",", "; ") }} kWh
  Ilum: {{states.sensor.enerpi_ldr.state}} %'''
CMD_STATUS_TEMPL_ESP32 = '''*ESP8266*:
- Tª: {{states.sensor.esp1_temperature.state}} ºC
- HR: {{states.sensor.esp1_humidity.state}} %'''

CMD_TEMPL_HASS_STATUS = '''*HASS Status*:
*¿Problemas? -> {{states.binary_sensor.services_notok.state}}* ({{relative_time(states.binary_sensor.services_notok.last_changed)}})
- IP: {{states.sensor.ip_externa.state}}
- Internet: *{{states.binary_sensor.internet_online.state}}*, Router: {{states.binary_sensor.router_on.state}}, DL {{states.sensor.speedtest_download.state|int}} Mbps / UL {{states.sensor.speedtest_upload.state|int}} Mbps / ping {{states.sensor.speedtest_ping.state|int}}ms
Servicios:
- AppDaemon: *{{states.switch.systemd_appdaemon.state}}* ({{relative_time(states.switch.systemd_appdaemon.last_changed)}})
- Homebridge: *{{states.switch.systemd_homebridge.state}}* ({{relative_time(states.switch.systemd_homebridge.last_changed)}})
- Notify: Telegram {{states.binary_sensor.telegram_online.state}}, iOS {{states.binary_sensor.ios_online.state}}, Pushbullet {{states.binary_sensor.pushbullet_online.state}}, email {{states.binary_sensor.email_online.state}}, Kodi {{states.binary_sensor.kodi_online.state}}.
Funcionando desde {{states.sensor.last_boot.state}} (HASS {{relative_time(states.sensor.last_boot.last_changed)}}). CPU al {{states.sensor.cpu_use.state}} %, RAM FREE {{states.sensor.ram_free.state}} MB, SD al {{states.sensor.disk_use_home.state}} %.
- {{states.sensor.error_counter_notifiers.state}} warnings de notificación.
- {{states.sensor.warning_counter_core.state}} core warnings.
- {{states.sensor.core_error_counter.state}} core errors.'''

# Custom shell script for capture a pic from a HASS camera:
CMD_MAKE_HASS_PIC = '/home/homeassistant/.homeassistant/shell/capture_pic.sh ' \
                    'snapshot_cameras/{cam_filename} {img_url} {hass_pw}'


def _clean(telegram_text):
    """Remove markdown characters to prevent
    Telegram parser to fail ('_' & '*' chars)."""
    return telegram_text.replace('_', '\_').replace('*', '')


# noinspection PyClassHasNoInit
class EventListener(appapi.AppDaemon):
    """Event listener for ios.notification_action_fired,
    Telegram bot events and the family tracker."""

    _config = None
    _lights_notif = None
    _lights_notif_state = None
    _lights_notif_st_attr = None
    _notifier = None
    _bot_notifier = None
    _bot_wizstack = None
    _bot_chatids = None
    _bot_users = None

    # Family Tracker
    _tracking_state = None

    # Alarm state
    _alarm_state = False

    # HASS entities:
    _hass_entities = None

    def initialize(self):
        """AppDaemon required method for app init."""
        self._config = dict(self.config['AppDaemon'])
        self._notifier = self._config.get('notifier').replace('.', '/')
        self._bot_notifier = self._config.get('bot_notifier').replace('.', '/')
        _chatids = [int(x) for x in self._config.get('bot_chatids').split(',')]
        _nicknames = self._config.get('bot_nicknames').split(',')
        self._bot_chatids = _chatids
        self._bot_users = {c: u for c, u in zip(self._bot_chatids, _nicknames)}
        self._lights_notif = self.args.get('lights_notif', 'light.cuenco')
        self._bot_wizstack = {user: [] for user in self._bot_users.keys()}

        # iOS app notification actions
        [self.listen_event(self.receive_ios_event, ev)
         for ev in ['ios.notification_action_fired',
                    'ios_iphone.notification_action_fired']]

        # Telegram Bot
        [self.listen_event(self.receive_telegram_event, ev)
         for ev in ['telegram_command', 'telegram_text', 'telegram_callback']]

        # Alarm mode controller
        self.listen_state(self.alarm_mode_controller,
                          entity='input_select.alarm_mode')
        self.listen_state(self.alarm_mode_controller_master_switch,
                          entity='switch.switch_master_alarm')
        self._alarm_state = self.get_state('switch.switch_master_alarm') == 'on'

        # Device Tracking:
        _devs_track = self.get_state('group.family', attribute='attributes'
                                     )['entity_id']
        self._tracking_state = {
            dev: [self.get_state(dev),
                  self.get_state(dev, attribute='last_changed')]
            for dev in _devs_track}
        [self.listen_state(self.track_zone_ch, dev, old="home", duration=60)
         for dev in self._tracking_state.keys()]
        [self.listen_state(self.track_zone_ch, dev, new="home", duration=5)
         for dev in self._tracking_state.keys()]
        self.log("**TRACKING STATE: {} -> {}"
                 .format(_devs_track, self._tracking_state))

        # Entities & friendly names:
        self._hass_entities = {
            ent_type: {k.split('.')[1]: v['attributes']['friendly_name']
                       for k, v in self.get_state(ent_type).items()}
            for ent_type in HASSWIZ_TYPES}

        # Start showing menu:
        self._notify_bot_menu(self._bot_chatids[0])

    def _notify_bot_menu(self, user_id):
        self.call_service(self._bot_notifier, target=user_id,
                          message='_Say something to me_, *my master*',
                          data=dict(inline_keyboard=TELEGRAM_INLINE_KEYBOARD,
                                    disable_notification=False))
        return True

    def _ssh_command_output(self, user, host, command, timeout=10):
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(host, username=user, key_filename=PATH_SSH_KEY)
        _, stdout, stderr = ssh.exec_command(command, timeout=timeout)
        out = stdout.read().decode()[:-1]
        if not out:
            out = stderr.read().decode()[:-1]
            self.log('SSH ERROR: {}'.format(out))
            return False, RG_COLOR.sub('', out)
        return True, RG_COLOR.sub('', out)

    def _shell_command_output(self, cmd, timeout=10, **kwargs):
        popenargs = cmd.split() if ' ' in cmd else cmd
        try:
            out = subprocess.check_output(popenargs, timeout=timeout,
                                          stderr=subprocess.STDOUT,
                                          **kwargs).decode()
            return True, RG_COLOR.sub('', out)
        except subprocess.CalledProcessError as e:
            self.log('CalledProcessError with {} -> {}, [{}]'
                     .format(cmd, e, e.__class__))
            return False, e.output.decode()
        except Exception as e:
            clean_e = str(e).replace('[', '(').replace(']', ')')
            msg = 'CHECK_OUTPUT ERROR: {} {}'.format(clean_e, e.__class__)
            return False, msg

    def _gen_hass_cam_pics(self, cam_entity_id):
        """curl -s
        -o /home/homeassistant/.homeassistant/www/snapshot_cameras/{file}.jpg
        -H "x-ha-access: {hass_pw}" {base_url}/api/camera_proxy/{cam_name}
        """
        file = cam_entity_id.split('.')[1].replace('_', '') + '.jpg'
        img_url = '{}/api/camera_proxy/{}'.format(self._config['base_url'],
                                                  cam_entity_id)
        cmd = CMD_MAKE_HASS_PIC.format(hass_pw=self._config['ha_key'],
                                       img_url=img_url, cam_filename=file)
        ok, _ = self._shell_command_output(cmd, timeout=5)
        self.log('HASS CAM PIC {} -> {}:{}'.format(cam_entity_id, file, ok))
        static_url = '{}/local/snapshot_cameras/{}'.format(
            self._config['base_url'], file)
        return static_url

    def _exec_bot_shell_command(self, command, args, timeout=20, **kwargs):
        self.log('in shell_command_output with "{}", "{}"'
                 .format(command, args), 'DEBUG')
        if command == '/tvshowscron':
            user, host = 'osmc', 'rpi3osmc'
            cmd = SSH_PYTHON_ENVS_PREFIX[host].format(user)
            cmd += "python /home/osmc/PYTHON/cronify"
            return self._ssh_command_output(user, host, cmd, timeout=timeout)
        elif command == '/tvshowsnext':
            user, host = 'osmc', 'rpi3osmc'
            cmd = SSH_PYTHON_ENVS_PREFIX[host].format(user)
            cmd += "python /home/osmc/PYTHON/tvshows --next"
            return self._ssh_command_output(user, host, cmd, timeout=40)
        elif command == '/tvshowsinfo':
            user, host = 'osmc', 'rpi3osmc'
            cmd = SSH_PYTHON_ENVS_PREFIX[host].format(user)
            cmd += "python /home/osmc/PYTHON/tvshows -i " + args
            return self._ssh_command_output(user, host, cmd, timeout=600)
        elif command == '/tvshowsdd':
            user, host = 'osmc', 'rpi3osmc'
            cmd = SSH_PYTHON_ENVS_PREFIX[host].format(user)
            cmd += "python /home/osmc/PYTHON/tvshows -dd " + args
            return self._ssh_command_output(user, host, cmd, timeout=600)
        elif command == '/osmc':
            user, host = 'osmc', 'rpi3osmc'
            if args.startswith('python'):
                args = SSH_PYTHON_ENVS_PREFIX[host].format(user) + args[6:]
            return self._ssh_command_output(user, host, args, timeout=timeout)
        elif command == '/osmcmail':
            user, host = 'osmc', 'rpi3osmc'
            cmd = 'tail -n 100 /var/mail/osmc'
            return self._ssh_command_output(user, host, cmd, timeout=timeout)
        elif command == '/rpi2':
            user, host = 'pi', 'rpi2'
            if args.startswith('python'):
                args = SSH_PYTHON_ENVS_PREFIX[host].format(user) + args[6:]
            return self._ssh_command_output(user, host, args, timeout=timeout)
        elif command == '/rpi2h':
            user, host = 'pi', 'rpi2h'
            if args.startswith('python'):
                args = SSH_PYTHON_ENVS_PREFIX[host].format(user) + args[6:]
            return self._ssh_command_output(user, host, args, timeout=timeout)
        elif command == '/rpi':
            user, host = 'pi', 'rpi'
            if args.startswith('python'):
                args = SSH_PYTHON_ENVS_PREFIX[host].format(user) + args[6:]
            return self._ssh_command_output(user, host, args, timeout=timeout)
        elif command == '/pitemps':
            cmd = 'python3 /home/pi/pitemps.py'
            return self._shell_command_output(cmd, timeout=timeout, **kwargs)
        elif command == '/cathass':
            cmd = 'tail -n 100 ' \
                  '/home/homeassistant/.homeassistant/home-assistant.log'
            return self._shell_command_output(cmd, timeout=timeout, **kwargs)
        elif command == '/catappd':
            cmd = 'tail -n 100 /home/homeassistant/appdaemon.log'
            return self._shell_command_output(cmd, timeout=timeout, **kwargs)
        elif command == '/catappderr':
            cmd = 'tail -n 100 /home/homeassistant/appdaemon_err.log'
            return self._shell_command_output(cmd, timeout=timeout, **kwargs)
        else:  # shell cmd
            return self._shell_command_output(args, timeout=timeout, **kwargs)

    def _bot_hass_command(self, command, cmd_args, user_id):
        # TODO + comandos, fuzzy logic con cmd + args, etc...
        prefix = 'WTF CMD {}'.format(command)
        msg = {'message': "ERROR {} - {}".format(command, cmd_args),
               "target": user_id}
        if command == '/hasswiz':  # HASS wizard:
            msg = dict(title='*HASS Wizard*',
                       message=HASSWIZ_STEPS[0]['question'],
                       target=user_id,
                       data=dict(inline_keyboard=HASSWIZ_STEPS[0]['options']))
            prefix = 'START HASS WIZARD'
        elif command == '/help':
            # Welcome message & keyboards:
            prefix = 'SHOW BOT HELP'
            msg = dict(target=user_id, message=TELEGRAM_BOT_HELP,
                       data=dict(inline_keyboard=TELEGRAM_INLINE_KEYBOARD,
                                 disable_notification=False))
        elif (command == '/init') or (command == '/start'):
            # Welcome message & keyboards:
            prefix = 'BOT START'
            msg = dict(target=user_id,
                       message='_Say something to me_, *my master*',
                       data=dict(inline_keyboard=TELEGRAM_INLINE_KEYBOARD,
                                 disable_notification=False))
        elif command == '/status':
            # multiple messaging:
            msg = dict(title=CMD_STATUS_TITLE, message=CMD_STATUS_TEMPL_SALON,
                       target=user_id,
                       data=dict(keyboard=TELEGRAM_KEYBOARD,
                                 disable_notification=True))
            self.call_service(self._bot_notifier, **msg)
            msg.pop('title')
            msg['data'].pop('keyboard')
            msg['message'] = CMD_STATUS_TEMPL_ESTUDIO
            self.call_service(self._bot_notifier, **msg)
            msg['message'] = CMD_STATUS_TEMPL_DORM
            self.call_service(self._bot_notifier, **msg)
            msg['message'] = CMD_STATUS_TEMPL_GALERIA
            self.call_service(self._bot_notifier, **msg)
            msg['message'] = CMD_STATUS_TEMPL_HEATER
            self.call_service(self._bot_notifier, **msg)
            msg['message'] = CMD_STATUS_TEMPL_RESTO
            self.call_service(self._bot_notifier, **msg)
            msg['message'] = CMD_STATUS_TEMPL_ESP32
            self.call_service(self._bot_notifier, **msg)
            msg['message'] = CMD_STATUS_TEMPL_ENERPI
            msg['data'] = dict(inline_keyboard=TELEGRAM_INLINE_KEYBOARD,
                               disable_notification=False)
            # self.call_service(self._bot_notifier, **msg)
            prefix = 'SHOW HASS STATUS'
        elif command == '/hastatus':
            msg = dict(message=CMD_TEMPL_HASS_STATUS,
                       target=user_id,
                       data=dict(inline_keyboard=TELEGRAM_INLINE_KEYBOARD,
                                 disable_notification=False))
            prefix = 'SHOW HASS PROCESS STATUS'
        elif command == '/html':
            msg = dict(data=dict(parse_mode='html', keyboard=TELEGRAM_KEYBOARD),
                       message=cmd_args, target=user_id)
            prefix = 'HTML RENDER'
        elif command == '/template':
            msg = dict(message=cmd_args, target=user_id,
                       data=dict(keyboard=TELEGRAM_KEYBOARD))
            prefix = 'TEMPLATE RENDER'
        elif command == '/getcams':
            photos = [{'file': '/home/homeassistant/picamera/image.jpg',
                       'caption': 'PiCamera Salón'}]
            for ent, cap in zip(['escam_qf001', 'picamera_estudio'],
                                ['ESCAM QF001 Salón', 'PiCamera Estudio']):
                cam = 'camera.{}'.format(ent)
                static_url = self._gen_hass_cam_pics(cam)
                photos.append({'url': static_url, 'caption': cap})
            if len(photos) > 1:
                first = photos[:-1]
                photos = [photos[-1]]
                msg = {'message': "HASS CAMERAS", "target": user_id,
                       'data': {'photo': first,
                                'keyboard': TELEGRAM_KEYBOARD}}
                self.call_service(self._bot_notifier, **msg)
            msg = {'message': "HASS CAMERAS", "target": user_id,
                   'data': {'photo': photos,
                            'inline_keyboard': TELEGRAM_INLINE_KEYBOARD}}
            prefix = 'SEND CAMERA PICS'
        elif command == '/enerpitiles':
            photos = []
            for ent, cap in zip(ENERPI_TILES, ENERPI_TILES_DESC):
                cam = 'camera.{}'.format(ent)
                static_url = self._gen_hass_cam_pics(cam)
                photos.append({'url': static_url, 'caption': cap})
            if len(photos) > 1:
                first = photos[:-1]
                photos = [photos[-1]]
                msg = {'message': "ENERPI CAMERAS", "target": user_id,
                       'data': {'photo': first,
                                'keyboard': TELEGRAM_KEYBOARD_ENERPI}}
                self.call_service(self._bot_notifier, **msg)
            msg = {'message': "ENERPI CAMERAS", "target": user_id,
                   'data': {'photo': photos,
                            'inline_keyboard': TELEGRAM_INLINE_KEYBOARD_ENERPI}}
            prefix = 'SEND ENERPI TILES'
        elif command == '/enerpikwh':
            cam, cap = 'camera.enerpi_tile_kwh', 'Consumo en kWh y € (24h)'
            static_url = self._gen_hass_cam_pics(cam)
            photos = [{'url': static_url, 'caption': cap}]
            msg = {'message': "ENERPI CAMERA", "target": user_id,
                   'data': {'photo': photos,
                            'inline_keyboard': TELEGRAM_INLINE_KEYBOARD_ENERPI}}
            prefix = 'SEND ENERPI TILE KWH'
        elif command == '/enerpipower':
            cam, cap = 'camera.enerpi_tile_power', 'Potencia eléctrica, W (24h)'
            static_url = self._gen_hass_cam_pics(cam)
            photos = [{'url': static_url, 'caption': cap}]
            msg = {'message': "ENERPI CAMERA", "target": user_id,
                   'data': {'photo': photos,
                            'inline_keyboard': TELEGRAM_INLINE_KEYBOARD_ENERPI}}
            prefix = 'SEND ENERPI TILE POWER'
        elif command == '/enerpi':
            cam, cap = 'camera.enerpi_tile_power', 'Potencia eléctrica, W (24h)'
            static_url = self._gen_hass_cam_pics(cam)
            message = '{}\n\n{}\n'.format(CMD_STATUS_TEMPL_ENERPI,
                                          static_url.replace('_', '\_'))
            msg = {'title': "*Power status*:", 'message': message,
                   "target": user_id,
                   'data': {'inline_keyboard': TELEGRAM_INLINE_KEYBOARD_ENERPI}}
            prefix = 'ENERPI INFO'
        return prefix, msg

    # noinspection PyUnusedLocal
    def alarm_mode_controller(self, entity, attribute, old, new, kwargs):
        """Cambia el master switch cuando se utiliza el input_select"""
        self.log('ALARM_MODE_CONTROLLER {} -> {}'.format(old, new))
        if new == 'Desconectada':
            self._alarm_state = False
            self.turn_off("switch.switch_master_alarm")
        elif new == 'Fuera de casa':  # and (old == 'Desconectada'):
            self._alarm_state = True
            self.turn_on("switch.switch_master_alarm")
        # TODO modo vigilancia "en casa" / "fuera", "vacaciones"

    # noinspection PyUnusedLocal
    def alarm_mode_controller_master_switch(self, entity, attribute,
                                            old, new, kwargs):
        """Cambia el input_select cuando se utiliza el master switch"""
        self.log('ALARM_MODE_CONTROLLER_MASTER_SWITCH {} -> {}'
                 .format(old, new))
        selected_mode = self.get_state('input_select.alarm_mode')
        if new == 'on':
            self._alarm_state = True
            if selected_mode == 'Desconectada':
                self.select_option("input_select.alarm_mode",
                                   option="Fuera de casa")
        elif new == 'off':
            self._alarm_state = False
            if selected_mode != 'Desconectada':
                self.select_option("input_select.alarm_mode",
                                   option="Desconectada")

    def _alguien_mas_en_casa(self, entity_exclude='no_excluir_nada'):
        res = any([x[0] == 'home' for k, x in self._tracking_state.items()
                   if k != entity_exclude])
        if self._alarm_state:
            self.log('alguien_mas_en_casa? -> {}. De {}, excl={}'
                     .format(res, self._tracking_state, entity_exclude))
        return res

    # noinspection PyUnusedLocal
    def track_zone_ch(self, entity, attribute, old, new, kwargs):
        last_st, last_ch = self._tracking_state[entity]
        self._tracking_state[entity] = [new, self.datetime()]
        clean_ent = entity.lstrip('device_tracker.')
        if last_st != old:
            self.log('TRACKING_STATE_CHANGE "{}" from "{}" [!="{}"'
                     ', changed at {}] to "{}"'
                     .format(clean_ent, old, last_st, last_ch, new))
        else:
            self.log('TRACKING_STATE_CHANGE "{}" from "{}" [{}] to "{}"'
                     .format(clean_ent, old, last_ch, new))
            if (new == 'home') and not self._alguien_mas_en_casa():
                # Llegada a casa:
                # if self._alarm_state:
                data_msg = {"title": "Bienvenido a casa",
                            "message": "¿Qué puedo hacer por ti?",
                            "data": {"push": {"badge": 0,
                                              "category": "INHOME"}}}
                self.log('INHOME NOTIF: {}'.format(data_msg))
                self.call_service(self._notifier, **data_msg)
            elif ((old == 'home') and not self._alguien_mas_en_casa()
                  and not self._alarm_state):
                # Salida de casa:
                data_msg = {"title": "Vuelve pronto!",
                            "message": "¿Apagamos luces o encendemos alarma?",
                            "data": {"push": {"badge": 0, "category": "AWAY"}}}
                self.log('AWAY NOTIF: {}'.format(data_msg))
                self.call_service(self._notifier, **data_msg)

    def light_flash(self, xy_color, persistence=5, n_flashes=3):
        """Flash hue lights as visual notification."""

        def _turn_on(*args_runin):
            self.call_service('light/turn_on', **args_runin[0])

        def _turn_off(*args_runin):
            self.call_service('light/turn_off', **args_runin[0])

        # noinspection PyUnusedLocal
        def _restore_state(*args):
            for light, st, attrs in zip(self._lights_notif.split(','),
                                        self._lights_notif_state,
                                        self._lights_notif_st_attr):
                if st == 'on':
                    self.call_service('light/turn_on', entity_id=light,
                                      transition=1, xy_color=attrs['xy_color'],
                                      brightness=attrs['brightness'])
                else:
                    self.call_service('light/turn_off', entity_id=light,
                                      transition=1)

        # Get prev state:
        self._lights_notif_state = [self.get_state(l)
                                    for l in self._lights_notif.split(',')]
        self._lights_notif_st_attr = [self.get_state(l, 'attributes')
                                      for l in self._lights_notif.split(',')]
        self.log('Flashing "{}" {} times, persistence={}s.'
                 .format(self._lights_notif, n_flashes, persistence))

        # Loop ON-OFF
        self.call_service('light/turn_off', entity_id=self._lights_notif,
                          transition=0)
        self.call_service('light/turn_on', entity_id=self._lights_notif,
                          transition=1, xy_color=xy_color, brightness=254)
        run_in = 2
        for i in range(1, n_flashes):
            self.run_in(_turn_off, run_in, entity_id=self._lights_notif,
                        transition=1)
            self.run_in(_turn_on, run_in + 2, entity_id=self._lights_notif,
                        xy_color=xy_color, transition=1, brightness=254)
            run_in += 4

        # Restore state
        self.run_in(_restore_state, run_in + persistence - 2,
                    entity_id=self._lights_notif, transition=1)

    def receive_ios_event(self, event_id, payload_event, *args):
        """Event listener."""
        if 'notification_action_fired' in event_id:
            action_name = payload_event['actionName']
            if action_name == 'com.apple.UNNotificationDefaultActionIdentifier':
                # iOS Notification discard
                self.log('NOTIFICATION Discard: {} - Args={}, more={}'
                         .format(event_id, payload_event, args))
            else:
                dev = payload_event['sourceDeviceName']
                self.log('RESPONSE_TO_ACTION "{}" from dev="{}", otherArgs ={}'
                         .format(action_name, dev, payload_event))
                self.response_to_action(action_name, dev, *args)
        else:
            self.log('NOTIFICATION WTF: "{}", payload={}, otherArgs={}'
                     .format(event_id, payload_event, args))

    def process_telegram_command(self, command, cmd_args,
                                 user_id, callback_id=None):
        tic = time()
        if callback_id is not None:
            msg = dict(data=dict(callback_query=dict(
                callback_query_id=callback_id, show_alert=False)),
                target=user_id)
        else:
            msg = dict(target=user_id)
        if command in TELEGRAM_IOS_COMMANDS:  # Same as iOS notification:
            msg["message"] = 'Exec: *{}* action'.format(command)
            if callback_id is not None:
                msg['message'] = msg['message'].replace('*', '')
            self.call_service(self._bot_notifier, **msg)
            self.log('TELEGRAM_COMMAND exec: {}'.format(command))
            self.response_to_action(TELEGRAM_IOS_COMMANDS[command],
                                    self._bot_users[user_id],
                                    telegram_target=(user_id, callback_id))
        elif command in TELEGRAM_SHELL_CMDS:
            msg["message"] = '_Running shell cmd_: {}'.format(command)
            if callback_id is not None:
                msg['message'] = msg['message'].replace('_', '')
            self.call_service(self._bot_notifier, **msg)
            ok, out = self._exec_bot_shell_command(command, cmd_args)
            if len(out) > 4000:
                out = out[-4000:]
            self.log('SHELL CMD TOOK {:.3f}s'.format(time() - tic))
            title = '*SHELL CMD OK*\n' if ok else '*SHELL CMD ERROR!*:\n'
            message = "```\n{}\n```".format(out.replace('```', ''))
            self.call_service(self._bot_notifier, title=title, target=user_id,
                              message=message)
        elif command in TELEGRAM_HASS_CMDS:
            msg["message"] = '_Running_: {}'.format(command)
            if callback_id is not None:
                msg['message'] = msg['message'].replace('_', '')
                self.log('DEBUG: USING CALLBACK {} w/msg={}'
                         .format(callback_id, msg['message']))
            self.call_service(self._bot_notifier, **msg)
            prefix, msg = self._bot_hass_command(command, cmd_args, user_id)
            self.log('{} TOOK {:.3f}s'.format(prefix, time() - tic))
            self.call_service(self._bot_notifier, **msg)
        else:
            rand_msg_mask = TELEGRAM_UNKNOWN[randrange(len(TELEGRAM_UNKNOWN))]
            p_cmd = '{}({})'.format(command, cmd_args)
            self.log('NOT IMPLEMENTED: ' + rand_msg_mask.format(p_cmd))
            self.call_service(self._bot_notifier, target=user_id,
                              data=dict(keyboard=TELEGRAM_KEYBOARD),
                              message=rand_msg_mask.format(
                                  '{}({})'.format(command, cmd_args)))

    def process_telegram_wizard(self, msg_origin, data_callback,
                                user_id, callback_id):
        # Wizard evolution:
        option = data_callback[len(COMMAND_WIZARD_OPTION):]
        data_msg = dict(callback_query=dict(callback_query_id=callback_id))
        if option == 'reset':
            self._bot_wizstack[user_id] = []
            self.log('HASSWIZ RESET')
            self.call_service(self._bot_notifier, data=data_msg,
                              target=user_id,
                              message="Reset wizard, start again")
        elif option == 'back':
            self._bot_wizstack[user_id] = self._bot_wizstack[user_id][:-1]
            message = "Back to: {}".format(self._bot_wizstack[user_id])
            self.log('HASSWIZ BACK --> {}'.format(self._bot_wizstack[user_id]))
            self.call_service(self._bot_notifier, data=data_msg,
                              target=user_id, message=message)
        elif option == 'exit':
            self._bot_wizstack[user_id] = []
            self.log('HASSWIZ EXIT')
            self.call_service(self._bot_notifier, data=data_msg,
                              target=user_id, message="Bye bye...")
            return self._notify_bot_menu(user_id)
        else:
            self._bot_wizstack[user_id].append(option)
            if len(self._bot_wizstack[user_id]) == len(HASSWIZ_STEPS):
                # Try to exec command:
                service, operation, entity_id = self._bot_wizstack[user_id]
                self._bot_wizstack[user_id].pop()
                entity = '{}.{}'.format(service, entity_id)
                # CALLING SERVICE / GET STATES
                if (service in ['switch', 'light', 'input_boolean']) and (operation in ['turn_on', 'turn_off']):
                    message = "Service called: {}/{}/{}"
                    message = message.format(_clean(service), _clean(operation), _clean(entity_id))
                    self.log('HASSWIZ: CALLING SERVICE "{}". Stack: {}'
                             .format(message, self._bot_wizstack[user_id]))
                    self.call_service('{}/{}'.format(service, operation),
                                      entity_id=entity)
                    self.call_service(self._bot_notifier, data=data_msg,
                                      target=user_id, message=message)
                elif operation in ['state', 'attributes']:
                    if operation == 'state':
                        data = self.get_state(entity)
                    else:
                        data = self.get_state(entity, attribute='attributes')
                    self.log('HASSWIZ STATE DATA -> {}/{}/{} -> {}'
                             .format(service, operation, entity_id, data))
                    message = "*{} {}*:\n--> {}".format(_clean(entity_id), _clean(operation), _clean(str(data)))
                    self.call_service(self._bot_notifier,
                                      target=user_id, message=message)
                else:
                    comb_err = '{}/{}/{}'.format(service, operation, entity_id)
                    self.log('ERROR: COMBINATION NOT IMPLEMENTED -> {}'
                             .format(comb_err), 'warning')
                    self.call_service(self._bot_notifier, data=data_msg,
                                      target=user_id,
                                      message='Combination *not implemented* -> ' + _clean(comb_err))
                    return False
                return True
            else:
                # Notificación de respuesta:
                self.log('OPTION SELECTED: "{}"'.format(option))
                self.call_service(self._bot_notifier, data=data_msg,
                                  target=user_id,
                                  message="Option selected: {}".format(option))
        # Show next wizard step
        try:
            wiz_step = HASSWIZ_STEPS[len(self._bot_wizstack[user_id])]
        except IndexError:
            self.log('HASS WIZ INDEX ERROR: stack={}, max={}. Reseting stack'
                     .format(len(self._bot_wizstack[user_id]),
                             len(HASSWIZ_STEPS)))
            self._bot_wizstack[user_id] = []
            wiz_step = HASSWIZ_STEPS[0]
        wiz_step_text = wiz_step['question']
        if ('{}' in wiz_step_text) and self._bot_wizstack[user_id]:
            wiz_step_text = wiz_step_text.format(
                '/'.join(self._bot_wizstack[user_id]))

        wiz_step_inline_kb = wiz_step['options']
        if wiz_step_inline_kb is None:
            # Get options from HASS, filtering with stack opts
            d_entities_options = self._hass_entities[
                self._bot_wizstack[user_id][0]]
            wiz_step_inline_kb = []
            wiz_step_inline_kb_row = []
            for i, (key, fn) in enumerate(d_entities_options.items()):
                btn = (fn, '{}{}'.format(COMMAND_WIZARD_OPTION, key))
                wiz_step_inline_kb_row.append(btn)
                if i % 3 == 2:
                    wiz_step_inline_kb.append(wiz_step_inline_kb_row)
                    wiz_step_inline_kb_row = []
            if wiz_step_inline_kb_row:
                wiz_step_inline_kb.append(wiz_step_inline_kb_row)
            wiz_step_inline_kb.append(HASSWIZ_MENU_ACTIONS)

        msg_id = msg_origin['message_id']
        # # Edición de teclado -> no necesaria
        # self.call_service(self._bot_notifier, message=wiz_step_text,
        #                   target=user_id,
        #                   data=dict(edit_replymarkup=dict(message_id=msg_id),
        #                             inline_keyboard=wiz_step_inline_kb))
        # Edición de mensaje y de teclado:
        self.call_service(self._bot_notifier, message=wiz_step_text,
                          target=user_id,
                          data=dict(edit_message=dict(message_id=msg_id),
                                    inline_keyboard=wiz_step_inline_kb))
        return True

    # noinspection PyUnusedLocal
    def receive_telegram_event(self, event_id, payload_event, *args):
        """Event listener for Telegram events."""
        self.log('TELEGRAM NOTIFICATION: "{}", payload={}'
                 .format(event_id, payload_event))
        user_id = payload_event['user_id']
        if event_id == 'telegram_command':
            command = payload_event['command']
            cmd_args = payload_event['args'] or ''
            self.process_telegram_command(command, cmd_args, user_id)
        elif event_id == 'telegram_text':
            text = payload_event['text']
            msg = 'TEXT RECEIVED: ```\n{}\n```'.format(text)
            self.log('TELEGRAM TEXT: ' + text)
            self.call_service(self._bot_notifier, target=user_id, message=msg)
        else:
            assert event_id == 'telegram_callback'
            msg_origin = payload_event['message']
            data_callback = payload_event['data']
            callback_id = payload_event['id']
            callback_chat_instance = payload_event['chat_instance']

            # Tipo de pulsación (wizard vs simple command):
            if data_callback.startswith(COMMAND_PREFIX):  # exec simple command
                cmd = data_callback.split(' ')
                command, cmd_args = cmd[0], cmd[1:]
                self.log('CALLBACK REDIRECT TO COMMAND RESPONSE: '
                         'cmd="{}", args="{}", callback_id={}'
                         .format(command, cmd_args, callback_id))
                self.process_telegram_command(command, cmd_args, user_id,
                                              callback_id=callback_id)
            elif data_callback.startswith(COMMAND_WIZARD_OPTION):  # Wizard
                return self.process_telegram_wizard(msg_origin, data_callback,
                                                    user_id, callback_id)
            else:  # WTF?
                rand_msg_mask = TELEGRAM_UNKNOWN[
                    randrange(len(TELEGRAM_UNKNOWN))]
                self.log('CALLBACK RESPONSE NOT IMPLEMENTED: '
                         + rand_msg_mask.format(data_callback))
                self.call_service(self._bot_notifier, target=user_id,
                                  data=dict(keyboard=TELEGRAM_KEYBOARD),
                                  message=rand_msg_mask.format(data_callback))

    def frontend_notif(self, action_name, msg_origin, mask=DEFAULT_NOTIF_MASK,
                       title=None, raw_data=None):
        """Set a persistent_notification in frontend."""
        if raw_data is not None:
            message = mask.format(dt.datetime.now(tz=conf.tz),
                                  msg_origin, raw_data)
        else:
            message = mask.format(dt.datetime.now(tz=conf.tz), msg_origin)
        title = action_name if title is None else title
        self.persistent_notification(message, title=title, id=action_name)

    def _turn_off_lights_and_appliances(self, turn_off_heater=False):
        self.turn_off('group.all_lights', transition=2)
        self.turn_off("switch.calefactor")
        self.turn_off("switch.cocina")
        self.turn_off("switch.altavoz")
        self.turn_off("switch.kodi_tv_salon")
        if turn_off_heater:
            self.turn_off("switch.caldera")

    def response_to_action(self, action, origin, telegram_target=None):
        """Respond to defined action events."""
        if telegram_target is None:
            action_msg_log = '*iOS Action "{}" received. '.format(action)
        else:
            action_msg_log = '*Action {}* received: '.format(action)
        # AWAY category
        if action == 'ALARM_ARM_NOW':  # Activar alarma
            self.frontend_notif(action, origin, mask=NOTIF_MASK_ALARM_ON,
                                title='Activación remota de alarma')
            self._turn_off_lights_and_appliances()
            self.select_option("input_select.alarm_mode",
                               option="Fuera de casa")
            action_msg_log += 'ALARM ON, MODE "Fuera de casa"'
        elif action == 'ALARM_HOME':  # Activar vigilancia
            self.frontend_notif(action, origin, mask=NOTIF_MASK_ALARM_HOME,
                                title='Activación remota de vigilancia')
            self._turn_off_lights_and_appliances()
            self.select_option("input_select.alarm_mode", option="En casa")
            action_msg_log += 'ALARM MODE "En casa"'
        elif action == 'LIGHTS_OFF':  # Apagar luces
            self._turn_off_lights_and_appliances()
            self.frontend_notif(action, origin, mask=NOTIF_MASK_LIGHTS_OFF,
                                title='Apagado de luces')
            action_msg_log += 'APAGANDO LUCES'

        # INHOME category
        elif action == 'WELCOME_HOME':  # Alarm OFF, lights ON
            self.select_option("input_select.alarm_mode", option="Desconectada")
            self.turn_on("switch.cocina")
            self.call_service('light/hue_activate_scene',
                              group_name="Salón", scene_name='Semáforo')
            self.frontend_notif(action, origin, mask=NOTIF_MASK_ALARM_OFF,
                                title='Llegando a casa, luces ON')
            action_msg_log += 'ALARM OFF. Kitchen ON, "Semáforo"("Salón")'
            self.light_flash(XY_COLORS['green'], persistence=2, n_flashes=2)
        elif action == 'WELCOME_HOME_TV':  # Alarm OFF, lights ON
            self.select_option("input_select.alarm_mode", option="Desconectada")
            self.turn_on("switch.kodi_tv_salon")
            self.call_service('light/hue_activate_scene',
                              group_name="Salón", scene_name='Aurora boreal')
            self.frontend_notif(action, origin, mask=NOTIF_MASK_ALARM_OFF,
                                title='Llegando a casa, tele ON')
            action_msg_log += 'ALARM OFF. TV ON, "Aurora boreal"("Salón")'
            self.light_flash(XY_COLORS['green'], persistence=2, n_flashes=2)
        elif action == 'IGNORE_HOME':  # Reset del estado de alarma
            self.fire_event('reset_alarm_state')
            self.frontend_notif(action, origin,
                                mask=NOTIF_MASK_ALARM_RESET,
                                title='Ignorando presencia')
            action_msg_log += 'reset_alarm_state & alarm continues ON'

        elif action == 'ALARM_SILENT':  # Silenciar alarma (sólo la sirena)
            self.frontend_notif(action, origin,
                                mask=NOTIF_MASK_ALARM_SILENT,
                                title="Sirena OFF")
            self.fire_event('silent_alarm_state')
            action_msg_log += 'SIRENA OFF'
        elif action == 'ALARM_RESET':  # Ignorar armado y resetear
            self.fire_event('reset_alarm_state')
            self.frontend_notif(action, origin,
                                mask=NOTIF_MASK_ALARM_RESET,
                                title="Ignorando presencia")
            action_msg_log += 'reset_alarm_state & alarm continues ON'
        elif action == 'ALARM_CANCEL':  # Desconectar alarma
            self.frontend_notif(action, origin,
                                mask=NOTIF_MASK_ALARM_OFF,
                                title="Desconexión de Alarma")
            self.select_option("input_select.alarm_mode", option="Desconectada")
            action_msg_log += 'ALARM MODE OFF'
            self.light_flash(XY_COLORS['green'], persistence=2, n_flashes=5)

        # CONFIRM category
        elif action == 'CONFIRM_OK':  # Validar
            self.frontend_notif(action, origin,
                                mask=NOTIF_MASK_LAST_VALIDATION,
                                title="Validación")
            action_msg_log += 'Confirmation received'
            self.light_flash(XY_COLORS['yellow'], persistence=3, n_flashes=1)

        # CAMERA category
        elif action == 'CAM_YES':  # Validar
            self.frontend_notif(action, origin)
            action_msg_log += 'GREEN FLASHING'
            self.light_flash(XY_COLORS['green'], persistence=3, n_flashes=1)
        elif action == 'CAM_NO':  # Validar
            self.frontend_notif(action, origin)
            action_msg_log += 'RED FLASHING'
            self.light_flash(XY_COLORS['red'], persistence=3, n_flashes=1)

        # KODIPLAY category
        elif action == 'LIGHTS_ON':  # Lights ON!
            self.frontend_notif(action, origin,
                                mask=NOTIF_MASK_LIGHTS_ON, title="Lights ON!")
            self.call_service('input_slider/select_value',
                              entity_id="input_slider.light_main_slider_salon",
                              value=254)
            action_msg_log += 'LIGHTS ON: LIGHT MAIN SLIDER SALON 254'
        elif action == 'HYPERION_TOGGLE':  # Toggle Ambilight
            self.frontend_notif(action, origin,
                                mask=NOTIF_MASK_TOGGLE_AMB,
                                title="Toggle Ambilight")
            self.toggle("switch.toggle_kodi_ambilight")
            action_msg_log += 'TOGGLE KODI AMBILIGHT'
            self.light_flash(XY_COLORS['blue'], persistence=2, n_flashes=2)
        elif action == 'HYPERION_CHANGE':  # Change Ambilight conf
            self.frontend_notif(action, origin,
                                mask=NOTIF_MASK_TOGGLE_AMB_CONF,
                                title="Cambio de modo Ambilight")
            self.toggle("switch.toggle_config_kodi_ambilight")
            action_msg_log += 'CHANGE AMBILIGHT CONF'
            self.light_flash(XY_COLORS['violet'], persistence=2, n_flashes=2)

        # ALARMCLOCK category
        elif action == 'INIT_DAY':  # Luces Energy + Calefactor!
            self.frontend_notif(action, origin, mask=NOTIF_MASK_INIT_DAY)
            self.call_service('light/hue_activate_scene',
                              group_name="Dormitorio", scene_name='Energía')
            self.turn_on('switch.calefactor')
            action_msg_log += 'A NEW DAY STARTS WITH A WARM SHOWER'
        elif action == 'POSTPONE_ALARMCLOCK':  # Postponer despertador
            self.frontend_notif(action, origin,
                                mask=NOTIF_MASK_POSTPONE_ALARMCLOCK,
                                title="Posponer despertador")
            self.turn_off('input_boolean.manual_trigger_lacafetera')
            action_msg_log += 'Dormilón!'
            self.fire_event("postponer_despertador", jam="true")
        elif action == 'ALARMCLOCK_OFF':  # Luces Energy
            self.frontend_notif(action, origin,
                                mask=NOTIF_MASK_ALARMCLOCK_OFF,
                                title="Despertador apagado")
            self.turn_off('input_boolean.manual_trigger_lacafetera')
            action_msg_log += 'Apagado de alarma'

        # TODO replace/remove EXECORDER iOS category with textInput not working!
        elif action == 'INPUTORDER':  # Tell me ('textInput')
            self.frontend_notif(action, origin)
            action_msg_log += 'INPUT: {}'.format(origin)
            self.light_flash(XY_COLORS['blue'], persistence=3, n_flashes=1)
        # Unrecognized cat
        else:
            action_msg_log += 'WTF: origin={}'.format(origin)
            self.frontend_notif(action, origin)

        self.log(action_msg_log)
        # if telegram_target is not None:
        #     # edit the caption notification:
        #     # msg = dict(target=telegram_target[0],
        #     #            message='It is done, my master\n{}'.format(action_msg_log),
        #     #            data=dict(edit_caption=dict(caption='It is done OK: {}'.format(action_msg_log),
        #     #                                        inline_message_id=msg_origin['message_id'])))
        #     #
        #     # msg = dict(target=telegram_target[0],
        #     #            message='It is done, my master\n{}'.format(action_msg_log),
        #     #            data=dict(edit_caption=dict(caption='It is done OK: {}'.format(action_msg_log),
        #     #                                        inline_message_id=msg_origin['message_id'])))
        #
        #     self.call_service(self._bot_notifier, target=telegram_target[0],
        #                       message='It is done, my master\n{}'.format(action_msg_log),
        #                       data=dict(callback_query=dict(callback_query_id=telegram_target[1], show_alert=True)))

    # debug
    def _test_notification_actions(self):

        def _flash_color(args):
            self.light_flash(XY_COLORS[args['color']], persistence=3, n_flashes=1)

        # noinspection PyUnusedLocal
        def _push_category(args):
            category = args['category']
            data_msg = {"title": "Test {}".format(category),
                        "message": "{} test iOS notif->{}".format(category, self._notifier),
                        "data": {"push": {"badge": args['badge'],
                                          "category": category}}}
            self.log('TEST PUSH_CATEGORY {} --> {}'.format(category, data_msg))
            self.call_service(self._notifier, **data_msg)

        # noinspection PyUnusedLocal
        def _push_camera(*args):
            data_msg = {"title": "Test camera",
                        "message": "camera test iOS notif->{}".format(self._notifier),
                        "data": {"push": {"target": "28ab3a8f-3ff6-30cd-b93b-8bb854cbf483",
                                          "category": "camera",
                                          "hide-thumbnail": False},
                                 "entity_id": "camera.escam_qf001"}}  # "camera.picamera_salon"
            self.log('TEST PUSH_CAMERA --> {}'.format(data_msg))
            self.call_service(self._notifier, **data_msg)

        # self.run_in(_flash_color, 5, color='orange')
        self.run_in(_push_camera, 2)
        # self.run_in(_push_category, 25, category='KODIPLAY', badge=1)
        # self.run_in(_push_category, 50, category='ALARMSOUNDED', badge=2)
        # self.run_in(_push_category, 3, category='ALARMCLOCK', badge=3)
        # self.run_in(_push_category, 60, category='AWAY', badge=3)
        # self.run_in(_push_category, 120, category='INHOME', badge=3)
        # self.run_in(_push_category, 40, category='AWAY', badge=3)
        # self.run_in(_push_category, 60, category='INHOME', badge=3)
        # self.run_in(_push_category, 100, category='EXECORDER', badge=0)
