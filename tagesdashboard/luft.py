"""
Luftqualität draußen: eine Karte nur dann, wenn die Luft mäßig oder schlechter ist (Variante B).

Quellen
-------
1. sensor.community (Bürgersensoren, meist SDS011) – vorrangig, weil nah und aktuell:
   https://data.sensor.community/airrohr/v1/filter/area=LAT,LON,KM
   * alle Messungen der letzten 5 Minuten im Umkreis; ohne Schlüssel, aber mit User-Agent (Pflicht)
   * Eintrag: {"timestamp": "2026-11-13 14:02:11" (UTC), "location": {"indoor": 0, ...},
     "sensor": {"id": 12345, "sensor_type": {"name": "SDS011"}},
     "sensordatavalues": [{"value_type": "P1", "value": "18.4"}, {"value_type": "P2", "value": "9.1"}]}
   * P1 = PM10, P2 = PM2,5 in µg/m³. Andere Typen (BME280 …) liefern Temperatur/Feuchte und zählen hier nicht.
   * Lizenz der Daten: ODbL, Quelle „sensor.community“.

2. Umweltbundesamt, amtliche Messstation (Standard: Bonn-Auerberg, DENW062, betrieben vom Land NRW) – als Rückfall:
   https://luftdaten.umweltbundesamt.de/api-proxy/airquality/json?date_from=…&time_from=…&station=DENW062
   * Stundenwerte; Zeiten in MEZ (ganzjährig UTC+1, keine Sommerzeit), Stunden 1–24
   * data = {station: {"beginn": [ende, gesamtindex, unvollständig, [komponente, wert, index, anteil], …]}}
   * Komponenten: 1 = PM10, 3 = Ozon, 5 = NO2, 9 = PM2,5 (µg/m³)
   * Quellenangabe laut UBA: „Umweltbundesamt mit Daten der Messnetze der Länder und des Bundes“

Warum zwei Quellen?
-------------------
Die günstigen Laser-Sensoren zählen bei feuchter Luft Wassertröpfchen als Feinstaub mit und zeigen
dann zu viel – bei Nebel oft das Doppelte. Ist die Luftfeuchte am Wetter-Ort hoch (HUMID_RH, aus den
DWD-Werten), gilt deshalb der Wert der Messstation. Fehlen die Bürgersensoren (zu wenige, Dienst
nicht erreichbar), springt die Station ebenfalls ein. Ohne Station und bei Feuchte zeigt die Karte den
Sensorwert, aber gestrichelt und mit Hinweis.

Einstufung
----------
Nach dem Luftqualitätsindex (LQI) des Umweltbundesamts, Stundenwerte, Klassengrenzen seit 2025
(siehe LQI_LIMITS). Der schlechteste Schadstoff bestimmt die Klasse. Die Bürgersensoren liefern
5-Minuten-Werte; damit die Karte nicht bei jedem Ausreißer kommt und geht, wird über die Abrufe
der letzten Stunde gemittelt (_history).
"""

import logging
import statistics
import time as _time
from datetime import datetime, timedelta, timezone

import requests

logger = logging.getLogger(__name__)

COMMUNITY_URL = "https://data.sensor.community/airrohr/v1/filter/area={lat:.4f},{lon:.4f},{km}"
UBA_URLS = [  # API v4 (Proxy der Luftdaten-Seite); Rückfall auf v3, falls der Proxy umzieht
    "https://luftdaten.umweltbundesamt.de/api-proxy/airquality/json",
    "https://luftdaten.umweltbundesamt.de/api/air-data/v3/airquality/json",
]
HEADERS = {"User-Agent": "InkyPi-Tagesdashboard/1.13 (privates E-Ink-Display; github.com/leonschwarze/InkyPi_Dashboard)"}
TIMEOUT = 12

DEFAULT_STATION = "DENW062"   # Bonn-Auerberg
DEFAULT_RADIUS_KM = 3
MIN_SENSORS = 3               # weniger Außensensoren: kein verlässlicher Median
MAX_AGE_MIN = 20              # ältere Messungen eines Sensors zählen nicht
HUMID_RH = 80                 # ab hier messen die Laser-Sensoren deutlich zu viel
SMOOTH_MIN = 60               # Mittel über die Abrufe der letzten Stunde
COMMUNITY_CACHE_MIN = 10      # die meisten Stationen senden etwa alle 5–10 Minuten
UBA_CACHE_MIN = 30            # Stundenwerte, kommen mit Verzögerung
UBA_MAX_AGE_H = 3             # älter: Station gilt als ausgefallen
CET = timezone(timedelta(hours=1))

# Klassengrenzen des LQI (Obergrenze je Klasse, µg/m³, Stundenwert); Klasse 1 sehr gut … 5 sehr schlecht
LQI_LIMITS = {
    "pm25": (5, 15, 30, 50),
    "pm10": (9, 27, 54, 90),
    "no2": (10, 30, 60, 100),
    "o3": (24, 72, 144, 240),
}
LEVEL_WORD = {1: "sehr gut", 2: "gut", 3: "mäßig", 4: "schlecht", 5: "sehr schlecht"}
LEVEL_CLASS = {3: "maessig", 4: "schlecht", 5: "sehr-schlecht"}
NAMES = {"pm25": "Feinstaub", "pm10": "Feinstaub", "no2": "Stickstoffdioxid", "o3": "Ozon"}
SHORT = {"pm25": "PM2,5", "pm10": "PM10", "no2": "NO₂", "o3": "Ozon"}
TOP = {3: "{} erhöht", 4: "{} hoch", 5: "{} sehr hoch"}
# Kurzfassung der UBA-Verhaltenshinweise für die jeweilige Klasse
ADVICE = {
    3: "Unbedenklich, aber lieber kurz lüften",
    4: "Anstrengenden Sport draußen meiden",
    5: "Sport draußen meiden · Fenster zu",
}
UBA_COMPONENTS = {1: "pm10", 3: "o3", 5: "no2", 9: "pm25"}

_cache = {}     # Schlüssel -> (monotonic, ergebnis)
_history = {}   # (lat, lon, km) -> [(zeit, pm10, pm25)]


# ----------------------------------------------------------------------
# Einstellungen
# ----------------------------------------------------------------------
def read_config(opt, flag, lat, lon):
    if not flag("airEnabled") or lat is None or lon is None:
        return None
    radius = (opt("airRadius") or "").strip().replace(",", ".")
    try:
        radius = min(max(float(radius), 0.5), 10)
    except ValueError:
        radius = DEFAULT_RADIUS_KM
    level = (opt("airLevel") or "3").strip()
    return {
        "lat": lat, "lon": lon,
        "radius": round(radius, 1),
        "level": 4 if level == "4" else 3,
        "station": (opt("airStation") or "").strip().upper() or DEFAULT_STATION,
        "gases": flag("airGases"),
    }


# ----------------------------------------------------------------------
# Einstufung
# ----------------------------------------------------------------------
def classify(component, value):
    """LQI-Klasse 1–5 eines Stundenwerts; Grenzwerte gehören zur unteren Klasse (z. B. PM2,5 = 15 → gut)."""
    if value is None:
        return None
    for i, limit in enumerate(LQI_LIMITS[component], start=1):
        if value <= limit + 0.49:  # das UBA rundet auf ganze µg/m³
            return i
    return 5


def de_int(value):
    return str(int(round(value)))


# ----------------------------------------------------------------------
# sensor.community
# ----------------------------------------------------------------------
def _num(value):
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def aggregate(entries, now):
    """Median über die Außensensoren: {"pm10", "pm25", "n10", "n25"} – Werte None, wenn zu wenige Sensoren.
    Pro Sensor zählt der Mittelwert seiner frischen Messungen; Innensensoren und Fehlwerte fallen weg."""
    limit = now.astimezone(timezone.utc) - timedelta(minutes=MAX_AGE_MIN)
    per_sensor = {}
    for e in entries or []:
        try:
            loc = e.get("location") or {}
            if str(loc.get("indoor", 0)) not in ("0", "False", "false", ""):
                continue
            ts = datetime.strptime(e["timestamp"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            if ts < limit:
                continue
            sid = (e.get("sensor") or {}).get("id")
            vals = {v.get("value_type"): _num(v.get("value")) for v in e.get("sensordatavalues") or []}
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
        for key, comp in (("P1", "pm10"), ("P2", "pm25")):
            v = vals.get(key)
            # SDS011 meldet 999,9 bei Messfehlern; negative Werte gibt es nicht
            if v is None or v < 0 or v >= 999:
                continue
            per_sensor.setdefault((comp, sid), []).append(v)
    out = {}
    for comp in ("pm10", "pm25"):
        values = [sum(vs) / len(vs) for (c, _), vs in per_sensor.items() if c == comp]
        out["n" + comp[2:]] = len(values)
        out[comp] = statistics.median(values) if len(values) >= MIN_SENSORS else None
    return out


def fetch_community(lat, lon, km, session):
    url = COMMUNITY_URL.format(lat=lat, lon=lon, km=km)
    r = session.get(url, headers=HEADERS, timeout=TIMEOUT)
    if r.status_code != 200:
        raise RuntimeError(f"sensor.community: HTTP {r.status_code}")
    return r.json()


def community(cfg, now, session):
    """Geglätteter Wert der Bürgersensoren oder None."""
    key = ("com", round(cfg["lat"], 3), round(cfg["lon"], 3), cfg["radius"])
    hit = _cache.get(key)
    if hit and _time.monotonic() - hit[0] < COMMUNITY_CACHE_MIN * 60:
        agg = hit[1]
    else:
        try:
            agg = aggregate(fetch_community(cfg["lat"], cfg["lon"], cfg["radius"], session), now)
        except Exception as exc:  # Zusatz: nie das ganze Bild verlieren
            logger.warning("Luft: sensor.community nicht verfügbar: %s", exc)
            agg = None
        _cache[key] = (_time.monotonic(), agg)
        if agg and agg.get("pm10") is not None and agg.get("pm25") is not None:
            hist = _history.setdefault(key, [])
            hist.append((now, agg["pm10"], agg["pm25"]))
    if not agg or agg.get("pm10") is None or agg.get("pm25") is None:
        return None
    hist = [h for h in _history.get(key, []) if now - timedelta(minutes=SMOOTH_MIN) <= h[0] <= now]
    _history[key] = hist
    if not hist:  # z. B. Zeit im Test zurückgedreht
        hist = [(now, agg["pm10"], agg["pm25"])]
    return {
        "pm10": sum(h[1] for h in hist) / len(hist),
        "pm25": sum(h[2] for h in hist) / len(hist),
        "n": min(agg["n10"], agg["n25"]),
        "source": "sensors",
    }


# ----------------------------------------------------------------------
# Umweltbundesamt
# ----------------------------------------------------------------------
def _parse_cet(text):
    """„2026-11-13 14:00:00“ in MEZ; das UBA schreibt Mitternacht auch als „24:00:00“."""
    day, _, clock = str(text).partition(" ")
    hh, mm, *_ = (clock or "00:00").split(":")
    base = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=CET)
    return base + timedelta(hours=int(hh), minutes=int(mm))


def parse_uba(payload, now):
    """Neuester Stundenwert der Station: {"pm10", "pm25", "no2", "o3", "end"} (fehlende Stoffe None) oder None."""
    data = (payload or {}).get("data") or {}
    best = None
    for station in data.values():  # Schlüssel ist je nach API-Version Nummer oder Code
        if not isinstance(station, dict):
            continue
        for start, row in station.items():
            try:
                end = _parse_cet(row[0])
            except (IndexError, ValueError, TypeError):
                continue
            values = {}
            for comp in row[3:]:
                try:
                    name = UBA_COMPONENTS.get(int(comp[0]))
                    if name and comp[1] is not None:
                        values[name] = float(comp[1])
                except (IndexError, ValueError, TypeError):
                    continue
            if values and (best is None or end > best["end"]):
                best = dict({k: None for k in UBA_COMPONENTS.values()}, **values, end=end)
    if best is None or best["end"] < now - timedelta(hours=UBA_MAX_AGE_H):
        return None
    return best


def fetch_uba(station, now, session):
    cet = now.astimezone(CET)
    params = {"date_from": (cet - timedelta(hours=UBA_MAX_AGE_H + 1)).strftime("%Y-%m-%d"), "time_from": 1,
              "date_to": cet.strftime("%Y-%m-%d"), "time_to": 24, "station": station, "lang": "de"}
    last = None
    for url in UBA_URLS:
        try:
            r = session.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
            if r.status_code == 200:
                return r.json()
            last = f"HTTP {r.status_code}"
        except requests.RequestException as exc:
            last = str(exc)
    raise RuntimeError(f"Umweltbundesamt: {last}")


def uba(cfg, now, session):
    key = ("uba", cfg["station"])
    hit = _cache.get(key)
    if hit and _time.monotonic() - hit[0] < UBA_CACHE_MIN * 60:
        payload = hit[1]
    else:
        try:
            payload = fetch_uba(cfg["station"], now, session)
        except Exception as exc:
            logger.warning("Luft: Messstation nicht verfügbar: %s", exc)
            payload = None
        _cache[key] = (_time.monotonic(), payload)
    return parse_uba(payload, now) if payload else None


# ----------------------------------------------------------------------
# Entscheidung und Karte
# ----------------------------------------------------------------------
def humidity_now(records, now):
    """Relative Feuchte (%) aus dem DWD-Stundenwert, der jetzt am nächsten liegt (± 90 min)."""
    near = [r for r in records or [] if r.get("relative_humidity") is not None
            and abs((r["dt"] - now).total_seconds()) <= 90 * 60]
    if not near:
        return None
    return min(near, key=lambda r: abs((r["dt"] - now).total_seconds()))["relative_humidity"]


def assess(com, station, rh, cfg):
    """Welche Werte gelten, und muss die Karte erscheinen? Gibt die Karte zurück oder None.

    Feinstaub: Bürgersensoren, außer bei hoher Feuchte oder wenn sie fehlen – dann die Messstation.
    Ozon und NO2 (nur mit cfg["gases"]) kommen immer von der Station."""
    humid = rh is not None and rh >= HUMID_RH
    station_pm = station and station.get("pm10") is not None and station.get("pm25") is not None
    unsure = False
    if com and not humid:
        pm, src = com, "sensors"
    elif station_pm:
        pm, src = station, "station"
    elif com:
        pm, src, unsure = com, "sensors", True
    else:
        pm, src = None, None

    values = {}
    if pm:
        values.update(pm10=pm["pm10"], pm25=pm["pm25"])
    if cfg["gases"] and station:
        values.update({k: station[k] for k in ("no2", "o3") if station.get(k) is not None})
    if not values:
        return None
    levels = {k: classify(k, v) for k, v in values.items()}
    worst = max(levels.values())
    if worst < cfg["level"]:
        return None

    # Hauptschadstoff: der mit der schlechtesten Klasse; bei Gleichstand Feinstaub vor Gasen
    order = ["pm25", "pm10", "o3", "no2"]
    lead = next(k for k in order if levels.get(k) == worst)
    if lead in ("pm25", "pm10"):
        shown = f"PM2,5 {de_int(values['pm25'])} · PM10 {de_int(values['pm10'])}"  # µg/m³; Einheit kostet zu viel Platz
        where = f"{pm['n']} Sensoren" if src == "sensors" else "Station"
    else:  # Gas: Wert kommt immer von der Station
        shown = f"{SHORT[lead]} {de_int(values[lead])} µg/m³"
        where = "Station"
    return {
        "level": worst,
        "state": LEVEL_CLASS[worst],
        "badge": LEVEL_WORD[worst],
        "top": TOP[worst].format(NAMES[lead]),
        "reading": shown,
        "where": where,
        "advice": "Feucht: Sensoren zeigen oft zu viel" if unsure and lead in ("pm25", "pm10") else ADVICE[worst],
        "unsure": unsure and lead in ("pm25", "pm10"),
        "source": src,
        "humid": humid,
    }


def load(cfg, now, records, session=None):
    """Karte für das Dashboard oder None (Luft gut oder keine Daten)."""
    session = session or requests.Session()
    rh = humidity_now(records, now)
    com = community(cfg, now, session)
    # Die Station brauchen wir nur, wenn sie etwas ändern kann – spart Abrufe
    need_station = cfg["gases"] or com is None or (rh is not None and rh >= HUMID_RH)
    station = uba(cfg, now, session) if need_station else None
    card = assess(com, station, rh, cfg)
    logger.info("Luft: Sensoren %s, Station %s, Feuchte %s %% → %s",
                {k: round(v, 1) for k, v in com.items() if k in ("pm10", "pm25")} if com else "–",
                {k: v for k, v in station.items() if k != "end"} if station else "–", rh,
                card["badge"] if card else "keine Karte")
    return card
