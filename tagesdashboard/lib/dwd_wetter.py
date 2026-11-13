"""
DWD Wetter – InkyPi-Plugin

Zeigt Wetter auf Deutsch mit Daten des Deutschen Wetterdienstes (DWD) an.
Die Daten kommen über Bright Sky (https://brightsky.dev), eine freie JSON-API,
die die offenen DWD-Daten aufbereitet – kein API-Key nötig.

Verwendete Endpunkte:
  /current_weather  aktuelle Messwerte der nächstgelegenen DWD-Station (SYNOP)
  /weather          stündliche Werte: Beobachtungen + MOSMIX-Vorhersage
  /alerts           amtliche DWD-Unwetterwarnungen für die Warnzelle des Orts
"""

import logging
import math
from collections import Counter
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo

import requests

from plugins.base_plugin.base_plugin import BasePlugin

try:  # Schärfere Darstellung auf Inky-Displays (Kopie von shared/eink.py)
    from . import eink
except ImportError:  # pragma: no cover
    eink = None

try:  # Seite immer als UTF-8 rendern (Kopie von shared/zeichensatz.py)
    from . import zeichensatz
except ImportError:  # pragma: no cover
    zeichensatz = None

try:  # relativer Import, damit der Ordnername frei bleibt
    from . import dwd_icons as icons
except ImportError:  # pragma: no cover - Fallback, falls ohne Paketkontext geladen
    import importlib.util
    import os

    _spec = importlib.util.spec_from_file_location(
        "dwd_icons", os.path.join(os.path.dirname(__file__), "dwd_icons.py")
    )
    icons = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(icons)

try:
    from astral import Observer
    from astral.sun import sun as astral_sun
except ImportError:  # astral ist eine InkyPi-Abhängigkeit, aber sicher ist sicher
    Observer = None
    astral_sun = None

logger = logging.getLogger(__name__)

API_BASE = "https://api.brightsky.dev"
HTTP_TIMEOUT = 20
USER_AGENT = "InkyPi-DWD-Wetter/1.0 (+https://github.com/fatihak/InkyPi)"

WOCHENTAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
WOCHENTAGE_KURZ = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
          "August", "September", "Oktober", "November", "Dezember"]
HIMMELSRICHTUNGEN = ["N", "NO", "O", "SO", "S", "SW", "W", "NW"]
BEAUFORT_GRENZEN = [1, 6, 12, 20, 29, 39, 50, 62, 75, 89, 103, 118]  # km/h

# DWD-Warnstufen: Hintergrund, Textfarbe, Bezeichnung, Rang, Rahmenfarbe.
# Spectra-6-Displays haben kein Orange. Statt einer orangefarbenen Fläche (würde als
# Rot-Gelb-Schachbrett die Schrift unruhig machen) bekommt die markante Warnung einen
# gelben Grund mit dickem orangem Rahmen.
WARNSTUFEN = {
    "minor": ("#FFE500", "#000000", "Wetterwarnung", 1, "#000000"),
    "moderate": ("#FFE500", "#000000", "Markante Wetterwarnung", 2, "#FF8C00"),
    "severe": ("#E3001B", "#FFFFFF", "Unwetterwarnung", 3, "#000000"),
    "extreme": ("#8B0A50", "#FFFFFF", "Extremes Unwetter", 4, "#000000"),
}

# Messwert-Kacheln: Schlüssel -> (Einstellungsname, Standard an/aus)
TILES = [
    ("wind", True),
    ("gust", True),
    ("humidity", True),
    ("pressure", False),
    ("precip", True),
    ("sunshine", True),
    ("sun", True),
    ("visibility", False),
    ("dewpoint", False),
    ("cloudcover", False),
]

DEFAULTS = {
    "showAlerts": "true",
    "showMetrics": "true",
    "showGraph": "true",
    "showForecast": "true",
    "showFooter": "true",
    "einkSnap": "true",
    "nightShading": "true",
    "graphIcons": "true",
    "hourlyHours": "24",
    "forecastDays": "5",
}
for _key, _on in TILES:
    DEFAULTS[f"tile_{_key}"] = "true" if _on else "false"

# Format der gespeicherten Einstellungen (verstecktes Feld cfgVersion in settings.html).
#   0 = sehr alte Einstellungen ohne cfgVersion (fehlender Schlüssel = Standardwert)
#   1 = bis 1.7: Titel über titleSelection ("auto"/"custom") + customTitle
#   2 = seit 1.10: nur customTitle, leer = Ortsname vom DWD
CFG_VERSION = 2
# Ab welcher cfgVersion es eine Checkbox gibt. Ist die gespeicherte Version älter, gilt für sie der
# Standardwert statt "fehlt = aus" (Gegenstück in settings.html: data-since). Bisher keine.
SINCE_VERSION = {}


def cfg_version(settings):
    raw = settings.get("cfgVersion")
    if raw is None:
        return 0
    try:
        return max(int(str(raw).strip()), 1)
    except ValueError:
        return 1


def migrate_settings(settings):
    """Bringt gespeicherte Einstellungen älterer Versionen ins aktuelle Format.

    Gibt eine Kopie zurück und ändert InkyPis gespeicherte Daten nicht: Beim nächsten Speichern
    schreibt die Einstellungsseite das neue Format selbst. Gleiche Regeln wie migrate() in settings.html.
    """
    s = dict(settings or {})
    if cfg_version(s) < 2:
        # Früher galt ein eingetippter Titel nur, wenn "Eigener Titel" gewählt war (Standard: "auto").
        if s.get("titleSelection", "auto") != "custom":
            s["customTitle"] = ""
        s.pop("titleSelection", None)
    return s


# --------------------------------------------------------------------------
# Hilfsfunktionen
# --------------------------------------------------------------------------

def de_num(value, decimals=0):
    """Zahl im deutschen Format (Komma als Dezimaltrennzeichen)."""
    if value is None:
        return "–"
    if decimals == 0:
        text = str(int(round(value)))
        return "0" if text == "-0" else text
    return f"{value:.{decimals}f}".replace(".", ",")


def first_value(record, *keys):
    for key in keys:
        val = record.get(key)
        if val is not None:
            return val
    return None


def compass(deg):
    if deg is None:
        return ""
    return HIMMELSRICHTUNGEN[int(((deg % 360) + 22.5) // 45) % 8]


def beaufort(kmh):
    if kmh is None:
        return None
    for bft, limit in enumerate(BEAUFORT_GRENZEN):
        if kmh < limit:
            return bft
    return 12


def feels_like(temp, wind_kmh, humidity):
    """Gefühlte Temperatur: Windchill (kalt) bzw. Hitzeindex (warm)."""
    if temp is None:
        return None
    if temp <= 10 and wind_kmh is not None and wind_kmh > 4.8:
        v = wind_kmh ** 0.16
        return 13.12 + 0.6215 * temp - 11.37 * v + 0.3965 * temp * v
    if temp >= 26.7 and humidity is not None and humidity >= 40:
        t = temp * 9 / 5 + 32
        rh = humidity
        hi = (-42.379 + 2.04901523 * t + 10.14333127 * rh - 0.22475541 * t * rh
              - 0.00683783 * t * t - 0.05481717 * rh * rh + 0.00122874 * t * t * rh
              + 0.00085282 * t * rh * rh - 0.00000199 * t * t * rh * rh)
        return (hi - 32) * 5 / 9
    return temp


def cloud_text(cloud_cover, is_day):
    """DWD-Bewölkungsbegriffe nach Achteln."""
    if cloud_cover is None:
        return "Bewölkt"
    okta = cloud_cover / 12.5
    if okta < 1:
        return "Sonnig" if is_day else "Klar"
    if okta < 3.5:
        return "Heiter"
    if okta < 6.5:
        return "Wolkig"
    if okta < 7.5:
        return "Stark bewölkt"
    return "Bedeckt"


def refine_icon(icon, precip, cloud_cover, is_day):
    """Bright-Sky-Icon um Intensität und Schauer-Varianten verfeinern."""
    if not icon:
        icon = "cloudy"
    if icon == "rain":
        if precip is not None and precip >= 4:
            return "heavy-rain"
        if cloud_cover is not None and cloud_cover < 70:
            return "showers-day" if is_day else "showers-night"
        if precip is not None and 0 < precip < 0.3:
            return "drizzle"
    if icon in ("clear-day", "clear-night"):
        return "clear-day" if is_day else "clear-night"
    if icon in ("partly-cloudy-day", "partly-cloudy-night"):
        return "partly-cloudy-day" if is_day else "partly-cloudy-night"
    return icon


def condition_text(icon, precip, cloud_cover, is_day):
    if icon in ("clear-day", "clear-night", "partly-cloudy-day", "partly-cloudy-night", "cloudy"):
        return cloud_text(cloud_cover, is_day)
    if icon == "fog":
        return "Nebel"
    if icon == "wind":
        return "Windig"
    if icon in ("showers-day", "showers-night"):
        return "Regenschauer"
    if icon in ("rain", "drizzle", "heavy-rain"):
        if precip is None:
            return "Regen"
        if precip < 0.5:
            return "Leichter Regen"
        if precip < 4:
            return "Regen"
        return "Starker Regen"
    if icon == "sleet":
        return "Schneeregen"
    if icon == "snow":
        if precip is not None and precip >= 2:
            return "Starker Schneefall"
        if precip is not None and precip < 0.3:
            return "Leichter Schneefall"
        return "Schneefall"
    if icon == "hail":
        return "Hagel"
    if icon == "thunderstorm":
        return "Gewitter"
    return ""


def parse_ts(value, tz):
    return datetime.fromisoformat(value).astimezone(tz)


def short_place_name(name):
    if not name:
        return ""
    for prefix in ("Kreisfreie Stadt ", "Stadt ", "Gemeinde ", "Landkreis ", "Kreis ", "Region "):
        if name.startswith(prefix):
            return name[len(prefix):]
    return name


KLEINWOERTER = {"mit", "und", "oder", "vor", "von", "im", "in", "bis", "über", "unter", "auf", "an", "der", "die", "das"}


def event_title(text):
    """'SCHWERES GEWITTER mit ORKANBÖEN' -> 'Schweres Gewitter mit Orkanböen'."""
    words = (text or "").split()
    out = []
    for i, w in enumerate(words):
        low = w.lower()
        out.append(low if (i > 0 and low in KLEINWOERTER) else low[:1].upper() + low[1:])
    return " ".join(out)


def arrow_svg(rotation, cls="trend-arrow"):
    return (
        f'<svg class="{cls}" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
        f'<g transform="rotate({rotation} 16 16)"><path d="M16 4 L26 20 H19 V28 H13 V20 H6 Z" '
        f'fill="currentColor"/></g></svg>'
    )


# --------------------------------------------------------------------------
# Plugin
# --------------------------------------------------------------------------

class DwdWetter(BasePlugin):

    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params["style_settings"] = True
        template_params["tiles"] = [
            {"key": key, "label": label, "default": on}
            for (key, on), label in zip(TILES, [
                "Wind", "Böen", "Luftfeuchte", "Luftdruck", "Niederschlag heute",
                "Sonnenstunden heute", "Sonnenauf- und -untergang", "Sichtweite",
                "Taupunkt", "Bewölkung",
            ])
        ]
        return template_params

    # ------------------------------------------------------------------
    def generate_image(self, settings, device_config):
        settings = migrate_settings(settings)
        opts = self._options(settings)

        raw_lat = str(settings.get("latitude", "")).strip().replace(",", ".")
        raw_lon = str(settings.get("longitude", "")).strip().replace(",", ".")
        if not raw_lat or not raw_lon:
            raise RuntimeError("Bitte einen Ort (Breiten- und Längengrad) angeben.")
        try:
            lat, lon = float(raw_lat), float(raw_lon)
        except ValueError:
            raise RuntimeError("Breiten- und Längengrad müssen Zahlen sein.")

        tz_name = device_config.get_config("timezone", default="Europe/Berlin") or "Europe/Berlin"
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = ZoneInfo("Europe/Berlin")
        now = self.current_time(tz)

        data = self.fetch_data(lat, lon, tz, now, opts)
        params = self.build_template_params(data, lat, lon, tz, now, opts, settings)

        dimensions = device_config.get_resolution()
        if device_config.get_config("orientation") == "vertical":
            dimensions = dimensions[::-1]
        params["orientation"] = "portrait" if dimensions[1] > dimensions[0] else "landscape"
        # Querformat mit Warnzeile: Kopfbereich flacher, sonst bleibt der Graph zu niedrig
        params["tight"] = bool(params.get("alerts")) and params["orientation"] == "landscape"
        # Schmale Vorhersagespalten (z. B. 7 Tage im Hochformat) kompakter darstellen
        params["fc_compact"] = dimensions[0] / max(len(params["forecast"]), 1) < 125
        params["plugin_settings"] = settings

        if zeichensatz is not None:
            zeichensatz.utf8_templates(self)  # sonst rät Chromium den Zeichensatz
        image = self.render_image(dimensions, "dwd_wetter.html", "dwd_wetter.css", params)
        if not image:
            raise RuntimeError("Bild konnte nicht erzeugt werden – siehe Logs.")
        if eink is not None:
            image = eink.prepare(image, device_config, enabled=opts["eink"])
        return image

    def current_time(self, tz):
        """Eigene Methode, damit Tests eine feste Uhrzeit einsetzen können."""
        return datetime.now(tz)

    # ------------------------------------------------------------------
    def _options(self, settings):
        version = cfg_version(settings)

        def flag(key):
            # Gespeicherte Einstellungen: fehlende Checkbox = aus – außer die Checkbox ist neuer als die Einstellungen
            if version >= max(SINCE_VERSION.get(key, 1), 1):
                return settings.get(key) == "true"
            return settings.get(key, DEFAULTS[key]) == "true"

        def number(key, allowed):
            try:
                val = int(settings.get(key, DEFAULTS[key]))
            except (TypeError, ValueError):
                val = int(DEFAULTS[key])
            return val if val in allowed else int(DEFAULTS[key])

        return {
            "show_alerts": flag("showAlerts"),
            "show_metrics": flag("showMetrics"),
            "show_graph": flag("showGraph"),
            "show_forecast": flag("showForecast"),
            "show_footer": flag("showFooter"),
            "eink": flag("einkSnap"),
            "night_shading": flag("nightShading"),
            "graph_icons": flag("graphIcons"),
            "hours": number("hourlyHours", (12, 24, 36, 48)),
            "days": number("forecastDays", (3, 4, 5, 6, 7)),
            "tiles": [key for key, _ in TILES if flag(f"tile_{key}")],
        }

    # ------------------------------------------------------------------
    # Datenabruf
    # ------------------------------------------------------------------
    def _get(self, session, path, params):
        url = f"{API_BASE}{path}"
        response = session.get(url, params=params, timeout=HTTP_TIMEOUT)
        if not 200 <= response.status_code < 300:
            logger.error("Bright Sky %s antwortete mit %s: %s", path, response.status_code, response.text[:300])
            raise RuntimeError(f"Bright Sky {path}: HTTP {response.status_code}")
        return response.json()

    def fetch_data(self, lat, lon, tz, now, opts):
        session = requests.Session()
        session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
        tz_param = getattr(tz, "key", "Europe/Berlin")

        today = now.date()
        start = datetime.combine(today, datetime.min.time(), tz) - timedelta(hours=3)
        end = datetime.combine(today + timedelta(days=opts["days"] + 1), datetime.min.time(), tz) + timedelta(hours=1)
        end = max(end, now + timedelta(hours=opts["hours"] + 2))

        try:
            hourly = self._get(session, "/weather", {
                "lat": lat, "lon": lon, "tz": tz_param,
                "date": start.isoformat(timespec="minutes"),
                "last_date": end.isoformat(timespec="minutes"),
            })
        except Exception as exc:
            logger.exception("Stündliche DWD-Daten konnten nicht geladen werden")
            raise RuntimeError("DWD-Vorhersage konnte nicht geladen werden – Internetverbindung prüfen.") from exc

        try:
            current = self._get(session, "/current_weather", {"lat": lat, "lon": lon, "tz": tz_param})
        except Exception:
            logger.warning("Aktuelle Messwerte nicht verfügbar – nutze Vorhersage als Ersatz", exc_info=True)
            current = {}

        # Warnungen immer abfragen: die Warnzelle liefert auch den Ortsnamen für den Titel
        alerts = {}
        try:
            alerts = self._get(session, "/alerts", {"lat": lat, "lon": lon, "tz": tz_param})
        except Exception:
            logger.warning("DWD-Warnungen nicht verfügbar", exc_info=True)

        return {"hourly": hourly, "current": current, "alerts": alerts}

    # ------------------------------------------------------------------
    # Aufbereitung
    # ------------------------------------------------------------------
    def sun_times(self, lat, lon, day, tz):
        if astral_sun is None:
            return None, None
        try:
            s = astral_sun(Observer(latitude=lat, longitude=lon), date=day, tzinfo=tz)
            return s["sunrise"], s["sunset"]
        except Exception:  # Polartag/-nacht
            return None, None

    def is_day(self, dt, sun_cache):
        sunrise, sunset = sun_cache(dt.date())
        if sunrise is None or sunset is None:
            return 6 <= dt.hour < 18
        return sunrise <= dt < sunset

    def build_template_params(self, data, lat, lon, tz, now, opts, settings):
        cache = {}

        def sun_cache(d):
            if d not in cache:
                cache[d] = self.sun_times(lat, lon, d, tz)
            return cache[d]

        # ---- stündliche Datensätze -------------------------------------
        records = []
        for rec in (data["hourly"] or {}).get("weather", []):
            try:
                rec = dict(rec)
                rec["dt"] = parse_ts(rec["timestamp"], tz)
                records.append(rec)
            except (KeyError, ValueError):
                continue
        records.sort(key=lambda r: r["dt"])
        if not records:
            raise RuntimeError("Keine DWD-Daten für diesen Ort – liegt er in bzw. nahe Deutschland?")

        by_day = {}
        for rec in records:
            by_day.setdefault(rec["dt"].date(), []).append(rec)

        nearest = min(records, key=lambda r: abs((r["dt"] - now).total_seconds()))

        # ---- aktuelle Werte --------------------------------------------
        cur = (data.get("current") or {}).get("weather") or {}

        def cval(*keys, fallback=None):
            val = first_value(cur, *keys)
            if val is None and fallback:
                val = nearest.get(fallback)
            return val

        temp = cval("temperature", fallback="temperature")
        humidity = cval("relative_humidity", fallback="relative_humidity")
        wind = cval("wind_speed_10", "wind_speed_30", "wind_speed_60", fallback="wind_speed")
        wind_dir = cval("wind_direction_10", "wind_direction_30", "wind_direction_60", fallback="wind_direction")
        gust = cval("wind_gust_speed_10", "wind_gust_speed_30", "wind_gust_speed_60", fallback="wind_gust_speed")
        pressure = cval("pressure_msl", fallback="pressure_msl")
        visibility = cval("visibility", fallback="visibility")
        dew = cval("dew_point", fallback="dew_point")
        cloud = cval("cloud_cover", fallback="cloud_cover")
        precip_now = cval("precipitation_60", "precipitation_30", fallback="precipitation")
        day_now = self.is_day(now, sun_cache)
        cur_icon = refine_icon(cval("icon", fallback="icon"), precip_now, cloud, day_now)

        # Luftdrucktendenz der letzten 3 Stunden
        pressure_trend = None
        past = [r for r in records if r.get("pressure_msl") is not None
                and timedelta(hours=2.5) <= now - r["dt"] <= timedelta(hours=3.5)]
        if pressure is not None and past:
            diff = pressure - past[0]["pressure_msl"]
            pressure_trend = 45 if diff >= 1 else (135 if diff <= -1 else 90)

        # ---- Tageswerte -------------------------------------------------
        def summarize(day, recs):
            temps = [r["temperature"] for r in recs if r.get("temperature") is not None]
            precip = sum(r.get("precipitation") or 0 for r in recs)
            probs = [r["precipitation_probability"] for r in recs if r.get("precipitation_probability") is not None]
            sunshine = sum(r.get("sunshine") or 0 for r in recs) / 60
            gusts = [r["wind_gust_speed"] for r in recs if r.get("wind_gust_speed") is not None]
            return {
                "date": day,
                "tmax": max(temps) if temps else None,
                "tmin": min(temps) if temps else None,
                "precip": precip,
                "prob": max(probs) if probs else None,
                "sunshine": sunshine,
                "gust": max(gusts) if gusts else None,
                "icon": self.day_icon(recs),
                "complete": len(recs) >= 20,
            }

        today = now.date()
        today_sum = summarize(today, by_day.get(today, [nearest]))

        forecast = []
        for i in range(1, opts["days"] + 1):
            d = today + timedelta(days=i)
            recs = by_day.get(d)
            if not recs:
                continue
            s = summarize(d, recs)
            forecast.append({
                "name": WOCHENTAGE_KURZ[d.weekday()],
                "date": f"{d.day}.{d.month}.",
                "icon": icons.weather_icon(s["icon"], "fc-icon"),
                "tmax": de_num(s["tmax"]),
                "tmin": de_num(s["tmin"]),
                "precip": de_num(s["precip"], 1) if s["precip"] >= 0.05 else "0",
                "prob": de_num(s["prob"]) if s["prob"] is not None else None,
                "sunshine": de_num(s["sunshine"], 0 if s["sunshine"] >= 9.5 else 1) if s["sunshine"] else "0",
                "weekend": d.weekday() >= 5,
            })

        # ---- Kacheln ----------------------------------------------------
        sunrise, sunset = sun_cache(today)
        ctx = {
            "wind": wind, "wind_dir": wind_dir, "gust": gust, "humidity": humidity,
            "pressure": pressure, "pressure_trend": pressure_trend, "visibility": visibility,
            "dew": dew, "cloud": cloud, "today_sum": today_sum, "sunrise": sunrise, "sunset": sunset,
        }
        tiles = [t for t in (self.make_tile(key, ctx) for key in opts["tiles"]) if t]

        # ---- Warnungen --------------------------------------------------
        alerts_data = data.get("alerts") or {}
        alerts = self.parse_alerts(alerts_data.get("alerts") or [], tz, now) if opts["show_alerts"] else []

        # ---- Titel & Quelle --------------------------------------------
        location = alerts_data.get("location") or {}
        sources = (data.get("current") or {}).get("sources") or (data["hourly"] or {}).get("sources") or []
        station = None
        if sources:
            src_id = cur.get("source_id") or nearest.get("source_id")
            station = next((s for s in sources if s.get("id") == src_id), sources[0])

        custom_title = (settings.get("customTitle") or "").strip()   # Format nach migrate_settings()
        if custom_title:
            title = custom_title
        else:
            title = (location.get("name_short") or short_place_name(location.get("name"))
                     or (station or {}).get("station_name", "").title() or "Wetter")

        station_text = ""
        if station:
            name = (station.get("station_name") or "").title()
            dist = station.get("distance")
            station_text = name + (f" ({de_num(dist / 1000)} km)" if dist is not None else "")

        # ---- Stundenverlauf --------------------------------------------
        graph = self.build_graph(records, now, opts, sun_cache) if opts["show_graph"] else None

        feels = feels_like(temp, wind, humidity)
        return {
            "title": title,
            "date_str": f"{WOCHENTAGE[now.weekday()]}, {now.day}. {MONATE[now.month - 1]}",
            "updated": now.strftime("%H:%M"),
            "current": {
                "icon": icons.weather_icon(cur_icon, "cur-icon"),
                "temp": de_num(temp),
                "text": condition_text(cur_icon, precip_now, cloud, day_now),
                "feels": de_num(feels) if feels is not None else None,
                "show_feels": feels is not None and temp is not None and abs(feels - temp) >= 1,
                "tmax": de_num(today_sum["tmax"]),
                "tmin": de_num(today_sum["tmin"]),
            },
            "tiles": tiles,
            "tile_cols": self.tile_columns(len(tiles)),
            "tile_dense": len(tiles) > 6,  # mehr als 2 Reihen: kompakter, damit der Graph Platz behält
            "tile_rows": max(1, math.ceil(len(tiles) / self.tile_columns(len(tiles)))),
            "alerts": alerts[:1],
            "alerts_more": max(len(alerts) - 1, 0),
            "graph": graph,
            "forecast": forecast,
            "station": station_text,
            "opts": opts,
            "icon_up": arrow_svg(0, "mini-arrow"),
            "icon_down": arrow_svg(180, "mini-arrow"),
            "icon_umbrella": icons.metric_icon("precip", "fc-mini"),
            "icon_sun": icons.metric_icon("sunshine", "fc-mini"),
        }

    # ------------------------------------------------------------------
    def tile_columns(self, n):
        return 2 if n <= 4 else 3

    def make_tile(self, key, ctx):
        mi = icons.metric_icon
        if key == "wind":
            bft = beaufort(ctx["wind"])
            extra = ""
            if ctx["wind_dir"] is not None and (ctx["wind"] or 0) >= 1:
                extra = icons.wind_arrow(ctx["wind_dir"], "tile-arrow") + f'<span>{compass(ctx["wind_dir"])}</span>'
            return {"icon": mi("wind"), "label": f"Wind · Bft {bft}" if bft is not None else "Wind",
                    "value": de_num(ctx["wind"]), "unit": "km/h", "extra": extra}
        if key == "gust":
            return {"icon": mi("gust"), "label": "Böen", "value": de_num(ctx["gust"]), "unit": "km/h"}
        if key == "humidity":
            return {"icon": mi("humidity"), "label": "Luftfeuchte", "value": de_num(ctx["humidity"]), "unit": "%"}
        if key == "pressure":
            extra = arrow_svg(ctx["pressure_trend"], "tile-arrow") if ctx["pressure_trend"] is not None else ""
            return {"icon": mi("pressure"), "label": "Luftdruck", "value": de_num(ctx["pressure"]),
                    "unit": "hPa", "extra": extra}
        if key == "precip":
            s = ctx["today_sum"]
            extra = f'<span>{de_num(s["prob"])} %</span>' if s["prob"] is not None else ""
            return {"icon": mi("precip"), "label": "Regen heute", "value": de_num(s["precip"], 1),
                    "unit": "mm", "extra": extra}
        if key == "sunshine":
            return {"icon": mi("sunshine"), "label": "Sonne heute",
                    "value": de_num(ctx["today_sum"]["sunshine"], 1), "unit": "h"}
        if key == "sun":
            sr, ss = ctx["sunrise"], ctx["sunset"]
            if sr is None or ss is None:
                return None
            return {"icon": mi("sun_times"), "label": "Tageslicht",
                    "value": f'{sr.hour}:{sr.minute:02d}<span class="sep">–</span>{ss.hour}:{ss.minute:02d}',
                    "unit": "", "raw": True}
        if key == "visibility":
            vis = ctx["visibility"]
            if vis is None:
                value = "–"
            elif vis < 1000:
                return {"icon": mi("visibility"), "label": "Sichtweite", "value": de_num(vis), "unit": "m"}
            else:
                value = de_num(vis / 1000, 1 if vis < 10000 else 0)
            return {"icon": mi("visibility"), "label": "Sichtweite", "value": value, "unit": "km"}
        if key == "dewpoint":
            return {"icon": mi("dewpoint"), "label": "Taupunkt", "value": de_num(ctx["dew"]), "unit": "°C"}
        if key == "cloudcover":
            return {"icon": mi("cloudcover"), "label": "Bewölkung", "value": de_num(ctx["cloud"]), "unit": "%"}
        return None

    # ------------------------------------------------------------------
    def day_icon(self, recs):
        """Ein repräsentatives Symbol für einen Tag (Tagstunden 7–19 Uhr)."""
        daytime = [r for r in recs if 7 <= r["dt"].hour <= 19] or recs
        n = len(daytime)
        counts = Counter((r.get("icon") or "") for r in daytime)
        precip = sum(r.get("precipitation") or 0 for r in daytime)
        clouds = [r["cloud_cover"] for r in daytime if r.get("cloud_cover") is not None]
        mean_cloud = sum(clouds) / len(clouds) if clouds else 50

        if counts["thunderstorm"] >= 1:
            return "thunderstorm"
        wet = {k: counts[k] for k in ("snow", "sleet", "hail", "rain")}
        wet_hours = sum(wet.values())
        if wet_hours >= 2 or precip >= 1.0:
            priority = {"hail": 3, "snow": 2, "sleet": 1, "rain": 0}
            kind = max(wet, key=lambda k: (wet[k], priority[k])) if wet_hours else "rain"
            if kind == "rain":
                if precip >= 15:
                    return "heavy-rain"
                if wet_hours <= n / 3 and mean_cloud < 80:
                    return "showers-day"
                return "rain"
            return kind
        if counts["fog"] >= n / 2:
            return "fog"
        if counts["wind"] >= 3:
            return "wind"
        if mean_cloud < 20:
            return "clear-day"
        if mean_cloud < 70:
            return "partly-cloudy-day"
        return "cloudy"

    # ------------------------------------------------------------------
    def parse_alerts(self, raw_alerts, tz, now):
        alerts = []
        for a in raw_alerts:
            if a.get("status") not in (None, "actual"):
                continue
            onset = parse_ts(a["onset"], tz) if a.get("onset") else None
            expires = parse_ts(a["expires"], tz) if a.get("expires") else None
            if expires and expires < now:
                continue
            bg, fg, level, rank, border = WARNSTUFEN.get(a.get("severity"), WARNSTUFEN["minor"])

            def fmt(dt):
                if dt.date() == now.date():
                    return dt.strftime("%H:%M")
                return f"{WOCHENTAGE_KURZ[dt.weekday()]} {dt.strftime('%H:%M')}"

            if onset and onset > now:
                when = f"{fmt(onset)} – {fmt(expires)}" if expires else f"ab {fmt(onset)}"
            else:
                when = f"bis {fmt(expires)}" if expires else "aktuell"

            headline = a.get("headline_de") or a.get("event_de") or level
            alerts.append({
                "headline": headline,
                "event": event_title(a.get("event_de")),
                "level": level,
                "when": when,
                "bg": bg,
                "fg": fg,
                "border": border,
                "rank": rank,
                "onset": onset or now,
                "icon": icons.warning_icon(border if rank == 2 else (bg if rank < 3 else "#FFFFFF"), "#000000", "warn-icon"),
            })
        alerts.sort(key=lambda x: (-x["rank"], x["onset"]))
        # Doppelte Meldungen (gleiche Überschrift) zusammenfassen
        seen, unique = set(), []
        for a in alerts:
            if a["headline"] in seen:
                continue
            seen.add(a["headline"])
            unique.append(a)
        return unique

    # ------------------------------------------------------------------
    def build_graph(self, records, now, opts, sun_cache):
        start = now.replace(minute=0, second=0, microsecond=0)
        pts = [r for r in records if r["dt"] >= start and r.get("temperature") is not None][: opts["hours"] + 1]
        if len(pts) < 3:
            return None
        n = len(pts)
        W, H = 1000.0, 300.0
        slot = W / n

        temps = [r["temperature"] for r in pts]
        tmax, tmin = max(temps), min(temps)
        span = max(tmax - tmin, 4.0)
        mid = (tmax + tmin) / 2
        lo, hi = mid - span / 2, mid + span / 2
        top, bottom = 0.32, 0.68  # Temperaturkurve nutzt diesen Höhenbereich

        def x(i):
            return (i + 0.5) * slot

        def y(t):
            return H * (top + (hi - t) / (hi - lo) * (bottom - top))

        # Glatte Kurve (Catmull-Rom -> Bézier)
        P = [(x(i), y(t)) for i, t in enumerate(temps)]
        d = f"M{P[0][0]:.1f},{P[0][1]:.1f}"
        for i in range(len(P) - 1):
            p0 = P[i - 1] if i > 0 else P[i]
            p1, p2 = P[i], P[i + 1]
            p3 = P[i + 2] if i + 2 < len(P) else p2
            c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
            c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
            d += f" C{c1[0]:.1f},{c1[1]:.1f} {c2[0]:.1f},{c2[1]:.1f} {p2[0]:.1f},{p2[1]:.1f}"
        area = d + f" L{P[-1][0]:.1f},{H:.1f} L{P[0][0]:.1f},{H:.1f} Z"

        bars, nights, rain_labels = [], [], []
        last_label = -9
        for i, r in enumerate(pts):
            prob = r.get("precipitation_probability")
            if prob is None:
                prob = 100 if (r.get("precipitation") or 0) >= 0.1 else 0
            if prob > 10:
                h = H * 0.92 * prob / 100
                bx, bw = i * slot + slot * 0.12, slot * 0.76
                bars.append({"x": f"{bx:.1f}", "x2": f"{bx + bw:.1f}", "y": f"{H - h:.1f}",
                             "w": f"{bw:.1f}", "h": f"{h:.1f}"})
            if opts["night_shading"] and not self.is_day(r["dt"], sun_cache):
                nights.append({"x": f"{i * slot:.1f}", "w": f"{slot + 0.6:.1f}"})
            amount = r.get("precipitation") or 0
            min_gap = 1 if n <= 25 else 2
            if amount >= 0.1 and i - last_label > min_gap:
                rain_labels.append({"left": f"{(i + 0.5) / n * 100:.2f}", "text": de_num(amount, 1)})
                last_label = i

        if n <= 13:
            step = 2
        elif n <= 25:
            step = 3
        elif n <= 37:
            step = 4
        else:
            step = 6
        xlabels, gicons = [], []
        for i, r in enumerate(pts):
            dt = r["dt"]
            if i == 0 or (dt.hour % step == 0 and i < n - 1 and i >= step * 0.75):
                left = f"{(i + 0.5) / n * 100:.2f}"
                if dt.hour == 0:
                    xlabels.append({"left": left, "text": WOCHENTAGE_KURZ[dt.weekday()], "bold": True})
                elif i == 0:
                    xlabels.append({"left": left, "text": "Jetzt", "bold": True})
                else:
                    xlabels.append({"left": left, "text": f"{dt.hour}", "bold": False})
                if opts["graph_icons"]:
                    ic = refine_icon(r.get("icon"), r.get("precipitation"), r.get("cloud_cover"),
                                     self.is_day(dt, sun_cache))
                    gicons.append({"left": left, "svg": icons.weather_icon(ic, "g-icon")})

        imax = temps.index(tmax)
        imin = temps.index(tmin)
        tlabels = [{"left": f"{(imax + 0.5) / n * 100:.2f}", "top": f"{y(tmax) / H * 100:.2f}",
                    "text": f"{de_num(tmax)}°", "cls": "t-max"}]
        if imin != imax:
            tlabels.append({"left": f"{(imin + 0.5) / n * 100:.2f}", "top": f"{y(tmin) / H * 100:.2f}",
                            "text": f"{de_num(tmin)}°", "cls": "t-min"})
        # Endwert zusätzlich beschriften, falls er nicht nah an Min/Max liegt
        if abs(n - 1 - imax) > n / 6 and abs(n - 1 - imin) > n / 6:
            tlabels.append({"left": f"{(n - 0.5) / n * 100:.2f}", "top": f"{y(temps[-1]) / H * 100:.2f}",
                            "text": f"{de_num(temps[-1])}°", "cls": "t-end"})

        # Beschriftungen am Rand nicht abschneiden
        def edge(item):
            left = float(item["left"])
            item["edge"] = " edge-l" if left < 6 else (" edge-r" if left > 94 else "")
            return item

        xlabels = [edge(i) for i in xlabels]
        gicons = [edge(i) for i in gicons]
        tlabels = [edge(i) for i in tlabels]

        return {
            "hours": n - 1,
            "line": d,
            "area": area,
            "bars": bars,
            "nights": nights,
            "rain_labels": rain_labels,
            "xlabels": xlabels,
            "icons": gicons,
            "tlabels": tlabels,
        }
