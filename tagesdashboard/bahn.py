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

Störungsmonitor: An jedem Halt hängen Meldungen ("m"): Verspätungsgründe (nur als Code),
Qualitätshinweise und Freitext-Meldungen zu Störungen und Baustellen. Ausgewertet werden die
Meldungen am Abfahrts- und am Ausstiegsbahnhof, und zwar nur die an genau dieser Fahrt –
Meldungen zu anderen Zügen oder zum Bahnhof (Aufzug defekt …) bleiben draußen.
Die eigentliche Störungs-API der Bahn (RIS::Disruptions) ist kostenpflichtig und nur für
Vertriebspartner freigegeben; die Meldungen hier kommen aus derselben Quelle wie die Tafeln.

Datenquelle: Deutsche Bahn AG, Timetables API, Lizenz CC BY 4.0.
"""

import html
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, time, timedelta
from urllib.parse import quote

import requests

try:
    from . import strecke
except ImportError:  # Tests importieren die Module ohne Paket
    import strecke

logger = logging.getLogger(__name__)

OFFICIAL = "https://apis.deutschebahn.com/db-api-marketplace/apis/timetables/v1"
PUBLIC = "https://iris.noncd.db.de/iris-tts/timetable"
TIMEOUT = 10

# Häufige Bahnhöfe ohne Nachschlagen (EVA-Nummer); alle anderen fragt bahn.station() ab
KNOWN_STATIONS = {"bonn hbf": "8000044", "köln hbf": "8000207", "koblenz hbf": "8000206",
                  "düsseldorf hbf": "8000085"}
_station_cache = {}
# Halt des Zuges am Zielbahnhof (Sollfahrplan ändert sich am Tag nicht): einmal suchen, dann merken
_target_cache = {}

# ----------------------------------------------------------------------
# Meldungen (Element "m" an einem Halt)
# ----------------------------------------------------------------------
# t = Art der Meldung: d Verspätungsgrund, f/q Qualität (Wagen, WLAN …), h HIM-Meldung
# (Baustellen, Störungen mit Freitext), r Störung, c Anschluss. pr = Priorität 1 hoch … 4 erledigt.
# Codes der Verspätungs- und Qualitätsmeldungen; die API liefert nur die Nummer. Texte wie in
# Travel::Status::DE::IRIS (Perl-Modul, das die DB-Codeliste pflegt), leicht gekürzt.
CODES = {
    1: "Nähere Informationen in Kürze", 2: "Polizeieinsatz", 3: "Feuerwehreinsatz an der Strecke",
    4: "Kurzfristiger Personalausfall", 5: "Ärztliche Versorgung eines Fahrgastes",
    6: "Notbremse betätigt", 7: "Unbefugte Personen an der Strecke", 8: "Notarzteinsatz an der Strecke",
    9: "Streikauswirkungen", 10: "Tiere an der Strecke", 11: "Unwetter", 13: "Pass- und Zollkontrolle",
    14: "Defekt am Bahnhof", 15: "Vandalismus", 16: "Entschärfung einer Fliegerbombe",
    17: "Beschädigung einer Brücke", 18: "Umgestürzter Baum auf der Strecke",
    19: "Unfall an einem Bahnübergang", 20: "Tiere im Gleis", 21: "Warten auf Anschlussreisende",
    22: "Witterungsbedingte Beeinträchtigungen", 23: "Betriebsstabilisierung", 24: "Verspätung im Ausland",
    25: "Bereitstellung weiterer Wagen", 26: "Abhängen von Wagen", 28: "Gegenstände auf der Strecke",
    29: "Ersatzverkehr mit Bus", 30: "Personalausfall im Stellwerk", 31: "Bauarbeiten",
    32: "Längere Haltezeit am Bahnhof", 33: "Defekt an der Oberleitung", 34: "Defekt an einem Signal",
    35: "Streckensperrung", 36: "Technische Störung am Zug", 37: "Kurzfristiger Fahrzeugausfall",
    38: "Defekt an der Strecke", 39: "Hohes Verkehrsaufkommen", 40: "Defektes Stellwerk",
    41: "Defekt an einem Bahnübergang", 42: "Außerplanmäßige Geschwindigkeitsbeschränkung",
    43: "Verspätung eines vorausfahrenden Zuges", 44: "Warten auf einen entgegenkommenden Zug",
    45: "Vorfahrt eines anderen Zuges", 46: "Vorfahrt eines anderen Zuges",
    47: "Verspätete Bereitstellung", 48: "Verspätung aus vorheriger Fahrt",
    49: "Kurzfristiger Personalausfall", 50: "Kurzfristige Erkrankung von Personal",
    51: "Verspätetes Personal aus vorheriger Fahrt", 52: "Streik", 53: "Unwetterauswirkungen",
    54: "Gleise derzeit eingeschränkt verfügbar", 55: "Technischer Defekt an einem anderen Zug",
    57: "Zusätzlicher Halt", 58: "Umleitung", 59: "Schnee und Eis",
    60: "Witterungsbedingt verminderte Geschwindigkeit", 61: "Defekte Tür", 62: "Behobener Defekt am Zug",
    63: "Technische Untersuchung am Zug", 64: "Defekt an einer Weiche", 65: "Erdrutsch", 66: "Hochwasser",
    67: "Behördliche Maßnahme", 68: "Hohes Fahrgastaufkommen", 69: "Verminderte Geschwindigkeit",
    78: "Ersatzverkehr mit Bus", 82: "Mehrere Wagen fehlen", 85: "Ein Wagen fehlt",
    97: "Hohe Auslastung", 99: "Verzögerungen im Betriebsablauf",
}
# Qualitätsmeldungen, die für Pendler zählen (WLAN, Wagenreihung, Bistro usw. bleiben weg)
QUALITY_SHOWN = {29, 78, 82, 85, 97}
# Verspätungsgründe, die nach echter Störung klingen (rot statt gelb markiert)
SEVERE_CODES = {2, 3, 7, 8, 9, 16, 17, 18, 19, 29, 30, 33, 34, 35, 38, 40, 52, 64, 65, 66, 67, 78}
MAX_TEXT = 140

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
            "dep": dep, "start": start, "end": end, "days": days,
            # Ausstieg: dort wird die Ankunft gezeigt und nach weiteren Meldungen gesucht
            "target": (opt("trainTarget") or "").strip(), "alerts": flag("trainAlerts"),
            # Streckenmeldungen der VRR-Auskunft (strecke.py): Vorwarnung, bevor der Zug betroffen ist
            "route": flag("trainRoute")}


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
        dp, tl, ar = s.find("dp"), s.find("tl"), s.find("ar")
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
            # Halte vor diesem Bahnhof (für die Streckenmeldungen: Störungen vor dem Einstieg zählen auch)
            "before": [p for p in ((ar.get("ppth") if ar is not None else "") or "").split("|") if p],
            "number": tl.get("n") or "",
        }
    return None


def trip_key(stop_id):
    """Halt-IDs sind aufgebaut als <Fahrt>-<Startzeit>-<Haltnummer>. Die ersten beiden Teile sind
    an allen Bahnhöfen derselben Fahrt gleich; so findet sich der Zug am Zielbahnhof wieder."""
    return stop_id.rsplit("-", 1)[0] if stop_id and stop_id.count("-") >= 2 else stop_id


def _stop(root, stop_id):
    for s in root.iter("s"):
        if s.get("id") == stop_id:
            return s
    return None


def _attrs(el):
    return {k: el.get(k) for k in ("ct", "cp", "cs", "cpth", "clt") if el is not None and el.get(k)}


def find_changes(xml_bytes, stop_id, kind="dp"):
    """Änderungen zur Abfahrt (dp) oder Ankunft (ar) eines Halts. Leeres dict ohne Änderungen."""
    s = _stop(ET.fromstring(xml_bytes), stop_id)
    return _attrs(s.find(kind)) if s is not None else {}


def find_stop(xml_bytes, key, number):
    """Ankunft derselben Fahrt in einem Sollfahrplan: zuerst über die Fahrt-ID, sonst über die
    Zugnummer (falls die ID-Teile einmal nicht übereinstimmen)."""
    fallback = None
    for s in ET.fromstring(xml_bytes).iter("s"):
        ar = s.find("ar")
        if ar is None or not ar.get("pt"):
            continue
        hit = {"id": s.get("id"), "pt": ar.get("pt"), "platform": ar.get("pp") or ""}
        if trip_key(s.get("id")) == key:
            return hit
        tl = s.find("tl")
        if fallback is None and number and tl is not None and tl.get("n") == number:
            fallback = hit
    return fallback


def find_messages(root, stop_id):
    """Alle Meldungen eines Halts (am Halt selbst, an Ankunft und Abfahrt), ohne gelöschte."""
    s = _stop(root, stop_id) if root is not None else None
    out, seen = [], set()
    for m in (s.iter("m") if s is not None else []):
        if m.get("del") == "1" or m.get("id") in seen:
            continue
        seen.add(m.get("id"))
        out.append({k: m.get(k) or "" for k in ("id", "t", "c", "cat", "ext", "pr", "from", "to", "ts")})
    return out


def clean(text):
    """Freitext der Bahn: HTML-Reste entfernen, Leerraum zusammenziehen, lange Texte kürzen."""
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > MAX_TEXT:
        text = text[:MAX_TEXT].rsplit(" ", 1)[0].rstrip(",;:–- ") + " …"
    return text


def alerts(msgs, now, until, tz, delayed):
    """Meldungen -> kurze Hinweise [{text, level}] für die Anzeige, wichtigste zuerst.

    Störungen und Baustellen (Freitext) gelten nur, solange sie gültig sind. Vom
    Verspätungsgrund zeigt das Dashboard nur den neuesten, und nur, wenn der Zug wirklich
    verspätet ist oder ausfällt (sonst bliebe ein alter Grund stehen)."""
    found, reasons = [], []
    for m in msgs:
        if m["pr"] == "4":
            continue
        try:
            if m["to"] and iris_time(m["to"], tz) < now:
                continue
            if m["from"] and iris_time(m["from"], tz) > until:
                continue
        except ValueError:
            pass
        code = int(m["c"]) if m["c"].isdigit() else None
        if m["t"] == "d":
            if code in CODES and delayed:
                reasons.append((m["ts"], code))
        elif m["t"] in ("f", "q"):
            if code in QUALITY_SHOWN:
                found.append((CODES[code], "high" if code in SEVERE_CODES else "info", "quality"))
        elif m["t"] in ("h", "r"):
            text = clean(m["ext"]) or CODES.get(code, "") or clean(m["cat"])
            if text and text.lower() not in ("information", "info", "hinweis"):
                found.append((text, "high" if m["t"] == "r" or m["pr"] == "1" else "info", "notice"))
    if reasons:
        code = max(reasons)[1]
        found.append((CODES[code], "high" if code in SEVERE_CODES else "info", "reason"))
    out, seen = [], set()
    for text, level, kind in sorted(found, key=lambda x: x[1] != "high"):  # stabil: Reihenfolge bleibt sonst
        if text.lower() not in seen:
            seen.add(text.lower())
            out.append({"text": text, "level": level, "kind": kind})
    return out


def merge(train, route):
    """Meldungen am Zug (IRIS) und auf der Strecke (VRR) in eine Reihenfolge: rote Meldungen am Zug,
    dann Freitext der Bahn zu diesem Zug (der kennt die Störung schon und ist genauer), dann akute
    Streckenstörungen (die Vorwarnung), dann übrige Hinweise am Zug, zuletzt Baustellen auf der Strecke."""
    def rank(a):
        if a["source"] == "route":
            return {"acute": 2, "done": 3, "build": 5}.get(a["kind"], 5)
        if a["level"] == "high":
            return 0
        return 1 if a.get("kind") == "notice" else 4
    items = [dict(a, source="train") for a in train] + [dict(a, source="route") for a in route]
    return sorted(items, key=rank)  # stabil: innerhalb einer Stufe bleibt die bisherige Reihenfolge


def short_name(name):
    return re.sub(r"\s+Hbf$", "", name or "").strip()


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
        "note": f"endet in {short_name(dest)}" if shortened and not cancelled else "",
    }


def target_stop(session, srcs, cfg, plan, planned_dt):
    """Halt des Zuges am Ausstiegsbahnhof: (EVA, Name, Halt) oder None. Gesucht wird in den
    Sollfahrplänen der Abfahrtsstunde und der zwei Stunden danach; das Ergebnis gilt den Tag."""
    eva, name = station(session, srcs, cfg["target"])
    key = (planned_dt.date(), trip_key(plan["id"]), eva)
    if key not in _target_cache:
        for k in [k for k in _target_cache if k[0] != planned_dt.date()]:
            del _target_cache[k]
        hit = None
        for h in range(3):
            slot = (planned_dt + timedelta(hours=h)).strftime("%y%m%d%H")
            hit = find_stop(fetch(session, srcs, f"plan/{eva}/{slot[:6]}/{slot[6:]}"), key[1], plan["number"])
            if hit and hit["pt"] > planned_dt.strftime("%y%m%d%H%M"):
                break
            hit = None
        _target_cache[key] = hit
    return (eva, cfg["target"], _target_cache[key]) if _target_cache[key] else None


def arrival(root, name, stop, path, tz):
    """Ankunft am Ausstieg. Fehlt der Bahnhof im geänderten Laufweg, fällt der Halt aus."""
    ch = {}
    if root is not None:
        s = _stop(root, stop["id"])
        ch = _attrs(s.find("ar")) if s is not None else {}
    planned = iris_time(stop["pt"], tz)
    actual = iris_time(ch["ct"], tz) if ch.get("ct") else planned
    skipped = bool(path) and not any(short_name(p) == short_name(name) for p in path)
    return {"name": short_name(name), "planned": hm(planned), "actual": hm(actual),
            "delay": max(0, round((actual - planned).total_seconds() / 60)),
            "cancelled": ch.get("cs") == "c" or skipped,
            "platform": ch.get("cp") or stop["platform"],
            "platform_changed": bool(ch.get("cp")) and ch["cp"] != stop["platform"]}


def load(cfg, now, tz, client_id=None, api_key=None, session=None):
    """Live-Status des Zuges aus den Einstellungen. Wirft keine Fehler: Bei Problemen
    kommt ein Eintrag mit state "unknown" zurück, damit das Dashboard trotzdem erscheint.

    Zusätzlich (Störungsmonitor): Ankunft am Ausstieg und die Meldungen, die an diesem Zug
    in Abfahrts- und Ausstiegsbahnhof hängen – also nur, was genau diese Fahrt betrifft."""
    planned_dt = datetime.combine(now.date(), cfg["dep"], tzinfo=tz)
    base = {"label": cfg["label"], "planned": hm(planned_dt), "actual": hm(planned_dt), "dest": "",
            "platform": "", "platform_changed": False, "note": "", "delay": 0,
            "arrival": None, "alerts": []}
    session = session or requests.Session()
    srcs = sources(client_id, api_key)
    try:
        eva, _ = station(session, srcs, cfg["station"])
        pt = planned_dt.strftime("%y%m%d%H%M")
        plan_xml = fetch(session, srcs, f"plan/{eva}/{pt[:6]}/{pt[6:8]}")
        plan = find_planned(plan_xml, cfg["cat"], cfg["num"], pt)
        if plan is None:
            return dict(base, state="unknown", badge="nicht im Fahrplan",
                        note=f"{cfg['label']} um {hm(planned_dt)} heute nicht gefunden")
        try:
            root = ET.fromstring(fetch(session, srcs, f"fchg/{eva}"))
            s = _stop(root, plan["id"])
            changes = _attrs(s.find("dp")) if s is not None else {}
            live = True
        except (RuntimeError, ET.ParseError) as exc:
            logger.warning("Bahn-Änderungen nicht abrufbar: %s", exc)
            root, changes, live = None, {}, False
        out = dict(base, **status(plan, changes, planned_dt, now, tz))
        if not live:
            out.update(state="unknown", badge="ohne Live-Daten")
        msgs = find_messages(root, plan["id"]) + find_messages(ET.fromstring(plan_xml), plan["id"])

        until = planned_dt + timedelta(hours=2)
        if cfg.get("target") and short_name(cfg["target"]).lower() != short_name(cfg["station"]).lower():
            try:
                hit = target_stop(session, srcs, cfg, plan, planned_dt)
                if hit:
                    t_eva, t_name, t_stop = hit
                    try:
                        t_root = ET.fromstring(fetch(session, srcs, f"fchg/{t_eva}"))
                    except (RuntimeError, ET.ParseError) as exc:
                        logger.info("Änderungen am Ausstieg nicht abrufbar: %s", exc)
                        t_root = None
                    path = [p for p in (changes.get("cpth") or "").split("|") if p]
                    out["arrival"] = arrival(t_root, t_name, t_stop, path, tz)
                    until = iris_time(t_stop["pt"], tz)
                    msgs += find_messages(t_root, t_stop["id"])
            except (RuntimeError, ET.ParseError, ValueError) as exc:
                logger.info("Ausstieg %s nicht auswertbar: %s", cfg["target"], exc)

        if cfg.get("alerts", True):
            arr = out["arrival"] or {}
            delayed = out["delay"] >= 1 or out["state"] == "cancelled" or arr.get("delay", 0) >= 1 \
                or arr.get("cancelled", False)
            route = strecke.load(cfg, plan, now, until, tz, session) if cfg.get("route") else []
            out["alerts"] = merge(alerts(msgs, now, until, tz, delayed), route)
        if out["state"] == "cancelled":
            out["arrival"] = None  # fällt ganz aus: Ankunft ist dann bedeutungslos
        elif out["arrival"] and out["arrival"]["cancelled"] and out["state"] != "gone":
            # fährt, kommt aber nicht bis zum Ausstieg: das ist wichtiger als Pünktlichkeit
            out.update(state="partial", badge="Teilausfall")
        return out
    except (RuntimeError, ET.ParseError, ValueError) as exc:
        logger.warning("Zugdaten nicht verfügbar: %s", exc)
        return dict(base, state="unknown", badge="keine Daten", note="Bahn nicht erreichbar")
