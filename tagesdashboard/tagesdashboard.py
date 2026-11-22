"""
Tagesdashboard – Wetter (DWD) und Nextcloud-Kalender auf einem Bild.

Das Plugin ist eigenständig. Im Unterordner lib/ liegen die Bausteine der
beiden Einzel-Plugins:
  lib/dwd_wetter.py, lib/dwd_icons.py   Wetterdaten, Symbole, Warnungen
  lib/nextcloud_kalender.py             CalDAV-Abruf, Serientermine
Die Einzel-Plugins müssen dafür nicht installiert sein.

Was das Dashboard selbst hinzufügt:
  * Fokus-Tag: tagsüber das Wetter von heute, abends (einstellbar) das von morgen
  * Tageskurve 6–24 Uhr mit "jetzt"-Linie
  * Kleidungsempfehlung für die Zeit, in der man unterwegs ist (aus den Terminen)
  * Regenwahrscheinlichkeit direkt an den Terminen
  * Live-Daten eines Pendelzuges in einem Zeitfenster (bahn.py)
  * morgens Schlagzeilen für Bonn, NRW und Bund (nachrichten.py)
  * abends: Wäsche vom Balkon holen? (waesche.py)
  * nachts ein ruhiges Nachtbild, sonntagabends eine Wochenvorschau (ansichten.py)
  * Anfahrt zu Terminen: Rad oder ÖPNV je nach Wetter, und wann man los muss (anfahrt.py)
  * Festtage: Gruß im Kopf und Festbild an Heiligabend und Silvester; Geburtstage (festtage.py)
  * Statusanzeige im Kopf, wenn eine Datenquelle ausfällt, nach ~2 h mit „seit …“ (status.py)
"""

import json
import logging
import sys
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import requests

from plugins.base_plugin.base_plugin import BasePlugin

logger = logging.getLogger(__name__)

try:
    from .lib import dwd_wetter as dwd
    from .lib import dwd_icons as icons
    from .lib import nextcloud_kalender as nc
    from .lib import eink
    from .lib import zeichensatz
    IMPORT_ERROR = None
except Exception as exc:  # Plugin soll InkyPi beim Start nicht blockieren
    logger.exception("Bausteine des Tagesdashboards konnten nicht geladen werden")
    dwd = icons = nc = eink = zeichensatz = None
    IMPORT_ERROR = exc

try:
    from . import (kleidung, bahn, nachrichten, waesche, ansichten, nachtgrafik, anfahrt, festtage, radar, luft,
                   katze, pollen, meteore, finsternisse, planeten, status, urlaub, wahlkampf, iss, ostereier, livestream,
                   pegel, pizustand, advent, zielort, laufen, glaette, polarlicht, nina, wochenlast, laufbilanz, monat)
except ImportError:  # pragma: no cover
    from plugins.tagesdashboard import (kleidung, bahn, nachrichten, waesche, ansichten, nachtgrafik, anfahrt,
                                        festtage, radar, luft, katze, pollen, meteore, finsternisse, planeten,
                                        status, urlaub, wahlkampf, iss, ostereier, livestream, pegel, pizustand, advent,
                                        zielort, laufen, glaette, polarlicht, nina, wochenlast,
                                        laufbilanz, monat)

# Wahlurne (Stimmzettel mit Kreuz steckt im Schlitz)
WAHL_ICON = ('<svg class="{cls}" viewBox="0 0 32 32" aria-hidden="true">'
             '<path d="M10 3 H22 V17 H10 Z" fill="#FFFFFF" stroke="#000" stroke-width="2.2"/>'
             '<path d="M13 6.5 l6 6 M19 6.5 l-6 6" stroke="#E3001B" stroke-width="2.4" stroke-linecap="round"/>'
             '<rect x="3.5" y="15" width="25" height="14" rx="2" fill="#E3001B" stroke="#000" stroke-width="2.2"/>'
             '<rect x="8" y="17.6" width="16" height="2.6" fill="#000"/></svg>')

# Läufer (Lauf-Fenster, seit 1.37) und Eiskristall (Glätte-Hinweis, seit 1.37), 48er-ViewBox wie die Karten-Icons
RUN_ICON = ('<svg class="{cls}" viewBox="0 0 48 48" aria-hidden="true">'
            '<circle cx="31" cy="7.5" r="4.6" fill="#000"/>'
            '<path d="M27.5 15 L21 28.5 M26 17.5 L33.5 22.5 L39 18.5 M26 17.5 L17.5 20 L13 26 '
            'M21 28.5 L29.5 33.5 L27 43 M21 28.5 L15 36.5 L7 36" fill="none" stroke="#000" stroke-width="3.8" '
            'stroke-linecap="round" stroke-linejoin="round"/><path d="M4 46 H44" stroke="#2E9E3F" stroke-width="3.2" '
            'stroke-linecap="round"/></svg>')
ICE_ICON = ('<svg class="{cls}" viewBox="0 0 48 48" aria-hidden="true"><g fill="none" stroke="#0082C9" stroke-width="3.6" '
            'stroke-linecap="round" stroke-linejoin="round"><path d="M24 4 V44 M6.7 14 L41.3 34 M6.7 34 L41.3 14"/>'
            '<path d="M18.5 7.5 L24 13 L29.5 7.5 M18.5 40.5 L24 35 L29.5 40.5 M5.5 21.5 L13 20 L10.5 12.5 '
            'M42.5 26.5 L35 28 L37.5 35.5 M5.5 26.5 L13 28 L10.5 35.5 M42.5 21.5 L35 20 L37.5 12.5"/></g></svg>')

# Sirene mit Blinklicht (Warnungen aus NINA, seit 1.38), 48er-ViewBox wie die Karten-Icons
NINA_ICON = ('<svg class="{cls}" viewBox="0 0 48 48" aria-hidden="true">'
             '<path d="M12 36 V26 A12 12 0 0 1 36 26 V36 Z" fill="#E3001B" stroke="#000" stroke-width="3" stroke-linejoin="round"/>'
             '<path d="M18.5 26 A5.5 5.5 0 0 1 24 20.5" fill="none" stroke="#FFFFFF" stroke-width="3" stroke-linecap="round"/>'
             '<rect x="7" y="36" width="34" height="7" rx="1.5" fill="#000"/>'
             '<path d="M24 3.5 V9 M8.5 9.5 L12.5 13.5 M39.5 9.5 L35.5 13.5 M2.5 24 H7.5 M40.5 24 H45.5" stroke="#000" '
             'stroke-width="3.4" stroke-linecap="round"/></svg>')

_HISTORY = {}  # Wochenlast: Termine der vergangenen Wochen, einmal am Tag abgefragt (seit 1.38)

WOCHENTAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
WOCHENTAGE_KURZ = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
          "August", "September", "Oktober", "November", "Dezember"]

DEFAULTS = {
    "sensitivity": "empfindlich",
    "switchHour": "20",
    "calendarDays": "7",
    "showAlerts": "true",
    "showWear": "true",
    "showGraph": "true",
    "rainOnEvents": "true",
    "useColors": "true",
    "showLocation": "true",
    "showPast": "false",
    "verifySSL": "true",
    "einkSnap": "true",
    # Zug (seit cfgVersion 2)
    "trainEnabled": "false",
    "trainStation": "Bonn Hbf",
    "trainLine": "RE 5",
    "trainTime": "08:04",
    "trainFrom": "06:30",
    "trainTo": "08:15",
    "trainMo": "false", "trainDi": "true", "trainMi": "false", "trainDo": "false",
    "trainFr": "false", "trainSa": "false", "trainSo": "false",
    "quietMinutes": "15",
    # Ausstieg und Störungsmonitor (seit cfgVersion 7)
    "trainTarget": "Düsseldorf Hbf",
    "trainAlerts": "true",
    "trainRoute": "true",       # Streckenmeldungen der VRR-Auskunft (seit cfgVersion 12)
    # Nachrichten (seit cfgVersion 3)
    "newsEnabled": "true",
    "newsFrom": "06:00", "newsTo": "09:30",
    "newsWeekendFrom": "08:00", "newsWeekendTo": "10:30",
    "newsBonnUrl": nachrichten.DEFAULT_FEEDS["bonn"][2],
    "newsBonnFilter": "/bonn/",
    "newsNrwUrl": nachrichten.DEFAULT_FEEDS["nrw"][2],
    "newsBundUrl": nachrichten.DEFAULT_FEEDS["bund"][2],
    # Frankreich (seit cfgVersion 10)
    "newsFrEnabled": "false",
    "newsFrUrl": nachrichten.DEFAULT_FEEDS["fr"][2],
    # Wäsche (seit cfgVersion 4)
    "laundryEnabled": "true",
    "laundryFrom": "17:00", "laundryTo": "23:00",
    "laundryCovered": "false",
    # Nachtbild und Wochenvorschau (seit cfgVersion 5)
    "nightEnabled": "true", "nightFrom": "23:00", "nightTo": "06:00", "nightFreeze": "true",
    "weekEnabled": "true", "weekFrom": "18:00", "weekTo": "23:00",
    # Bonner Silhouette im Nachtbild (seit cfgVersion 6)
    "nightArt": "true",
    # Anfahrt zu Terminen (seit cfgVersion 8)
    "tripEnabled": "false",
    "tripHome": "false",
    "tripBuffer": "5",
    "tripRainProb": "30",
    "tripMaxGap": "90",
    "tripLead": "120",
    "tripStart": "",
    "tripPlaces": "",
    "tripSkip": anfahrt.DEFAULT_SKIP,
    # Festtage und Geburtstage (seit cfgVersion 9)
    "festXmas": "true",
    "festNye": "true",
    "festBday": "true",
    "birthdays": "",
    # Regenradar (seit cfgVersion 10)
    "radarEnabled": "true",
    # Luftqualität (seit cfgVersion 11)
    "airEnabled": "true",
    "airLevel": "3",            # 3 = ab mäßig, 4 = ab schlecht
    "airRadius": "3",           # km um den Wetter-Ort
    "airGases": "false",        # Ozon und NO2 der Messstation mitbewerten
    "airStation": luft.DEFAULT_STATION,
    # Katze (seit cfgVersion 13)
    "catEnabled": "true",
    "catWeather": "true",       # Pose passt sich dem Wetter an
    "catNight": "true",         # schläft im Nachtbild auf dem Mond (seit cfgVersion 14)
    # Pollenflug (seit cfgVersion 15)
    "pollenEnabled": "true",
    "pollenLevel": "1",         # 1 = ab gering, 2 = ab mittel, 3 = ab hoch
    "pollenRegion": "",         # leer = Bonn (Teilregion 41, Rhein.-Westf. Tiefland)
    "pollenHasel": "true", "pollenErle": "true", "pollenEsche": "true", "pollenBirke": "true",
    "pollenGraeser": "true", "pollenRoggen": "true", "pollenBeifuss": "true", "pollenAmbrosia": "true",
    # Sternschnuppenströme im Nachtbild (seit cfgVersion 16)
    "meteorEnabled": "true",
    # Mondfinsternisse im Nachtbild (seit cfgVersion 17)
    "eclipseEnabled": "true",
    # Helle Planeten im Nachtbild (seit cfgVersion 18)
    "planetEnabled": "true",
    # Urlaubsbild, Wahlkampf-Modus, ISS-Überflug (seit cfgVersion 19)
    "urlaubEnabled": "true",
    "urlaubWords": urlaub.DEFAULT_KEYWORDS,
    "urlaubMinDays": str(urlaub.MIN_DAYS),
    "wahlEnabled": "true",
    "wahlArt": wahlkampf.DEFAULT_ART,   # landtag | bundestag | europa | kommunal
    "wahlTag": "",                       # leer: nur für die Landtagswahl NRW bekannt (25.04.2027)
    "wahlWords": wahlkampf.DEFAULT_WORDS,
    "issEnabled": "true",
    # Livestream-Karte während einer Ratssitzung (seit cfgVersion 20)
    "liveEnabled": "true",
    "liveWords": livestream.DEFAULT_WORDS,
    "liveUrl": livestream.DEFAULT_URL,
    # Rhein auf echtem Pegel im Nachtbild, Zustand des Pi in der Wochenvorschau (seit cfgVersion 21)
    "pegelEnabled": "true",
    "piEnabled": "true",
    # Freie Abende in der Wochenvorschau, Adventskranz im Kopf (seit cfgVersion 22)
    "freeEnabled": "true", "freeFrom": "18:00", "freeTo": "22:00",
    "adventEnabled": "true",
    # Wetter am Zielort: Zeile an auswärtigen Terminen (seit cfgVersion 23)
    "zielEnabled": "true",
    # Lauf-Fenster, Glätte-Hinweis, Polarlicht im Nachtbild (seit cfgVersion 24)
    "runEnabled": "true", "runMinutes": str(laufen.DAUER),
    "iceEnabled": "true",
    "polarEnabled": "true",
    # Warnungen aus NINA, Wochenlast, Laufbuch, Monatsbild (seit cfgVersion 25)
    "ninaEnabled": "true", "ninaArs": nina.DEFAULT_ARS,
    "loadEnabled": "true",
    "runLogEnabled": "true", "runFile": laufbilanz.DEFAULT_PATH,
    "monthEnabled": "true", "monthFrom": "06:00", "monthTo": "10:00",
}
# Ab welcher cfgVersion es einen Schlüssel gibt. Ist die gespeicherte Version älter, gilt für
# Checkboxen der Standardwert statt "fehlt = aus" (sonst wären neue Funktionen stumm aus).
SINCE_VERSION = {k: 2 for k in DEFAULTS if k.startswith("train") or k == "quietMinutes"}
SINCE_VERSION.update({k: 3 for k in DEFAULTS if k.startswith("news")})
SINCE_VERSION.update({k: 4 for k in DEFAULTS if k.startswith("laundry")})
SINCE_VERSION.update({k: 5 for k in DEFAULTS if k.startswith(("night", "week"))})
SINCE_VERSION["nightArt"] = 6
SINCE_VERSION.update({"trainTarget": 7, "trainAlerts": 7})
SINCE_VERSION.update({k: 8 for k in DEFAULTS if k.startswith("trip")})
SINCE_VERSION.update({k: 9 for k in DEFAULTS if k.startswith("fest")})
SINCE_VERSION.update({"radarEnabled": 10, "newsFrEnabled": 10, "newsFrUrl": 10})
SINCE_VERSION.update({k: 11 for k in DEFAULTS if k.startswith("air")})
SINCE_VERSION["trainRoute"] = 12
SINCE_VERSION.update({k: 13 for k in DEFAULTS if k.startswith("cat")})
SINCE_VERSION["catNight"] = 14
SINCE_VERSION.update({k: 15 for k in DEFAULTS if k.startswith("pollen")})
SINCE_VERSION["meteorEnabled"] = 16
SINCE_VERSION["eclipseEnabled"] = 17
SINCE_VERSION["planetEnabled"] = 18
SINCE_VERSION.update({"urlaubEnabled": 19, "wahlEnabled": 19, "issEnabled": 19})
SINCE_VERSION["liveEnabled"] = 20
SINCE_VERSION.update({"pegelEnabled": 21, "piEnabled": 21})
SINCE_VERSION.update({"freeEnabled": 22, "adventEnabled": 22})
SINCE_VERSION["zielEnabled"] = 23
SINCE_VERSION.update({"runEnabled": 24, "iceEnabled": 24, "polarEnabled": 24})
SINCE_VERSION.update({"ninaEnabled": 25, "loadEnabled": 25, "runLogEnabled": 25, "monthEnabled": 25})
CFG_VERSION = 25  # muss zu cfgVersion in settings.html passen (dev/test_settings.py prüft das)
WEEK_DAY = 6  # Wochenvorschau sonntags

# Das Nachtbild wird einmal gezeichnet und bis zum Ende der Nacht wiederverwendet
_NIGHT_CACHE = {}

# Außerhalb des Zug-Zeitfensters wird ein fertiges Bild wiederverwendet (siehe generate_image)
_IMAGE_CACHE = {}
EDGE_TOLERANCE = timedelta(minutes=1)


def cycle_seconds(device_config):
    """InkyPis Playlist-Takt in Sekunden (Einstellungen → Plugin Cycle Interval), sonst None."""
    try:
        value = int(device_config.get_config("plugin_cycle_interval_seconds", default=None))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def cache_fresh(now, quiet_until, edge, takt):
    """Darf das gemerkte Bild jetzt noch einmal ausgeliefert werden?

    edge: nächste Fenstergrenze (Nachrichten, Zug, Wäsche …). Ab da muss ein neues Bild her;
    1 Minute Toleranz, damit ein Aufruf knapp davor nicht bis zum nächsten Takt wartet.
    quiet_until: Ende von „Sonst alle … min“. InkyPi fragt nur im eigenen Takt; neu gezeichnet
    wird beim Aufruf, der am nächsten an quiet_until liegt (ab einem halben Takt davor). So wird
    aus 5-min-Takt + 15 min Ruhe alle 15 min, und ein Takt von 15 oder 20 min bleibt, wie er ist
    (der Fehler aus 1.3 – 15-min-Takt wurde zu 30 min – kann nicht wiederkommen).
    """
    if edge and now >= edge - EDGE_TOLERANCE:
        return False
    slack = max(EDGE_TOLERANCE, timedelta(seconds=takt / 2)) if takt else EDGE_TOLERANCE
    return now < quiet_until - slack
SENSITIVITY_LABEL = {"normal": "normal", "empfindlich": "kälteempfindlich", "sehr": "sehr kälteempfindlich"}
GRAPH_START, GRAPH_END = 6, 24  # Tageskurve von 6 bis 24 Uhr
UV_MIN_SHOWN = 3  # UV-Kachel erst ab „mittel“ (Sonnenschutz empfohlen), seit 1.36
# Regenstärke in mm pro Stunde. Bewusst alltagsnah gewählt; die offizielle DWD-Einteilung
# (leicht < 2,5, mäßig bis 10, stark > 10 mm/Std.) würde fast jeden Regen "leicht" nennen.
RAIN_LEVELS = [(1.0, "leicht"), (4.0, "maessig"), (float("inf"), "stark")]
RAIN_SCALE = 4.0  # mm/Std.: ab hier ist der Balken voll hoch (feste Skala, Tage bleiben vergleichbar)

# UV-Gefahrenindex des DWD: tägliche Höchstwerte für ausgewählte Orte (heute, morgen, übermorgen)
UVI_URL = "https://opendata.dwd.de/climate_environment/health/alerts/uvi.json"
# Stufen nach WHO/Bundesamt für Strahlenschutz: (bis einschließlich, Bezeichnung, Farbe, Schrift)
UV_STUFEN = [
    (2, "niedrig", "#2E9E3F", "#FFFFFF"),
    (5, "mittel", "#FFC400", "#000000"),
    (7, "hoch", "#FF8C00", "#000000"),
    (10, "sehr hoch", "#E3001B", "#FFFFFF"),
    (99, "extrem", "#8B0A50", "#FFFFFF"),
]
MIN_WEAR_HOURS = 4


def hm(dt):
    return f"{dt.hour}:{dt.minute:02d}"


class Tagesdashboard(BasePlugin):


    def generate_settings_template(self):
        params = super().generate_settings_template()
        params["style_settings"] = True
        params["api_key"] = {
            "required": True,
            "service": "Nextcloud (App-Passwort)",
            "expected_key": "NEXTCLOUD_APP_PASSWORD",
        }
        return params

    def current_time(self, tz):
        """Eigene Methode, damit Tests eine feste Uhrzeit einsetzen können."""
        return datetime.now(tz)

    def _opt(self, settings, key):
        if key in ("newsBonnFilter", "tripStart", "tripPlaces", "birthdays") and key in settings:  # leer ist erlaubt
            return settings[key]
        if "cfgVersion" in settings and DEFAULTS.get(key) in ("true", "false"):
            saved = int(settings["cfgVersion"]) if str(settings["cfgVersion"]).isdigit() else 1
            if saved < SINCE_VERSION.get(key, 1):
                return settings.get(key) or DEFAULTS[key]
            return settings.get(key, "false")
        return settings.get(key) or DEFAULTS[key]

    @staticmethod
    def _manual_refresh():
        """True, wenn InkyPi gerade „Jetzt aktualisieren“ ausführt (dann nie den Cache nutzen)."""
        frame = sys._getframe(1)
        for _ in range(25):
            if frame is None:
                return False
            obj = frame.f_locals.get("self")
            if obj is not None and type(obj).__name__ == "ManualRefresh":
                return True
            frame = frame.f_back
        return False

    # ==================================================================
    def generate_image(self, settings, device_config):
        if IMPORT_ERROR is not None:
            raise RuntimeError(f"Plugin unvollständig – Ordner lib/ fehlt oder ist beschädigt ({IMPORT_ERROR}).")
        flag = lambda k: self._opt(settings, k) == "true"  # noqa: E731

        tz_name = device_config.get_config("timezone", default="Europe/Berlin") or "Europe/Berlin"
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = ZoneInfo("Europe/Berlin")
        now = self.current_time(tz)
        today = now.date()

        dimensions = device_config.get_resolution()
        if device_config.get_config("orientation") == "vertical":
            dimensions = dimensions[::-1]

        # ---- Zug: nur im Zeitfenster; sonst Bild wiederverwenden ---------
        # Damit die Zugdaten aktuell sind, läuft das Dashboard im Zeitfenster z. B. alle 5 Minuten.
        # Außerhalb liefert es bis zu quietMinutes lang dasselbe Bild. InkyPi vergleicht die Bilder
        # und lässt das Display dann in Ruhe (kein Flackern, keine unnötigen Abrufe).
        opt = lambda k: self._opt(settings, k)  # noqa: E731
        train_cfg = bahn.read_config(opt, flag)
        train_now = bool(train_cfg) and bahn.in_window(now, train_cfg)
        news_cfg = nachrichten.read_config(opt, flag, bahn.parse_hhmm)
        news_now = bool(news_cfg) and nachrichten.in_window(now, news_cfg)
        laundry_win = None
        if flag("laundryEnabled"):
            lf, lt = bahn.parse_hhmm(opt("laundryFrom")), bahn.parse_hhmm(opt("laundryTo"))
            laundry_win = (lf, lt) if lf and lt else None
        # ---- Ansicht: Nacht > Wochenvorschau > normal ---------------------
        def window(prefix):
            if not flag(f"{prefix}Enabled"):
                return None
            a, b = bahn.parse_hhmm(opt(f"{prefix}From")), bahn.parse_hhmm(opt(f"{prefix}To"))
            return (a, b) if a and b and a != b else None
        night_win, week_win, month_win = window("night"), window("week"), window("month")
        fest_cfg = festtage.read_config(opt, flag)
        fest_now = festtage.view(now, fest_cfg)
        mode = "normal"
        if fest_now:  # Festansicht geht Nachtbild und Wochenvorschau vor
            mode = "fest"
        elif night_win and ansichten.in_window(now, *night_win):
            mode = "night"
        elif month_win and now.day == 1 and ansichten.in_window(now, *month_win):
            mode = "monat"  # Monatsbild (seit 1.38): am Monatsersten, geht der Wochenvorschau vor
        elif week_win and ansichten.in_window(now, *week_win, weekday=WEEK_DAY):
            mode = "week"
        if mode != "normal":
            news_now = train_now = False  # Sonderansichten zeigen weder Nachrichten noch Live-Zug

        # Bild-Cache außerhalb des Zugfensters – auch ohne Zug bzw. ohne gewählten Wochentag: Steht
        # die Playlist noch auf dem schnellen Zug-Takt (5 min), gilt sonst „Sonst alle … min“ nie
        # (Fehler bis 1.31). Verlängern kann der Cache einen langsameren Takt nicht (cache_fresh).
        use_cache = not train_now
        cache_key = json.dumps([settings, list(dimensions)], sort_keys=True, default=str)
        # Warnungen aus NINA (seit 1.38) schon vor den Bild-Caches: Eine neue Warnung soll beim nächsten
        # Takt erscheinen, auch mitten in der Nacht (Nachtbild sonst bis 6 Uhr eingefroren)
        warnings, warn_sig = [], ""
        nina_ars = nina.read_ars(opt("ninaArs")) if flag("ninaEnabled") else None
        if nina_ars:
            try:
                warnings = nina.load(nina_ars, *self.home_position(settings))
                warn_sig = nina.signature(warnings)
            except Exception:  # Zusatz: nie das ganze Bild verlieren
                logger.exception("Warnungen konnten nicht geladen werden")
        if mode == "night" and flag("nightFreeze") and not self._manual_refresh():
            hit = _NIGHT_CACHE.get(cache_key)
            if hit and hit.get("warn") != warn_sig:
                logger.info("Warnungen haben sich geändert – Nachtbild wird neu gezeichnet")
            elif hit and now < hit["until"]:
                logger.info("Nachtbild von %s wiederverwendet (bis %s)", hit["made"], hit["until"].strftime("%H:%M"))
                return hit["image"].copy()
        if use_cache and not self._manual_refresh():
            hit = _IMAGE_CACHE.get(cache_key)
            takt = cycle_seconds(device_config)
            if hit and hit.get("warn") != warn_sig:
                logger.info("Warnungen haben sich geändert – Bild wird neu gezeichnet")
            elif hit and cache_fresh(now, hit["quiet"], hit["edge"], takt):
                logger.info("Zugfenster nicht aktiv – Bild von %s wiederverwendet (Takt %s, neu um %s)",
                            hit["made"], f"{takt // 60} min" if takt else "unbekannt",
                            min(t for t in (hit["quiet"], hit["edge"]) if t).strftime("%H:%M"))
                return hit["image"].copy()

        status.begin()  # ab hier melden die Module, welche Quelle antwortet (Statusanzeige im Kopf)
        switch = self._opt(settings, "switchHour")
        focus = today + timedelta(days=1) if switch.isdigit() and now.hour >= int(switch) else today

        # ---- Kalender (darf ausfallen, dann nur Wetter) -------------------
        events, calendars, cal_error = [], [], None
        try:
            events, calendars = self.load_calendar(settings, device_config, tz, today, flag,
                                                   min_days=8 if mode == "week" else monat.days_needed(today)
                                                   if mode == "monat" else 0,
                                                   history=mode == "week" and flag("loadEnabled"))
            status.ok("Kalender")  # ein einzelner unlesbarer Kalender hat schon fail gemeldet
        except RuntimeError as exc:
            cal_error = str(exc)
            logger.warning("Kalender nicht verfügbar: %s", exc)
            status.fail("Kalender", exc)

        # ---- Wetter (darf ausfallen, dann nur Kalender) ------------------
        weather, wx_error = None, None
        try:
            weather = self.load_weather(settings, tz, now, focus, flag, days=8 if mode == "week" else 2)
            status.ok("Wetter")
        except RuntimeError as exc:
            wx_error = str(exc)
            logger.warning("Wetter nicht verfügbar: %s", exc)
            status.fail("Wetter", exc)

        if weather is None and cal_error:
            status.commit(now)  # Ausfall trotzdem mitzählen, auch wenn es kein Bild gibt
            self.pi_record(now, device_config, flag("piEnabled"))
            raise RuntimeError(f"Weder Wetter noch Kalender verfügbar. Wetter: {wx_error} Kalender: {cal_error}")

        use_colors = flag("useColors")
        for ev in events:
            ev["color"] = ev["cal_color"] if use_colors else "#000000"
            ev["fg"] = nc.contrast_color(ev["color"])

        records = weather["records"] if weather else []

        # ---- Urlaubsbild: läuft ein mehrtägiger Urlaub, ersetzt die Abfahrtstafel das Dashboard ----
        vacation = None
        if flag("urlaubEnabled") and events and mode in ("normal", "night", "week"):
            vacation = urlaub.find(events, today, urlaub.keywords(settings.get("urlaubWords")),
                                   urlaub.read_min_days(settings.get("urlaubMinDays")))
            if vacation:
                logger.info("Urlaub erkannt: %s bis %s", vacation["dest"], vacation["last"])
                mode = "urlaub"
                news_now = train_now = False

        # ---- Anfahrt: Rad oder ÖPNV, wann los? (nur in der normalen Ansicht) ----
        trip_cfg = anfahrt.read_config(opt, flag, *self.home_position(settings))
        trips = {"by_event": {}, "card": None, "edges": []}
        if trip_cfg and mode == "normal" and records and events:
            try:
                trips = anfahrt.plan(events, records, now, tz, trip_cfg)
            except Exception:  # Anfahrt ist Zusatz: nie das ganze Bild verlieren
                logger.exception("Anfahrt konnte nicht berechnet werden")

        # ---- Regenradar: Regen in den nächsten zwei Stunden (nur normale Ansicht) ----
        nowcast = None
        if flag("radarEnabled") and mode == "normal" and records:
            try:
                frames = radar.fetch(*self.home_position(settings), now)
                nowcast = radar.summary(frames, now, word=self.precip_word(records, now))
            except Exception as exc:  # Radar ist Zusatz: nie das ganze Bild verlieren
                logger.warning("Regenradar nicht verfügbar: %s", exc)

        # ---- Luftqualität: Karte nur, wenn die Luft mäßig oder schlechter ist (nur normale Ansicht) ----
        air = None
        air_cfg = luft.read_config(opt, flag, *self.home_position(settings))
        if air_cfg and mode == "normal":
            try:
                air = luft.load(air_cfg, now, records)
            except Exception as exc:  # Luft ist Zusatz: nie das ganze Bild verlieren
                logger.warning("Luftqualität nicht verfügbar: %s", exc)

        # ---- Pollenflug: zusätzliche Wetter-Kachel, nur wenn eine ausgewählte Art die Schwelle erreicht ----
        pollen_cfg = pollen.read_config(opt, flag)
        if pollen_cfg and mode == "normal" and weather:
            try:
                pollen_data = pollen.load(pollen_cfg, now)
                if pollen_data:
                    weather["tiles"] = weather["tiles"] + [self.pollen_tile(pollen_data)]
            except Exception as exc:  # Pollen ist Zusatz: nie das ganze Bild verlieren
                logger.warning("Pollenflug nicht verfügbar: %s", exc)

        params = {
            "date_str": f"{WOCHENTAGE[today.weekday()]}, {today.day}. {MONATE[today.month - 1]}",
            "kw": today.isocalendar()[1],
            "updated": now.strftime("%H:%M"),
            "place": (settings.get("customTitle") or "").strip() or (weather or {}).get("place", ""),
            "weather": weather,
            "wx_error": wx_error,
            "cal_error": cal_error,
            "wear": None,
            "graph": None,
            "calendar": self.calendar_days(events, tz, now, today, settings, flag, records, trips["by_event"]),
            "trip": trips["card"],
            "nowcast": nowcast,
            "air": air,
            "greetings": [dict(g, icon=festtage.icon(g["kind"])) for g in festtage.greetings(today, fest_cfg)],
            "show_location": flag("showLocation"),
            "use_colors": use_colors,
            "plugin_settings": settings,
            "cat": None,
        }
        if weather:
            if flag("showGraph"):
                params["graph"] = self.day_graph(records, focus, now, tz, weather["sun_cache"])
            if flag("showWear"):
                params["wear"] = self.wear(records, events, focus, now, tz, self._opt(settings, "sensitivity"),
                                           uv=weather.get("uv"))

        # ---- Wetter am Zielort (seit 1.30): Termine heute und morgen, die mindestens 30 km entfernt
        # liegen, bekommen eine Zeile mit dem Wetter dort (Variante A „am Termin“) ----
        if flag("zielEnabled") and mode == "normal" and records and params["calendar"]:
            try:
                away = zielort.find(params["calendar"], self.home_position(settings), tz, now,
                                    today + timedelta(days=1), weather["dwd_plugin"], dwd, icons, dwd.parse_ts,
                                    places=anfahrt.parse_places(opt("tripPlaces")))
            except Exception:  # Zusatz: nie das ganze Bild verlieren
                away = []
                logger.exception("Zielort konnte nicht bestimmt werden")
            for it in away:
                zielort.annotate(it)
        # ---- Glätte-Hinweis und Lauf-Fenster (seit 1.37, nur normale Ansicht) ----
        if mode == "normal" and records and weather:
            ice = None
            if flag("iceEnabled"):
                try:
                    ice = glaette.check(records, now, focus, alert=weather.get("alert"))
                except Exception:  # Zusatz: nie das ganze Bild verlieren
                    logger.exception("Glätte konnte nicht geschätzt werden")
                if ice:
                    if focus != today:
                        ice["text"] = "Morgen g" + ice["text"][1:]
                    params["ice"] = ice
                    params["ice_icon"] = ICE_ICON.format(cls="lw-svg")
                    logger.info("Glätte: %s (%s)", ice["text"], ice["reason"])
            if flag("runEnabled"):
                mins = opt("runMinutes")
                try:
                    run = laufen.find(records, events, now, focus, weather["sun_cache"](focus),
                                      minutes=int(mins) if mins.isdigit() else laufen.DAUER,
                                      icy_until=ice["until"] if ice else None)
                except Exception:  # Zusatz: nie das ganze Bild verlieren
                    run = None
                    logger.exception("Lauf-Fenster konnte nicht bestimmt werden")
                if run:
                    if focus != today:
                        run["text"] = "Morgen l" + run["text"][1:]
                    params["run"] = run
                    params["run_icon"] = RUN_ICON.format(cls="lw-svg")
                    logger.info("Laufen: %s", run["full"])
        if laundry_win and records and waesche.in_window(now, *laundry_win):
            params["laundry"] = waesche.check(records, now, covered=flag("laundryCovered"))
        if news_now:
            params["news"] = nachrichten.load(news_cfg, now)
            params["news_sources"] = list(dict.fromkeys(it["source"] for g in params["news"] for it in g["items"]))
        if train_now:
            params["train"] = bahn.load(train_cfg, now, tz,
                                        client_id=device_config.load_env_key("DB_CLIENT_ID"),
                                        api_key=device_config.load_env_key("DB_API_KEY"))
        # ---- Rhein auf echtem Pegel (seit 1.28, nur Nachtbild mit Silhouette); vor commit, damit ein
        # Ausfall des Pegels gezählt wird. Ohne Daten bleibt der Rhein wie bisher ----
        river_info = None
        if mode == "night" and flag("nightArt") and flag("pegelEnabled"):
            try:
                river_info = pegel.load(now)
            except Exception:  # Zusatz: nie das ganze Bild verlieren
                logger.exception("Pegel konnte nicht geladen werden")
        # ---- Polarlicht (seit 1.37, nur Nachtbild mit Silhouette): Kp-Vorhersage der NOAA, vor commit ----
        polar_values = None
        if mode == "night" and flag("nightArt") and flag("polarEnabled"):
            try:
                polar_values = polarlicht.load_values()
            except Exception:  # Zusatz: nie das ganze Bild verlieren
                logger.exception("Polarlicht konnte nicht geladen werden")
        # ---- Warnungen aus NINA (seit 1.38, Leons Wahl „B Band“): Band unter dem Kopf in der normalen
        # Ansicht, im Nachtbild, in der Wochenvorschau und im Monatsbild; geladen schon vor den Bild-Caches ----
        warn = None
        if nina_ars:
            nina.report_status(nina_ars)
            if warnings and mode in ("normal", "night", "week", "monat"):
                w0 = warnings[0]
                warn = {"first": dict(w0, since_text=nina.since_text(w0, tz)), "more": len(warnings) - 1,
                        "icon": NINA_ICON.format(cls="lw-svg")}
                logger.info("Warnungen: %s%s (%s, %s)", w0["title"], f" und {len(warnings) - 1} weitere"
                            if len(warnings) > 1 else "", w0["provider"], w0["severity"])
        # ---- Statusanzeige: alle Abrufe dieser Runde sind gelaufen ----
        status.commit(now)
        self.pi_record(now, device_config, flag("piEnabled"))
        params["status"] = status.report(now) if mode == "normal" else []
        if params["status"]:
            logger.info("Status im Kopf: %s", ", ".join(
                f"{s['name']} seit {s['since']}" + (" (lang)" if s["long"] else "") for s in params["status"]))
        params["orientation"] = "portrait" if dimensions[1] > dimensions[0] else "landscape"
        params["warn"] = warn
        # ---- Adventskranz (seit 1.29): 1. Advent bis Heiligabend, Kopf der normalen Ansicht und der
        # Wochenvorschau; jede Adventswoche brennt eine Kerze mehr. Keine Einstellung ----
        candles = advent.candles(today) if mode in ("normal", "week") and flag("adventEnabled") else 0
        if candles:
            params["advent"] = advent.wreath(candles)
            logger.info("Advent: %d. Kerze", candles)
        # ---- Ostereier (seit 1.24): seltene Tage und seltenes Wetter, nur in der normalen Ansicht ----
        egg = ostereier.today(now) if mode == "normal" else None
        if egg:
            logger.info("Osterei: %s", egg["name"])
            if egg["greeting"]:  # wie die Festtage, aber ohne Symbol (die Katze ist das Symbol)
                params["greetings"].append({"kind": "osterei", "text": egg["greeting"], "icon": ""})
        if mode == "normal" and use_colors and ostereier.rainbow(records, now):
            params["rainbow"] = ostereier.RAINBOW_SVG
            logger.info("Osterei: Regenbogen")
        # ---- Livestream (seit 1.25): QR-Code zum Stream, solange eine Ratssitzung läuft ----
        live_words = opt("liveWords") or livestream.DEFAULT_WORDS
        today_events = next((d["events"] for d in params.get("calendar") or [] if d.get("is_today")), [])
        if mode == "normal" and flag("liveEnabled"):
            try:
                card = livestream.card(today_events, live_words, opt("liveUrl"), now)
            except Exception:  # Zusatz: nie das ganze Bild verlieren (z. B. Adresse zu lang für einen QR-Code)
                card = None
                logger.exception("Livestream-Karte konnte nicht erzeugt werden")
            if card:
                params["live"] = card
                logger.info("Livestream: %s %s → %s", card["title"], card["until"], card["href"])
        # ---- Wahlkampf-Modus (seit 1.35 vor der Katzenwahl, Anlass „wahlkampf“): Karte an Tagen mit Wahlkampftermin (und am Wahltag selbst) ----
        wahl_cfg = wahlkampf.read_config(opt, flag, today) if mode == "normal" else None
        if wahl_cfg:
            card = self.wahl_card(params, wahl_cfg, today, weather, records)
            if card:
                params["wahl_card"], params["wahl_icon"] = card, WAHL_ICON.format(cls="lw-svg")
        if flag("catEnabled") and mode == "normal":
            try:
                occasions = [name for name, on in (
                    ("geburtstag", any(g["kind"] == "geburtstag" for g in params["greetings"])),
                    ("nachrichten", bool(params.get("news"))),
                    ("zug", bool(params.get("train"))),
                    ("waesche", bool(params.get("laundry"))),
                    ("rat", bool(params.get("live"))),  # seit 1.27: Rednerpult/Akten zur Ratssitzung
                    # seit 1.34: Lichterkette vom 1. Advent bis Heiligabend – unabhängig vom Schalter für den Kranz
                    ("advent", advent.candles(today) > 0),
                    # seit 1.35: Posen zu vorhandenen Karten, spätabends und am Wochenende
                    ("radar", bool(params.get("nowcast"))),
                    ("rad", (params.get("trip") or {}).get("icon") == "bike"),
                    ("oepnv", (params.get("trip") or {}).get("icon") == "bus"),
                    ("pollen", any(t.get("label") == "Pollen" for t in (weather or {}).get("tiles") or [])),
                    ("wahlkampf", bool(params.get("wahl_card"))),
                    ("zielort", any(ev.get("away_line") for d in params.get("calendar") or [] if d.get("is_today")
                                    for ev in d.get("events") or [])),
                    ("abend", now.hour >= katze.LATE_HOUR),
                    ("wochenende", today.weekday() >= 5)) if on]
                params["cat"] = katze.choose(now, records, nowcast, weather=flag("catWeather"),
                                             feels_like=dwd.feels_like, occasions=occasions,
                                             egg=egg["pose"] if egg else None)
                logger.info("Katze: %s%s", params["cat"]["main"]["name"],
                            f" ({params['cat']['reason']})" if params["cat"]["reason"] else "")
            except Exception:  # Katze ist Zusatz: nie das ganze Bild verlieren
                logger.exception("Katze konnte nicht gewählt werden")
        if mode == "monat":  # Monatsbild (seit 1.38, Leons Wahl „C Raster + Liste“)
            year, month = today.year, today.month
            free_win = self.free_window(opt, flag)
            params["month"] = monat.grid(
                year, month, events, tz, birthdays=fest_cfg["birthdays"] if fest_cfg else (),
                free_evening=(lambda items, d: ansichten.free_evening(items, d, tz, free_win)) if free_win and not cal_error else None,
                today=today)
            params["month"]["bday_icon"] = festtage.icon("geburtstag", "mo-ic")
            params["view_error"] = cal_error or params.get("wx_error")
        if mode == "urlaub":
            self.urlaub_view(params, vacation, today, weather, dimensions, tz, now)
        if mode == "fest":
            self.fest_view(params, fest_now, now, tz, events, weather)
        elif mode in ("night", "week"):
            self.special_view(params, mode, now, tz, events, weather, train_cfg, cal_error,
                              art=flag("nightArt"), night_end=ansichten.window_end(now, *night_win) if night_win else None,
                              moon_cat=flag("catEnabled") and flag("catNight"), meteors=flag("meteorEnabled"),
                              eclipses=flag("eclipseEnabled"), planets=flag("planetEnabled"),
                              iss_pos=self.home_position(settings) if flag("issEnabled") else None,
                              river=river_info, polar=polar_values, pi=flag("piEnabled"), free_win=self.free_window(opt, flag),
                              dims=dimensions, load=flag("loadEnabled"),
                              run_file=laufbilanz.clean_path(opt("runFile")) if flag("runLogEnabled") else None)

        zeichensatz.utf8_templates(self)  # sonst rät Chromium den Zeichensatz (Akzente → „Ã©“)
        image = self.render_image(dimensions, "tagesdashboard.html", "tagesdashboard.css", params)
        if not image:
            raise RuntimeError("Bild konnte nicht erzeugt werden – siehe Logs.")
        if eink is not None:
            image = eink.prepare(image, device_config, enabled=flag("einkSnap"))
        if mode == "night" and flag("nightFreeze"):
            # Einmal pro Nacht zeichnen: bis zum Ende des Nachtfensters bleibt das Bild stehen
            _NIGHT_CACHE.clear()
            _NIGHT_CACHE[cache_key] = {"image": image.copy(), "made": now.strftime("%H:%M"),
                                       "until": ansichten.window_end(now, *night_win), "warn": warn_sig}
        if use_cache:
            # Bild höchstens quietMinutes lang wiederverwenden und nie über eine Fenstergrenze
            # hinweg (Zugfenster beginnt, Nachrichten erscheinen oder verschwinden).
            quiet = self._opt(settings, "quietMinutes")
            quiet_until = now + timedelta(minutes=int(quiet) if quiet.isdigit() else 15)
            edges = [bahn.next_window_start(now, train_cfg)] if train_cfg else []
            edges += nachrichten.boundaries(now, news_cfg) if news_cfg else []
            edges += waesche.boundaries(now, *laundry_win) if laundry_win else []
            edges += ansichten.boundaries(now, *night_win) if night_win else []
            edges += ansichten.boundaries(now, *week_win) if week_win else []
            edges += monat.boundaries(now, *month_win) if month_win else []  # Monatsbild am Ersten (seit 1.38)
            edges += trips["edges"]  # Aufbruch-Karte erscheint bzw. verschwindet
            # Glätte-Karte endet, Lauf-Fenster beginnt („jetzt bis …“) bzw. ist zu kurz geworden (seit 1.37)
            edges += [params["ice"]["until"]] if params.get("ice") else []
            edges += [params["run"]["start"] - laufen.STEP, params["run"]["last_start"]] if params.get("run") else []
            edges += festtage.boundaries(now, fest_cfg)  # Gruß und Festbild (u. a. Mitternacht an Silvester)
            edges += status.boundaries(now)  # „● Kalender“ wird zu „● Kalender seit 9:10 nicht erreichbar“
            edges += ostereier.boundaries(now)  # Osterei des Tages (Mitternacht, 11.11. um 11:11)
            edges += advent.boundaries(now) if flag("adventEnabled") else []  # Kranz kommt, bekommt eine Kerze mehr, geht nach Heiligabend
            if flag("liveEnabled"):  # Livestream-Karte kommt zu Beginn der Sitzung und geht an ihrem Ende
                edges += livestream.boundaries(today_events, live_words, now)
            edge = min((e for e in edges if e and e > now), default=None)
            _IMAGE_CACHE.clear()  # nur ein Bild merken (Speicher auf dem Pi Zero)
            _IMAGE_CACHE[cache_key] = {"image": image.copy(), "quiet": quiet_until, "edge": edge,
                                       "made": now.strftime("%H:%M"), "warn": warn_sig}
        return image

    # ==================================================================
    # Festansicht (Heiligabend, Silvester/Neujahr, später Geburtstag)
    # ==================================================================
    def fest_view(self, params, fest, now, tz, events, weather):
        helper = nc.NextcloudKalender({"id": "nextcloud_kalender"})
        records = weather["records"] if weather else []
        w = weather["dwd_plugin"] if weather else None
        d = now.date()
        portrait = params["orientation"] == "portrait"
        kind = fest["kind"]
        label = f"{festtage.VIEW_LABEL.get(kind, WOCHENTAGE[d.weekday()])} · {d.day}. {MONATE[d.month - 1]}"
        if kind == "neujahr":
            label += f" {d.year}"
        items = helper.events_on_day(events, d, tz, now, False) if events else []
        params["fest"] = {
            "kind": kind,
            "label": label,
            "svg": festtage.scene(kind, 480 if portrait else 800, festtage.ART_H[portrait], seed=d.toordinal(),
                                  year=fest.get("year"), names=fest.get("names", ()), age=fest.get("age")),
            "wx": ansichten.day_summary(w, dwd, icons, records, d, "fe-icon") if w and records else None,
            "events": items[:4 if portrait else 3],
            "more": max(0, len(items) - (4 if portrait else 3)),
        }

    # ==================================================================
    # Urlaubsbild und Wahlkampf-Karte
    # ==================================================================
    def urlaub_view(self, params, vacation, today, weather, dimensions, tz, now):
        records = weather["records"] if weather else []
        w = weather["dwd_plugin"] if weather else None
        wx_home = ansichten.day_summary(w, dwd, icons, records, today, "ur-ic") if w and records else None
        wx_dest = None
        pos = urlaub.geocode(vacation["dest"])
        if pos and w:
            dest_records = urlaub.fetch_records(pos, tz, now, dwd.parse_ts)
            wx_dest = ansichten.day_summary(w, dwd, icons, dest_records, today, "ur-ic") if dest_records else None
        W = 800 if dimensions[0] >= dimensions[1] else 480
        H = round(W * dimensions[1] / dimensions[0])
        params["urlaub"] = {"svg": urlaub.scene(W, H, vacation, today, wx_dest, wx_home)}

    @staticmethod
    def wahl_card(params, cfg, today, weather, records):
        """Karte oben in der Terminspalte: am Wahltag und am Tag davor immer, sonst nur, wenn heute ein
        Wahlkampftermin ansteht (dann mit Wetter, Dämmerung und gefühlter Temperatur)."""
        cd = wahlkampf.countdown(today, cfg["day"], cfg["label"])
        if not cd:
            return None
        if cd["n"] <= 1:
            return {"top": cd["text"], "sub": "Wahllokale 8–18 Uhr" if cd["n"] == 0 else "Wahllokale morgen 8–18 Uhr",
                    "sub2": "", "level": "ok", "badge_n": cd["badge"][0], "badge_t": cd["badge"][1]}
        today_events = next((d["events"] for d in params.get("calendar") or [] if d.get("is_today")), [])
        if not records:
            return None
        for it in today_events:
            if it["all_day"] or not wahlkampf.is_campaign(it["title"], cfg["words"]):
                continue
            sunset = weather["sun_cache"](it["source"]["start"].date())[1]
            wx_ = wahlkampf.weather_at(it["source"], records, sunset, dwd.feels_like)
            if not wx_:
                continue
            return {"top": it["title"], "sub": f"{wx_['time']} · {wx_['rain']}",
                    "sub2": " · ".join(x for x in (wx_["dark"], wx_["felt"]) if x),
                    "level": wx_["level"], "badge_n": cd["badge"][0], "badge_t": cd["badge"][1]}
        return None

    # ==================================================================
    # Nachtbild und Wochenvorschau
    # ==================================================================
    def pi_record(self, now, device_config, enabled):
        """Zustand des Pi für die Wochenvorschau mitschreiben (seit 1.28): Ausfälle aus der Statusanzeige,
        Temperatur, Neustarts, Unterspannung. Läuft in jeder Runde mit echten Abrufen, auch ohne Bild."""
        if not enabled:
            return
        try:
            self._pi_path = pizustand.state_path(device_config)
            pizustand.record(now, status.snapshot(), path=self._pi_path)
        except Exception:  # Zusatz: nie das ganze Bild verlieren
            logger.exception("Zustand des Pi konnte nicht gespeichert werden")

    @staticmethod
    def free_window(opt, flag):
        """Fenster für die freien Abende (seit 1.29) oder None, wenn der Schalter aus ist.

        Ungültige oder gleiche Zeiten → Standard 18–22 Uhr (lieber eine Aussage als stillschweigend keine).
        „bis“ vor „von“ (z. B. 19:00–0:30) heißt: über Mitternacht.
        """
        if not flag("freeEnabled"):
            return None
        a, b = bahn.parse_hhmm(opt("freeFrom")), bahn.parse_hhmm(opt("freeTo"))
        return (a, b) if a and b and a != b else ansichten.EVENING

    def special_view(self, params, mode, now, tz, events, weather, train_cfg, cal_error, art=False, night_end=None,
                     moon_cat=False, meteors=False, eclipses=False, planets=False, iss_pos=None, river=None,
                     polar=None, pi=False, free_win=None, dims=(800, 480), load=False, run_file=None):
        helper = nc.NextcloudKalender({"id": "nextcloud_kalender"})
        records = weather["records"] if weather else []
        w = weather["dwd_plugin"] if weather else None

        def items_on(d):
            return helper.events_on_day(events, d, tz, now, False) if events else []

        if mode == "night":
            d = now.date() if now.hour < 12 else now.date() + timedelta(days=1)
            params["night"] = ansichten.night(now, records if w else [], items_on(d), w, dwd, icons, train_cfg,
                                              weather["sun_cache"] if weather else None)
            if art:
                wx = nachtgrafik.night_weather(records, now, night_end or now + timedelta(hours=7)) if records else None
                meteor_info = meteore.active(d) if meteors else None
                streaks = 4 if meteore.show_streaks(meteor_info, wx) else 0
                if meteor_info:
                    logger.info("Sternschnuppen: %s%s", meteor_info["text"],
                                " (SVG gezeichnet)" if streaks else "")
                eclipse_info = finsternisse.next_eclipse(d) if eclipses else None
                blood = finsternisse.show_blood_moon(eclipse_info)
                if eclipse_info:
                    logger.info("Finsternis: %s%s", eclipse_info["text"], " (Blutmond gezeichnet)" if blood else "")
                planet_info = planeten.active(d) if planets else None
                planet_dot = planet_info["kind"] if planeten.show_dot(planet_info, wx) else None
                if planet_info:
                    logger.info("Planeten: %s%s", planet_info["text"], " (Punkt gezeichnet)" if planet_dot else "")
                felis = ostereier.felis_night(d, wx)  # Osterei (seit 1.24): Sternbild Katze
                if felis:
                    logger.info("Osterei: Sternbild Katze")
                art_w = nachtgrafik.band_width(*dims)  # randlos bis an den Displayrand (seit 1.31)
                iss_line, iss_svg = "", None
                end = night_end or now + timedelta(hours=7)
                nxt = [p for p in iss.passes(now, *iss_pos) if iss.worth(p) and p["end"] > now] if iss_pos else []
                if nxt and nxt[0]["start"] < end:
                    p, txt = nxt[0], iss.describe(nxt[0])
                    same = p["start"].date() == now.date()
                    when = ("heute" if same else "morgen") + (" früh" if p["start"].hour < 12 else "")
                    iss_line = f"ISS {when} {txt['time']} ({txt['route_short']})"
                    logger.info("ISS: %s %s: %s · %s · %s · %s", when, txt["time"], txt["route"], txt["peak"],
                                txt["mins"], txt["bright"])
                    clear = (wx or {}).get("cloud", 100) < 60 and not (wx or {}).get("wet")
                    iss_svg = iss.night_arc(art_w) if clear else None
                aurora = polarlicht.night_info(polar, now, wx, end) if polar else None

                def first(text, prefix=""):
                    t = text.split(" · ")[0]
                    return t[len(prefix):] if prefix and t.startswith(prefix) else t
                # Himmelszeile (seit 1.37, Leons Wahl „A eine Zeile“): Kurzfassungen, wichtigste zuerst. Was nicht in
                # eine Zeile passt, lässt fitSky im Template von hinten weg. Ohne Ereignis: Nachtwetter und Mond.
                sky = []
                if aurora:
                    sky.append(f"Polarlicht möglich ab {aurora['when'].hour} Uhr" if aurora["draw"]
                               else "Polarlicht möglich, aber bewölkt")
                if eclipse_info:
                    sky.append(first(eclipse_info["text"]))      # „Mondfinsternis heute Nacht: total“
                if iss_line:                                    # „ISS heute 18:12 (W → O)“
                    sky.append(iss_line)
                if meteor_info:
                    sky.append(first(meteor_info["text"], "Sternschnuppen: "))
                if planet_info:
                    sky.append(first(planet_info["text"], "Planeten: "))
                daylight = nachtgrafik.daylight(weather["sun_cache"], d) if weather else ""
                params["night"]["art"] = {
                    "svg": nachtgrafik.svg(now, wx, width=art_w,
                                           cat=katze.on_moon if moon_cat else None, meteors=streaks,
                                           blood_moon=blood, planet=planet_dot, extra=iss_svg,
                                           felis=ostereier.felis_svg if felis else None, pegel=river,
                                           aurora=aurora if aurora and aurora["draw"] else None),
                    "weather": nachtgrafik.describe(wx),
                    # links unter „Sonnenaufgang“: „8 h 36 min Tageslicht (−3 min)“ (ohne Sonnenwende-Countdown)
                    "daylight": daylight.split(" · ")[0] if daylight else "",
                    "sky": sky,
                }
        else:
            portrait = params["orientation"] == "portrait"
            params["week"] = ansichten.week(now, records if w else [], items_on, w, dwd, icons, train_cfg,
                                            per_row=4 if portrait else 3, has_calendar=not cal_error,
                                            evening=free_win)
            if load and not cal_error:  # Wie voll ist die Woche? (seit 1.38, Fußzeile)
                try:
                    nxt = params["week"]["start"]
                    days = wochenlast.week_hours(events, nxt, tz)
                    avg = wochenlast.average(getattr(self, "_history", []), nxt, tz)
                    params["load"] = wochenlast.summary(days, avg)
                    logger.info("Wochenlast: %s, %s (%s)", params["load"]["total_text"],
                                params["load"]["word"] or "kein Vergleich", params["load"]["avg_text"] or "zu wenige Wochen")
                except Exception:  # Zusatz: nie das ganze Bild verlieren
                    logger.exception("Wochenlast konnte nicht berechnet werden")
            if run_file and getattr(self, "_nc_client", None) and not cal_error:  # Laufen der Woche (seit 1.38)
                try:
                    runs = laufbilanz.load(self._nc_client, self._nc_user, run_file)
                    params["runs"] = laufbilanz.summary(runs, now.date())
                    if params["runs"]:
                        logger.info("Laufbuch: %s in %s", params["runs"]["km_text"], params["runs"]["count_text"])
                except Exception:  # Zusatz: nie das ganze Bild verlieren
                    logger.exception("Laufbuch konnte nicht gelesen werden")
            if pi:  # Zustand des Pi in der Fußzeile (seit 1.28)
                try:
                    params["pi_parts"] = pizustand.parts(now, getattr(self, "_pi_path", None))
                    logger.info("Pi: %s", " · ".join(p["text"] for p in params["pi_parts"]))
                except Exception:  # Zusatz: nie das ganze Bild verlieren
                    logger.exception("Zustand des Pi konnte nicht ermittelt werden")
        params["view_error"] = cal_error or params.get("wx_error")

    # ==================================================================
    # Kalender
    # ==================================================================
    def load_calendar(self, settings, device_config, tz, today, flag, min_days=0, history=False):
        user = (settings.get("username") or "").strip()
        url = (settings.get("nextcloudUrl") or "").strip()
        if not user or not url:
            raise RuntimeError("Nextcloud-Adresse oder Benutzername fehlt.")
        client, confirm = nc.open_client(settings, device_config, user, flag("verifySSL"))

        days = int(self._opt(settings, "calendarDays")) if self._opt(settings, "calendarDays").isdigit() else 7
        start = datetime.combine(today, time.min, tz)
        end = start + timedelta(days=max(days, 2, min_days) + 1)

        helper = nc.NextcloudKalender({"id": "nextcloud_kalender"})
        found = client.calendars()  # wirft bei falscher Anmeldung – erst danach die Nextcloud merken
        confirm()
        calendars = helper.select_calendars(found, settings.get("calendars", ""))
        events = []
        for cal in calendars:
            try:
                for ics in client.events(cal["url"], start, end):
                    events.extend(helper.parse_events(ics, cal, tz, start, end, client.own_addresses))
            except RuntimeError as exc:
                logger.warning("Kalender %s nicht lesbar: %s", cal["name"], exc)
                status.fail("Kalender", f"{cal['name']}: {exc}")
        self._nc_client, self._nc_user = client, user
        self._history = []
        if history:  # Wochenlast (seit 1.38): acht vergangene Wochen, einmal am Tag abgefragt
            key = (url, user, settings.get("calendars", ""), today.isoformat())
            if _HISTORY.get("key") == key:
                self._history = _HISTORY["events"]
            else:
                monday = today + timedelta(days=(7 - today.weekday()) % 7 or 7)
                h_start = datetime.combine(monday - timedelta(days=7 * wochenlast.HISTORY_WEEKS), time.min, tz)
                complete = True
                for cal in calendars:
                    try:
                        for ics in client.events(cal["url"], h_start, start):
                            self._history.extend(helper.parse_events(ics, cal, tz, h_start, start, client.own_addresses))
                    except RuntimeError as exc:
                        complete = False
                        logger.warning("Kalender %s (vergangene Wochen) nicht lesbar: %s", cal["name"], exc)
                if complete:  # unvollständig: nächste Runde noch einmal versuchen
                    _HISTORY.clear()
                    _HISTORY.update(key=key, events=self._history)
                logger.info("Wochenlast: %d Termine aus %d vergangenen Wochen geladen",
                            len(self._history), wochenlast.HISTORY_WEEKS)
        if getattr(helper, "declined_hidden", 0):
            logger.info("Kalender: %d abgelehnte Termine ausgeblendet", helper.declined_hidden)
        return events, calendars

    def calendar_days(self, events, tz, now, today, settings, flag, records, trips=None):
        helper = nc.NextcloudKalender({"id": "nextcloud_kalender"}) if nc else None
        if helper is None:
            return []
        n = int(self._opt(settings, "calendarDays")) if self._opt(settings, "calendarDays").isdigit() else 7
        out = []
        for i in range(n):
            d = today + timedelta(days=i)
            items = helper.events_on_day(events, d, tz, now, flag("showPast"))
            if flag("rainOnEvents"):
                for it in items:
                    it["rain"] = self.rain_during(records, it["source"]) if not it["all_day"] else None
            for it in items:
                # Anfahrt ersetzt den Regenhinweis: ob es während des Termins regnet, ist dann egal
                it["trip"] = (trips or {}).get(id(it["source"]))
                if it["trip"]:
                    it["rain"] = None
            if items or i == 0:
                label = "Heute" if i == 0 else ("Morgen" if i == 1 else WOCHENTAGE_KURZ[d.weekday()])
                out.append({
                    "label": label,
                    "date": "" if i == 0 else f"{d.day}. {MONATE[d.month - 1]}" if i == 1 else f"{d.day}.{d.month}.",
                    "is_today": i == 0,
                    "events": items,
                })
        return out

    @staticmethod
    def rain_during(records, ev):
        """Höchste Regenwahrscheinlichkeit während eines Termins (nur wenn ≥ 50 %)."""
        s, e = ev["start"], max(ev["end"], ev["start"] + timedelta(hours=1))
        probs = [r.get("precipitation_probability") for r in records
                 if s - timedelta(minutes=59) <= r["dt"] <= e and r.get("precipitation_probability") is not None]
        if probs and max(probs) >= 50:
            return f"{round(max(probs))} % Regen"
        return None

    # ==================================================================
    # Wetter
    # ==================================================================
    @staticmethod
    def home_position(settings):
        """Wetterstandort als (lat, lon) – Startpunkt der Anfahrt, wenn kein eigener gesetzt ist."""
        try:
            return (float(str(settings.get("latitude", "")).strip().replace(",", ".")),
                    float(str(settings.get("longitude", "")).strip().replace(",", ".")))
        except ValueError:
            return None, None

    def load_weather(self, settings, tz, now, focus, flag, days=2):
        raw_lat = str(settings.get("latitude", "")).strip().replace(",", ".")
        raw_lon = str(settings.get("longitude", "")).strip().replace(",", ".")
        try:
            lat, lon = float(raw_lat), float(raw_lon)
        except ValueError:
            raise RuntimeError("Bitte einen Ort für das Wetter wählen.")

        w = dwd.DwdWetter({"id": "dwd_wetter"})
        opts = {
            "show_alerts": flag("showAlerts"), "show_graph": False, "night_shading": True,
            "graph_icons": True, "hours": 24, "days": days,
            # Platz 5 wird durch den UV-Index ersetzt; Bewölkung ist der Ersatz ohne UV-Daten
            "tiles": ["wind", "gust", "precip", "humidity", "cloudcover", "sun"],
            # ab gestern 0 Uhr, für „4° kälter als gestern“ (kleidung.vergleich, seit 1.22)
            "history_hours": 24,
        }
        data = w.fetch_data(lat, lon, tz, now, opts)
        base = w.build_template_params(data, lat, lon, tz, now, opts, settings)

        cache = {}

        def sun_cache(d):
            if d not in cache:
                cache[d] = w.sun_times(lat, lon, d, tz)
            return cache[d]

        records = []
        for rec in (data["hourly"] or {}).get("weather", []):
            try:
                rec = dict(rec)
                rec["dt"] = dwd.parse_ts(rec["timestamp"], tz)
                records.append(rec)
            except (KeyError, ValueError):
                continue
        records.sort(key=lambda r: r["dt"])

        offset = (focus - now.date()).days  # 0 = heute, 1 = morgen
        uv = self.load_uv(settings.get("uvCity", ""), base["title"])
        uv_value = None
        if uv:
            uv_value = uv.get(["today", "tomorrow", "dayafter_to"][min(offset, 2)])

        result = {
            "uv": uv_value,
            "place": base["title"],
            "station": base["station"],
            "alert": base["alerts"][0] if base["alerts"] else None,
            "alerts_more": base["alerts_more"],
            "records": records,
            "sun_cache": sun_cache,
            "dwd_plugin": w,
        }
        if focus == now.date():
            cur = base["current"]
            result.update({
                "is_today": True,
                "label": None,
                "icon": cur["icon"],
                "temp": cur["temp"],
                "text": cur["text"],
                "sub": f"↑{cur['tmax']}° ↓{cur['tmin']}°" + (f" · gefühlt {cur['feels']}°" if cur["show_feels"] else ""),
                "tiles": self.today_tiles(base["tiles"], records, now.date()),
            })
        else:
            result.update(self.focus_day(w, records, focus, tz, sun_cache))
        if uv_value is not None:
            result["tiles"] = [self.uv_tile(uv_value, offset) if t.get("key") == "cloudcover" else t
                               for t in result["tiles"]]
        result["tiles"] = self.slim_tiles(result["tiles"])
        return result

    # ------------------------------------------------------------------
    def load_uv(self, wanted, place):
        """UV-Index vom DWD; der Ort wird über den Namen zugeordnet (z. B. „Bonn“)."""
        names = [n.strip() for n in (wanted, place) if n and n.strip()]
        if not names:
            return None
        try:
            session = requests.Session()
            session.headers.update({"User-Agent": dwd.USER_AGENT})
            resp = session.get(UVI_URL, timeout=15)
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code}")
            entries = resp.json().get("content") or []
        except Exception as exc:
            logger.warning("UV-Index nicht verfügbar: %s", exc)
            status.fail("UV-Index", exc)
            return None
        status.ok("UV-Index")
        by_city = {(e.get("city") or "").casefold(): e.get("forecast") or {} for e in entries}
        for name in names:
            key = name.casefold()
            if key in by_city:
                return by_city[key]
            # z. B. "Frankfurt" passt auf "Frankfurt/Main"
            for city, fc in by_city.items():
                if city.startswith(key) or key.startswith(city):
                    return fc
        logger.info("Kein UV-Index für %s. Verfügbare Orte: %s", names,
                    ", ".join(sorted(e.get("city", "") for e in entries)))
        return None

    @staticmethod
    def uv_stufe(value):
        for limit, name, bg, fg in UV_STUFEN:
            if value <= limit:
                return name, bg, fg
        return UV_STUFEN[-1][1:]

    def uv_tile(self, value, offset):
        name, bg, fg = self.uv_stufe(value)
        badge = (f'<svg class="mx-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
                 f'<rect x="2" y="5" width="28" height="22" rx="5" fill="{bg}" stroke="currentColor" stroke-width="2.4"/>'
                 f'<text x="16" y="21" text-anchor="middle" font-family="Jost, sans-serif" font-weight="700" '
                 f'font-size="13" fill="{fg}">UV</text></svg>')
        return {"icon": badge, "label": "UV " + ("heute" if offset == 0 else "morgen"),
                "value": str(int(round(value))), "unit": name, "key": "uv"}

    @staticmethod
    def slim_tiles(tiles):
        """Kacheln entschlacken (seit 1.36): Wind und Böen in einer Kachel, UV erst ab Stufe 3.

        „UV 1 niedrig“ sagt den größten Teil des Jahres nichts; ohne UV-Daten fällt auch die
        Ersatzkachel Bewölkung weg (die Bewölkung steckt schon im Wettersymbol). So bleiben
        meist vier Kacheln im Raster 2 × 2, und die Tageskurve bekommt den Platz."""
        gust = next((t for t in tiles if t["label"].startswith("Böen")), None)
        out = []
        for t in tiles:
            key = t.get("key")
            if t is gust or key == "cloudcover":
                continue
            if key == "uv" and UV_MIN_SHOWN and int(t["value"]) < UV_MIN_SHOWN:
                continue
            if t["label"].startswith("Wind") and gust is not None:
                t = dict(t, label="Wind · Böen", raw=True,
                         value=f'{t["value"]}<span class="sep">/</span>{gust["value"]}')
            out.append(t)
        # UV ans Ende: die vier gewohnten Plätze bleiben gleich, UV steht in einer dritten Zeile
        return [t for t in out if t.get("key") != "uv"] + [t for t in out if t.get("key") == "uv"]

    @staticmethod
    def pollen_tile(data):
        """Siebte, breite Kachel aus den Rohdaten von pollen.load(): Art + Stufe, Gelb/Rot ab mittel."""
        extra_class = "tile-wide"
        if data["word"] != "gering":
            extra_class += f" lvl-{data['word']}"
        return {"icon": icons.metric_icon("pollen"), "label": "Pollen", "value": data["lead"],
                "unit": data["word"], "extra": f"+{data['more']} weitere" if data["more"] else "",
                "extra_class": extra_class}

    @staticmethod
    def today_tiles(tiles, records, d):
        """Kacheln aus dem DWD-Plugin, mit kürzeren Beschriftungen fürs Dashboard."""
        snowy = any(r.get("icon") in ("snow", "sleet") for r in records if r["dt"].date() == d)
        out = []
        for t in tiles:
            if t["label"] == "Bewölkung":
                t = dict(t, key="cloudcover")
            if t["label"] == "Regen heute" and snowy:
                t = dict(t, label="Schnee heute")
            out.append(t)
        return out

    def focus_day(self, w, records, d, tz, sun_cache):
        """Kopfbereich und Kacheln für den nächsten Tag (abends)."""
        day = [r for r in records if r["dt"].date() == d]
        if not day:
            raise RuntimeError("Keine Vorhersage für morgen verfügbar.")
        daytime = [r for r in day if 7 <= r["dt"].hour <= 20] or day
        val = lambda key, recs=day: [r[key] for r in recs if r.get(key) is not None]  # noqa: E731
        temps = val("temperature")
        icon = w.day_icon(day)
        precip = sum(r.get("precipitation") or 0 for r in day)
        probs = val("precipitation_probability")
        winds = val("wind_speed", daytime)
        dirs = val("wind_direction", daytime)
        gusts = val("wind_gust_speed")
        hums = val("relative_humidity", daytime)
        clouds = val("cloud_cover", daytime)
        sr, ss = sun_cache(d)
        mi = icons.metric_icon
        wind = sum(winds) / len(winds) if winds else None
        wdir = dirs[len(dirs) // 2] if dirs else None
        wind_extra = ""
        if wdir is not None and (wind or 0) >= 1:
            wind_extra = icons.wind_arrow(wdir, "tile-arrow") + f"<span>{dwd.compass(wdir)}</span>"
        tiles = [
            {"icon": mi("wind"), "label": "Wind tagsüber", "value": dwd.de_num(wind), "unit": "km/h", "extra": wind_extra},
            {"icon": mi("gust"), "label": "Böen bis", "value": dwd.de_num(max(gusts) if gusts else None), "unit": "km/h"},
            {"icon": mi("precip"), "label": "Regen morgen", "value": dwd.de_num(precip, 1), "unit": "mm",
             "extra": f"<span>{dwd.de_num(max(probs))} %</span>" if probs else ""},
            {"icon": mi("humidity"), "label": "Luftfeuchte", "value": dwd.de_num(sum(hums) / len(hums) if hums else None), "unit": "%"},
            {"icon": mi("cloudcover"), "label": "Bewölkung", "key": "cloudcover",
             "value": dwd.de_num(sum(clouds) / len(clouds) if clouds else None), "unit": "%"},
        ]
        if sr and ss:
            tiles.append({"icon": mi("sun_times"), "label": "Sonne",
                          "value": f'{hm(sr)}<span class="sep">–</span>{hm(ss)}', "unit": "", "raw": True})
        mean_cloud = sum(clouds) / len(clouds) if clouds else None
        return {
            "is_today": False,
            "label": f"Morgen · {WOCHENTAGE[d.weekday()]}",
            "icon": icons.weather_icon(icon, "cur-icon"),
            "temp": dwd.de_num(max(temps)) if temps else "–",
            "text": dwd.condition_text(icon, precip / max(len(day), 1), mean_cloud, True),
            "sub": f"Höchstwert · tiefst {dwd.de_num(min(temps))}°" if temps else "",
            "tiles": tiles,
        }

    # ------------------------------------------------------------------
    def day_graph(self, records, d, now, tz, sun_cache):
        start = datetime.combine(d, time(GRAPH_START), tz)
        end = datetime.combine(d, time.min, tz) + timedelta(hours=GRAPH_END)
        pts = [r for r in records if start <= r["dt"] <= end and r.get("temperature") is not None]
        if len(pts) < 4:
            return None
        n = len(pts)
        W, H = 1000.0, 300.0
        slot = W / n
        temps = [r["temperature"] for r in pts]
        tmax, tmin = max(temps), min(temps)
        span = max(tmax - tmin, 4.0)
        mid = (tmax + tmin) / 2
        lo, hi = mid - span / 2, mid + span / 2
        top, bottom = 0.30, 0.72
        x = lambda i: (i + 0.5) * slot  # noqa: E731
        y = lambda t: H * (top + (hi - t) / (hi - lo) * (bottom - top))  # noqa: E731
        left = lambda i: f"{(i + 0.5) / n * 100:.2f}"  # noqa: E731

        P = [(x(i), y(t)) for i, t in enumerate(temps)]
        line = f"M{P[0][0]:.1f},{P[0][1]:.1f}"
        for i in range(len(P) - 1):
            p0 = P[i - 1] if i > 0 else P[i]
            p1, p2 = P[i], P[i + 1]
            p3 = P[i + 2] if i + 2 < len(P) else p2
            c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
            c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
            line += f" C{c1[0]:.1f},{c1[1]:.1f} {c2[0]:.1f},{c2[1]:.1f} {p2[0]:.1f},{p2[1]:.1f}"

        # Regen bekommt eine eigene Zeile unter der Kurve: Höhe = Menge, Füllung = Stärke.
        rain = []
        for i, r in enumerate(pts):
            amount = r.get("precipitation") or 0
            if amount >= 0.05:
                level = next(name for limit, name in RAIN_LEVELS if amount < limit)
                h = 100 * max(min(amount / RAIN_SCALE, 1.0), 0.28)  # auch Niesel bleibt sichtbar
                rain.append({"x": f"{i * slot + slot * 0.08:.1f}", "w": f"{slot * 0.84:.1f}",
                             "y": f"{100 - h:.1f}", "h": f"{h:.1f}", "cls": level})
        used_levels = {c["cls"] for c in rain}

        icon_hours = {9, 12, 15, 18, 21}
        gicons, xlabels = [], []
        for i, r in enumerate(pts):
            h = r["dt"].hour
            if h in icon_hours:
                day = sun_cache(r["dt"].date())
                is_day = day[0] <= r["dt"] < day[1] if day[0] and day[1] else 7 <= h < 18
                ic = dwd.refine_icon(r.get("icon"), r.get("precipitation"), r.get("cloud_cover"), is_day)
                gicons.append({"left": left(i), "svg": icons.weather_icon(ic, "g-icon")})
                xlabels.append({"left": left(i), "text": str(h)})

        imax, imin = temps.index(tmax), temps.index(tmin)
        tlabels = [{"left": left(imax), "top": f"{y(tmax) / H * 100:.2f}", "text": f"{dwd.de_num(tmax)}°", "cls": "t-max"}]
        if imin != imax:
            tlabels.append({"left": left(imin), "top": f"{y(tmin) / H * 100:.2f}", "text": f"{dwd.de_num(tmin)}°", "cls": "t-min"})
        for t in tlabels:
            v = float(t["left"])
            t["edge"] = " edge-l" if v < 6 else (" edge-r" if v > 94 else "")

        now_left = None
        if start <= now <= end:
            now_left = f"{((now - start).total_seconds() / 3600 + 0.5) / n * 100:.2f}"
        return {"line": line, "icons": gicons, "xlabels": xlabels,
                "tlabels": tlabels, "now_left": now_left, "rain": rain,
                "rain_levels": [lv for _, lv in RAIN_LEVELS if lv in used_levels],
                "rain_summary": self.rain_summary(pts, now, d)}

    @staticmethod
    def precip_word(records, now):
        """Regen, Schnee oder Niederschlag in den nächsten zwei Stunden – das Radar kennt die Art nicht."""
        near = [r for r in records if now - timedelta(hours=1) <= r["dt"] <= now + timedelta(hours=3)]
        snowy = sum(1 for r in near if r.get("icon") in ("snow", "sleet") or r.get("condition") in ("snow", "sleet"))
        wet = sum(1 for r in near if (r.get("precipitation") or 0) >= 0.1 or r.get("icon") in ("rain", "snow", "sleet"))
        if not snowy:
            return "Regen"
        return "Schnee" if snowy >= max(wet, 1) * 0.6 else "Niederschlag"

    @staticmethod
    def rain_summary(pts, now, d):
        """Kopfzeile der Tageskurve, z. B. „Regen 17–23 Uhr · 6,8 mm · bis 85 %“."""
        relevant = [r for r in pts if d != now.date() or r["dt"] >= now - timedelta(minutes=59)]
        if not relevant:
            return "Kein Regen mehr erwartet"
        wet = [r for r in relevant if (r.get("precipitation") or 0) >= 0.1
               or (r.get("precipitation_probability") or 0) >= 50]
        probs = [r["precipitation_probability"] for r in relevant if r.get("precipitation_probability") is not None]
        if not wet:
            if probs and max(probs) >= 30:
                return f"Kaum Regen · Risiko bis {round(max(probs))} %"
            return "Kein Regen erwartet" if d != now.date() else "Kein Regen mehr erwartet"
        total = sum(r.get("precipitation") or 0 for r in relevant)
        first, last = wet[0]["dt"], wet[-1]["dt"]
        snowy = sum(1 for r in wet if r.get("icon") in ("snow", "sleet") or r.get("condition") in ("snow", "sleet"))
        word = "Schnee" if snowy > len(wet) / 2 else ("Niederschlag" if snowy else "Regen")
        if d == now.date() and first <= now:
            when = f"{word} bis {last.hour} Uhr"
        elif first == last:
            when = f"{word} um {first.hour} Uhr"
        else:
            when = f"{word} {first.hour}–{last.hour if last.hour else 24} Uhr"
        return f"{when} · {dwd.de_num(total, 1)} mm"

    # ------------------------------------------------------------------
    def wear(self, records, events, d, now, tz, sensitivity, uv=None):
        """Kleidungsempfehlung für die Zeit, in der man voraussichtlich unterwegs ist."""
        day_start = datetime.combine(d, time.min, tz)
        day_end = day_start + timedelta(days=1)
        timed = [e for e in events if not e["all_day"] and e["start"] < day_end and e["end"] > day_start]
        reason = None
        if d == now.date():
            start = now.replace(minute=0, second=0, microsecond=0)
            end = start + timedelta(hours=MIN_WEAR_HOURS)
            later = [e for e in timed if e["end"] > now]
            if later:
                last = max(later, key=lambda e: e["end"])
                if last["end"] > end:
                    end, reason = last["end"], last["title"]
        else:
            start = datetime.combine(d, time(7), tz)
            end = datetime.combine(d, time(19), tz)
            if timed:
                start = min(start, min(e["start"] for e in timed))
                last = max(timed, key=lambda e: e["end"])
                if last["end"] > end:
                    end, reason = last["end"], last["title"]
        end = min(end, day_end)

        def felt(r):
            return dwd.feels_like(r["temperature"], r.get("wind_speed"), r.get("relative_humidity"))

        # Vortag zur selben Uhrzeit (nach Uhrzeit, nicht „minus 24 h“ – sonst verrutscht es bei der
        # Zeitumstellung um eine Stunde; die fehlende bzw. doppelte Stunde fängt die Abdeckung ab)
        by_hour = {(r["dt"].date(), r["dt"].hour): r for r in records if r.get("temperature") is not None}
        hours, pairs = [], []
        for r in records:
            if not (start <= r["dt"] <= end + timedelta(minutes=59)) or r.get("temperature") is None:
                continue
            gef = felt(r)
            prev = by_hour.get((r["dt"].date() - timedelta(days=1), r["dt"].hour))
            pairs.append((gef, felt(prev) if prev else None))
            hours.append(kleidung.Stunde(
                gefuehlt=gef, temp=r["temperature"],
                regen_prob=r.get("precipitation_probability") or (100 if (r.get("precipitation") or 0) >= 0.3 else 0),
                regen_mm=r.get("precipitation") or 0,
                boeen=r.get("wind_gust_speed") or 0,
                sonne_min=r.get("sunshine") or 0,
                schnee=(r.get("icon") in ("snow", "sleet")) or (r.get("condition") in ("snow", "sleet")),
            ))
        rec = kleidung.empfehlen(hours, sensitivity, monat=d.month, uv=uv)
        if rec is None:
            return None
        grund = rec.grund  # wann es regnet, steht in der Kopfzeile der Tageskurve
        until = f"Bis {hm(end)}" if end < day_end else "Bis Mitternacht"
        if d != now.date():
            until = f"Morgen {hm(start)}–{hm(end)}"
        # "Warm und regenfest anziehen" -> "Anziehen: warm und regenfest"
        title = rec.titel
        if title.endswith(" anziehen"):
            title = title[: -len(" anziehen")]
            title = title[:1].lower() + title[1:]
        # „4° kälter als gestern“ (seit 1.22): direkt hinter „gefühlt bis …“, darauf bezieht es sich.
        # Abends (Fokus morgen) ist der Vortag heute.
        diff = kleidung.vergleich(pairs)
        compare = None
        if diff is not None:
            compare = kleidung.vergleich_text(diff, "gestern" if d == now.date() else "heute")
            logger.info("Kleidung: %s (Fenster %s–%s)", compare, hm(start), hm(end))
        return {
            "title": title,
            "pieces": [{"svg": kleidung.ICONS.get(icon, ""), "text": text} for icon, text in rec.teile],
            "why": f"{until}: {grund}",
            # mit Vergleich in Teilen, damit fitWhy() hintere Gründe weglassen kann
            "why_head": f"{until}: {rec.gruende[0]}",
            "why_rest": rec.gruende[1:],
            "compare": compare,
            "reason_event": reason,
            "sensitivity": SENSITIVITY_LABEL.get(sensitivity, ""),
        }
