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
                   katze, pollen, meteore, finsternisse, planeten)
except ImportError:  # pragma: no cover
    from plugins.tagesdashboard import (kleidung, bahn, nachrichten, waesche, ansichten, nachtgrafik, anfahrt,
                                        festtage, radar, luft, katze, pollen, meteore, finsternisse, planeten)

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
CFG_VERSION = 18  # muss zu cfgVersion in settings.html passen (dev/test_settings.py prüft das)
WEEK_DAY = 6  # Wochenvorschau sonntags

# Das Nachtbild wird einmal gezeichnet und bis zum Ende der Nacht wiederverwendet
_NIGHT_CACHE = {}

# Außerhalb des Zug-Zeitfensters wird ein fertiges Bild wiederverwendet (siehe generate_image)
_IMAGE_CACHE = {}
SENSITIVITY_LABEL = {"normal": "normal", "empfindlich": "kälteempfindlich", "sehr": "sehr kälteempfindlich"}
GRAPH_START, GRAPH_END = 6, 24  # Tageskurve von 6 bis 24 Uhr
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
        # Nur mit Zug: Nur dafür muss InkyPi schneller laufen als sonst. Ohne Zug gilt allein das
        # Intervall der Playlist (ein Cache würde es sonst stillschweigend verlängern).
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
        night_win, week_win = window("night"), window("week")
        fest_cfg = festtage.read_config(opt, flag)
        fest_now = festtage.view(now, fest_cfg)
        mode = "normal"
        if fest_now:  # Festansicht geht Nachtbild und Wochenvorschau vor
            mode = "fest"
        elif night_win and ansichten.in_window(now, *night_win):
            mode = "night"
        elif week_win and ansichten.in_window(now, *week_win, weekday=WEEK_DAY):
            mode = "week"
        if mode != "normal":
            news_now = train_now = False  # Sonderansichten zeigen weder Nachrichten noch Live-Zug

        use_cache = bool(train_cfg) and not train_now
        cache_key = json.dumps([settings, list(dimensions)], sort_keys=True, default=str)
        if mode == "night" and flag("nightFreeze") and not self._manual_refresh():
            hit = _NIGHT_CACHE.get(cache_key)
            if hit and now < hit["until"]:
                logger.info("Nachtbild von %s wiederverwendet (bis %s)", hit["made"], hit["until"].strftime("%H:%M"))
                return hit["image"].copy()
        if use_cache and not self._manual_refresh():
            hit = _IMAGE_CACHE.get(cache_key)
            # 1 Minute Toleranz: Kommt InkyPi im eingestellten Takt, wird nie ein fälliges Bild ausgelassen
            if hit and now < hit["until"] - timedelta(minutes=1):
                logger.info("Zugfenster nicht aktiv – Bild von %s wiederverwendet", hit["made"])
                return hit["image"].copy()

        switch = self._opt(settings, "switchHour")
        focus = today + timedelta(days=1) if switch.isdigit() and now.hour >= int(switch) else today

        # ---- Kalender (darf ausfallen, dann nur Wetter) -------------------
        events, calendars, cal_error = [], [], None
        try:
            events, calendars = self.load_calendar(settings, device_config, tz, today, flag,
                                                   min_days=8 if mode == "week" else 0)
        except RuntimeError as exc:
            cal_error = str(exc)
            logger.warning("Kalender nicht verfügbar: %s", exc)

        # ---- Wetter (darf ausfallen, dann nur Kalender) ------------------
        weather, wx_error = None, None
        try:
            weather = self.load_weather(settings, tz, now, focus, flag, days=8 if mode == "week" else 2)
        except RuntimeError as exc:
            wx_error = str(exc)
            logger.warning("Wetter nicht verfügbar: %s", exc)

        if weather is None and cal_error:
            raise RuntimeError(f"Weder Wetter noch Kalender verfügbar. Wetter: {wx_error} Kalender: {cal_error}")

        use_colors = flag("useColors")
        for ev in events:
            ev["color"] = ev["cal_color"] if use_colors else "#000000"
            ev["fg"] = nc.contrast_color(ev["color"])

        records = weather["records"] if weather else []

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

        if laundry_win and records and waesche.in_window(now, *laundry_win):
            params["laundry"] = waesche.check(records, now, covered=flag("laundryCovered"))
        if news_now:
            params["news"] = nachrichten.load(news_cfg, now)
            params["news_sources"] = list(dict.fromkeys(it["source"] for g in params["news"] for it in g["items"]))
        if train_now:
            params["train"] = bahn.load(train_cfg, now, tz,
                                        client_id=device_config.load_env_key("DB_CLIENT_ID"),
                                        api_key=device_config.load_env_key("DB_API_KEY"))
        params["orientation"] = "portrait" if dimensions[1] > dimensions[0] else "landscape"
        if flag("catEnabled") and mode == "normal":
            try:
                params["cat"] = katze.choose(now, records, nowcast, weather=flag("catWeather"),
                                             feels_like=dwd.feels_like)
                logger.info("Katze: %s%s", params["cat"]["main"]["name"],
                            f" ({params['cat']['reason']})" if params["cat"]["reason"] else "")
            except Exception:  # Katze ist Zusatz: nie das ganze Bild verlieren
                logger.exception("Katze konnte nicht gewählt werden")
        if mode == "fest":
            self.fest_view(params, fest_now, now, tz, events, weather)
        elif mode != "normal":
            self.special_view(params, mode, now, tz, events, weather, train_cfg, cal_error,
                              art=flag("nightArt"), night_end=ansichten.window_end(now, *night_win) if night_win else None,
                              moon_cat=flag("catEnabled") and flag("catNight"), meteors=flag("meteorEnabled"),
                              eclipses=flag("eclipseEnabled"), planets=flag("planetEnabled"))

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
                                       "until": ansichten.window_end(now, *night_win)}
        if use_cache:
            # Bild höchstens quietMinutes lang wiederverwenden und nie über eine Fenstergrenze
            # hinweg (Zugfenster beginnt, Nachrichten erscheinen oder verschwinden).
            quiet = self._opt(settings, "quietMinutes")
            until = now + timedelta(minutes=int(quiet) if quiet.isdigit() else 30)
            edges = [bahn.next_window_start(now, train_cfg)] if train_cfg else []
            edges += nachrichten.boundaries(now, news_cfg) if news_cfg else []
            edges += waesche.boundaries(now, *laundry_win) if laundry_win else []
            edges += ansichten.boundaries(now, *night_win) if night_win else []
            edges += ansichten.boundaries(now, *week_win) if week_win else []
            edges += trips["edges"]  # Aufbruch-Karte erscheint bzw. verschwindet
            edges += festtage.boundaries(now, fest_cfg)  # Gruß und Festbild (u. a. Mitternacht an Silvester)
            for edge in edges:
                if edge and now < edge < until:
                    until = edge
            _IMAGE_CACHE.clear()  # nur ein Bild merken (Speicher auf dem Pi Zero)
            _IMAGE_CACHE[cache_key] = {"image": image.copy(), "until": until, "made": now.strftime("%H:%M")}
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
    # Nachtbild und Wochenvorschau
    # ==================================================================
    def special_view(self, params, mode, now, tz, events, weather, train_cfg, cal_error, art=False, night_end=None,
                     moon_cat=False, meteors=False, eclipses=False, planets=False):
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
                params["night"]["art"] = {
                    "svg": nachtgrafik.svg(now, wx, width=480 if params["orientation"] == "portrait" else 800,
                                           cat=katze.on_moon if moon_cat else None, meteors=streaks,
                                           blood_moon=blood, planet=planet_dot),
                    "weather": nachtgrafik.describe(wx),
                    "daylight": nachtgrafik.daylight(weather["sun_cache"], d) if weather else "",
                    "meteors": meteor_info["text"] if meteor_info else "",
                    "eclipse": eclipse_info["text"] if eclipse_info else "",
                    "planet": planet_info["text"] if planet_info else "",
                }
        else:
            portrait = params["orientation"] == "portrait"
            params["week"] = ansichten.week(now, records if w else [], items_on, w, dwd, icons, train_cfg,
                                            per_row=4 if portrait else 3)
        params["view_error"] = cal_error or params.get("wx_error")

    # ==================================================================
    # Kalender
    # ==================================================================
    def load_calendar(self, settings, device_config, tz, today, flag, min_days=0):
        user = (settings.get("username") or "").strip()
        url = (settings.get("nextcloudUrl") or "").strip()
        if not user or not url:
            raise RuntimeError("Nextcloud-Adresse oder Benutzername fehlt.")
        key = (settings.get("passwordKey") or "NEXTCLOUD_APP_PASSWORD").strip()
        password = device_config.load_env_key(key)
        if not password:
            raise RuntimeError(f"App-Passwort fehlt (API Keys → {key}).")

        days = int(self._opt(settings, "calendarDays")) if self._opt(settings, "calendarDays").isdigit() else 7
        start = datetime.combine(today, time.min, tz)
        end = start + timedelta(days=max(days, 2, min_days) + 1)

        client = nc.CalDavClient(nc.dav_root(url), user, password, verify=flag("verifySSL"))
        helper = nc.NextcloudKalender({"id": "nextcloud_kalender"})
        calendars = helper.select_calendars(client.calendars(), settings.get("calendars", ""))
        events = []
        for cal in calendars:
            try:
                for ics in client.events(cal["url"], start, end):
                    events.extend(helper.parse_events(ics, cal, tz, start, end))
            except RuntimeError as exc:
                logger.warning("Kalender %s nicht lesbar: %s", cal["name"], exc)
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
            return None
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
        rain, nights = [], []
        for i, r in enumerate(pts):
            amount = r.get("precipitation") or 0
            if amount >= 0.05:
                level = next(name for limit, name in RAIN_LEVELS if amount < limit)
                h = 100 * max(min(amount / RAIN_SCALE, 1.0), 0.28)  # auch Niesel bleibt sichtbar
                rain.append({"x": f"{i * slot + slot * 0.08:.1f}", "w": f"{slot * 0.84:.1f}",
                             "y": f"{100 - h:.1f}", "h": f"{h:.1f}", "cls": level})
            sr, ss = sun_cache(r["dt"].date())
            if sr and ss and not (sr <= r["dt"] < ss):
                nights.append({"x": f"{i * slot:.1f}", "w": f"{slot + 0.6:.1f}"})
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
        return {"line": line, "nights": nights, "icons": gicons, "xlabels": xlabels,
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

        hours = []
        for r in records:
            if not (start <= r["dt"] <= end + timedelta(minutes=59)) or r.get("temperature") is None:
                continue
            gef = dwd.feels_like(r["temperature"], r.get("wind_speed"), r.get("relative_humidity"))
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
        return {
            "title": title,
            "pieces": [{"svg": kleidung.ICONS.get(icon, ""), "text": text} for icon, text in rec.teile],
            "why": f"{until}: {grund}",
            "reason_event": reason,
            "sensitivity": SENSITIVITY_LABEL.get(sensitivity, ""),
        }
