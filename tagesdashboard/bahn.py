"""
Live-Daten eines bestimmten Zuges von der Deutschen Bahn (Timetables-API, intern "IRIS").

Die API kennt zwei Arten von Daten:
  plan/{eva}/{yymmdd}/{HH}   Sollfahrplan einer Stunde an einem Bahnhof
  fchg/{eva}                 alle bekannten Änderungen an diesem Bahnhof (Verspätung,
                             Gleiswechsel, Ausfall, geänderter Laufweg)
Beides ist XML. Ein Halt ("s") hat in beiden dieselbe id; so werden Plan und
Änderungen zusammengeführt.

Zugang:
  * offiziell über den DB API Marketplace (kostenlos, Client-ID und API-Key nötig,
    in der .env als DB_CLIENT_ID und DB_API_KEY)
  * ohne Schlüssel über iris.noncd.db.de (dieselben Daten; inoffiziell, kann wegfallen)
Sind Schlüssel hinterlegt, wird zuerst die offizielle Adresse versucht.

Datenquelle: Deutsche Bahn AG, Timetables API, Lizenz CC BY 4.0.
"""

import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, time, timedelta
from urllib.parse import quote

import requests

logger = logging.getLogger(__name__)

OFFICIAL = "https://apis.deutschebahn.com/db-api-marketplace/apis/timetables/v1"
PUBLIC = "https://iris.noncd.db.de/iris-tts/timetable"
TIMEOUT = 10

# Häufige Bahnhöfe ohne Nachschlagen (EVA-Nummer); alle anderen fragt bahn.station() ab
KNOWN_STATIONS = {"bonn hbf": "8000044", "köln hbf": "8000207", "koblenz hbf": "8000206"}
_station_cache = {}

WEEKDAY_KEYS = ["trainMo", "trainDi", "trainMi", "trainDo", "trainFr", "trainSa", "trainSo"]
WEEKDAY_SHORT = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


def hm(dt):
    return f"{dt.hour}:{dt.minute:02d}"


def parse_hhmm(text):
    m = re.fullmatch(r"\s*(\d{1,2})[:.](\d{2})\s*", text or "")
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return None
    return time(int(m.group(1)), int(m.group(2)))


def split_line(text):
    """ "RE 5", "RE5", "re-5" -> ("RE", "5"); "S 23" -> ("S", "23")."""
    m = re.fullmatch(r"\s*([A-Za-zÄÖÜäöü]+)\s*-?\s*([0-9A-Za-z]+)\s*", text or "")
    return (m.group(1).upper(), m.group(2)) if m else None


def iris_time(value, tz):
    """IRIS-Zeitstempel yyMMddHHmm (deutsche Ortszeit) -> datetime mit Zeitzone."""
    return datetime.strptime(value, "%y%m%d%H%M").replace(tzinfo=tz)


# ----------------------------------------------------------------------
# Einstellungen und Zeitfenster
# ----------------------------------------------------------------------
def read_config(opt, flag):
    """Liest die Zug-Einstellungen. None, wenn ausgeschaltet oder unvollständig."""
    if not flag("trainEnabled"):
        return None
    line = split_line(opt("trainLine"))
    dep = parse_hhmm(opt("trainTime"))
    start, end = parse_hhmm(opt("trainFrom")), parse_hhmm(opt("trainTo"))
    days = [i for i, key in enumerate(WEEKDAY_KEYS) if flag(key)]
    station = (opt("trainStation") or "").strip()
    if not (line and dep and start and end and days and station):
        logger.warning("Zug-Anzeige: Einstellungen unvollständig (Linie, Abfahrt, Zeitfenster, Wochentage, Bahnhof)")
        return None
    return {"station": station, "cat": line[0], "num": line[1], "label": f"{line[0]} {line[1]}",
            "dep": dep, "start": start, "end": end, "days": days}


def in_window(now, cfg):
    return now.weekday() in cfg["days"] and cfg["start"] <= now.time().replace(second=0, microsecond=0) <= cfg["end"]


def next_window_start(now, cfg):
    """Beginn des nächsten Zeitfensters nach `now` (für den Bild-Cache)."""
    for offset in range(8):
        day = now.date() + timedelta(days=offset)
        if day.weekday() not in cfg["days"]:
            continue
        start = datetime.combine(day, cfg["start"], tzinfo=now.tzinfo)
        if start > now:
            return start
    return None


# ----------------------------------------------------------------------
# Abruf
# ----------------------------------------------------------------------
def sources(client_id, api_key):
    out = []
    if client_id and api_key:
        out.append((OFFICIAL, {"DB-Client-Id": client_id, "DB-Api-Key": api_key, "Accept": "application/xml"}))
    out.append((PUBLIC, {"Accept": "application/xml"}))
    return out


def fetch(session, srcs, path):
    last = None
    for base, headers in srcs:
        try:
            r = session.get(f"{base}/{path}", headers=headers, timeout=TIMEOUT)
            if r.status_code == 200 and r.content.strip():
                return r.content
            last = f"HTTP {r.status_code}"
        except requests.RequestException as exc:
            last = type(exc).__name__
        logger.info("Bahn-API %s: %s – versuche nächste Quelle", base, last)
    raise RuntimeError(f"Bahn-Daten nicht erreichbar ({last})")


def station(session, srcs, name):
    """Bahnhofsname oder EVA-Nummer -> (EVA, Name)."""
    if name.isdigit():
        return name, name
    key = name.lower()
    if key in _station_cache:
        return _station_cache[key]
    if key in KNOWN_STATIONS:
        return KNOWN_STATIONS[key], name
    root = ET.fromstring(fetch(session, srcs, f"station/{quote(name)}"))
    st = root.find("station")
    if st is None or not st.get("eva"):
        raise RuntimeError(f"Bahnhof „{name}“ nicht gefunden")
    _station_cache[key] = (st.get("eva"), st.get("name") or name)
    return _station_cache[key]


# ----------------------------------------------------------------------
# Auswertung (ohne Netz, damit testbar)
# ----------------------------------------------------------------------
def find_planned(xml_bytes, cat, num, pt):
    """Sucht im Sollfahrplan den Halt der Linie cat/num mit Abfahrt pt (yyMMddHHmm)."""
    root = ET.fromstring(xml_bytes)
    for s in root.iter("s"):
        dp, tl = s.find("dp"), s.find("tl")
        if dp is None or tl is None or dp.get("pt") != pt:
            continue
        if (tl.get("c") or "").upper() != cat:
            continue
        if num not in (dp.get("l"), tl.get("n")):
            continue
        return {
            "id": s.get("id"),
            "platform": dp.get("pp") or "",
            "path": [p for p in (dp.get("ppth") or "").split("|") if p],
            "number": tl.get("n") or "",
        }
    return None


def find_changes(xml_bytes, stop_id):
    """Änderungen zur Abfahrt eines Halts. Leeres dict, wenn nichts geändert ist."""
    root = ET.fromstring(xml_bytes)
    for s in root.iter("s"):
        if s.get("id") != stop_id:
            continue
        dp = s.find("dp")
        if dp is None:
            return {}
        return {k: dp.get(k) for k in ("ct", "cp", "cs", "cpth", "clt") if dp.get(k)}
    return {}


def status(plan, changes, planned_dt, now, tz):
    """Fasst Plan und Änderungen zu den Werten zusammen, die angezeigt werden."""
    actual = iris_time(changes["ct"], tz) if changes.get("ct") else planned_dt
    delay = max(0, round((actual - planned_dt).total_seconds() / 60))
    cancelled = changes.get("cs") == "c"
    platform = changes.get("cp") or plan["platform"]
    platform_changed = bool(changes.get("cp")) and changes["cp"] != plan["platform"]
    path = [p for p in (changes.get("cpth") or "").split("|") if p] or plan["path"]
    dest = path[-1] if path else ""
    planned_dest = plan["path"][-1] if plan["path"] else ""
    shortened = bool(changes.get("cpth")) and dest and planned_dest and dest != planned_dest

    if cancelled:
        state, badge = "cancelled", "fällt aus"
    elif now >= actual + timedelta(minutes=1):
        state, badge = "gone", "abgefahren"
    elif delay >= 5:
        state, badge = "late", f"+{delay}"
    elif delay >= 1:
        state, badge = "slight", f"+{delay}"
    else:
        state, badge = "ok", "pünktlich"
    return {
        "state": state, "badge": badge, "delay": delay,
        "planned": hm(planned_dt), "actual": hm(actual),
        # Ziel laut Plan; endet der Zug früher, steht das zusätzlich als Hinweis da
        "dest": planned_dest or dest, "platform": platform, "platform_changed": platform_changed,
        "planned_platform": plan["platform"],
        "note": f"endet in {dest}" if shortened and not cancelled else "",
    }


def load(cfg, now, tz, client_id=None, api_key=None, session=None):
    """Live-Status des Zuges aus den Einstellungen. Wirft keine Fehler: Bei Problemen
    kommt ein Eintrag mit state "unknown" zurück, damit das Dashboard trotzdem erscheint."""
    planned_dt = datetime.combine(now.date(), cfg["dep"], tzinfo=tz)
    base = {"label": cfg["label"], "planned": hm(planned_dt), "actual": hm(planned_dt), "dest": "",
            "platform": "", "platform_changed": False, "note": "", "delay": 0}
    session = session or requests.Session()
    srcs = sources(client_id, api_key)
    try:
        eva, _ = station(session, srcs, cfg["station"])
        pt = planned_dt.strftime("%y%m%d%H%M")
        plan = find_planned(fetch(session, srcs, f"plan/{eva}/{pt[:6]}/{pt[6:8]}"), cfg["cat"], cfg["num"], pt)
        if plan is None:
            return dict(base, state="unknown", badge="nicht im Fahrplan",
                        note=f"{cfg['label']} um {hm(planned_dt)} heute nicht gefunden")
        try:
            changes = find_changes(fetch(session, srcs, f"fchg/{eva}"), plan["id"])
            live = True
        except RuntimeError as exc:
            logger.warning("Bahn-Änderungen nicht abrufbar: %s", exc)
            changes, live = {}, False
        out = dict(base, **status(plan, changes, planned_dt, now, tz))
        if not live:
            out.update(state="unknown", badge="ohne Live-Daten")
        return out
    except (RuntimeError, ET.ParseError, ValueError) as exc:
        logger.warning("Zugdaten nicht verfügbar: %s", exc)
        return dict(base, state="unknown", badge="keine Daten", note="Bahn nicht erreichbar")
