"""
Warnungen des Bevölkerungsschutzes aus NINA (seit 1.38): Bombenentschärfung, Trinkwasser, Großbrand …

Quelle
------
Die Warn-App NINA des Bundesamts für Bevölkerungsschutz (BBK) hat eine offene Schnittstelle, ohne Key
(Dokumentation: github.com/bundesAPI/nina-api):

  https://warnung.bund.de/api31/dashboard/{ARS}.json
      alle aktuellen Warnungen eines Kreises. ARS = Amtlicher Regionalschlüssel mit zwölf Stellen, die
      letzten sieben immer „0000000“ (NINA kennt nur Kreise). Bonn = 05314 → 053140000000.
      Eintrag: {"id": "mow.DE-NW-BN-…", "payload": {"version": 3, "data": {"headline": …, "provider":
      "MOWAS"|"KATWARN"|"BIWAPP"|"DWD"|"LHP"|"POLICE", "severity": "Minor"|"Moderate"|"Severe"|"Extreme",
      "msgType": "Alert"|"Update"|"Cancel", "valid": true, …}}, "i18nTitle": {"de": …}, "sent": "2026-…+01:00"}
  https://warnung.bund.de/api31/warnings/{id}.json
      die Meldung im CAP-Format: info[] je Sprache mit headline, description, instruction (HTML mit <br/>)
  https://warnung.bund.de/api31/warnings/{id}.geojson
      das Warngebiet als FeatureCollection (Polygon/MultiPolygon, Koordinaten [lon, lat])

Gilt die Warnung für mich?
--------------------------
Der Kreis ist zu grob: Eine Bombenentschärfung in Beuel betrifft die Weststadt nicht. Deshalb wird das
Warngebiet (GeoJSON) gegen den Wetter-Ort geprüft (Punkt im Polygon). Ohne Gebiet gilt die Warnung als
„betrifft dich“ – lieber einmal zu viel warnen.

Was weggelassen wird
--------------------
* Warnungen, deren Gebiet den Wetter-Ort nicht enthält (Leons Wahl: „nicht bei dir“ weglassen).
* DWD-Unwetterwarnungen: zeigt das Dashboard schon (Bright Sky, Kasten im Wetterbereich).
* Entwarnungen (msgType „Cancel“) und als ungültig markierte Meldungen.

Abruf höchstens alle CACHE_MIN Minuten (auch Fehlschläge), Details und Gebiete je Version der Meldung
im Speicher. Statusname „Warnungen“.

Abruf vor dem Bild-Cache
------------------------
Das Dashboard liefert bis zu 15 Minuten dasselbe Bild, das Nachtbild sogar bis 6 Uhr. Eine Warnung soll
trotzdem beim nächsten Takt erscheinen. Deshalb ruft generate_image load() schon vor den Bild-Caches auf
und vergleicht signature() mit der des gespeicherten Bildes. Weil das vor status.begin() geschieht,
merkt sich load() das Ergebnis eines echten Abrufs (_pending) und meldet es erst beim nächsten Aufruf
innerhalb einer Runde (report_status()) – sonst ginge ein Ausfall der Statusanzeige verloren.
"""

import html
import logging
import re
import time as _time
from datetime import datetime

import requests

try:
    from . import status
except ImportError:  # Tests importieren die Module ohne Paket
    import status

logger = logging.getLogger(__name__)

API = "https://warnung.bund.de/api31"
DEFAULT_ARS = "05314"  # Bonn
HEADERS = {"User-Agent": "InkyPi-Tagesdashboard/1.38 (privates E-Ink-Display; github.com/leonschwarze/InkyPi_Dashboard)"}
STATUS_NAME = "Warnungen"
CACHE_MIN = 10
TIMEOUT = 15
SKIP_PROVIDERS = {"DWD"}
SEVERITY = {"Extreme": 4, "Severe": 3, "Moderate": 2, "Minor": 1}

_cache = {}    # ars -> (monotonic, einträge | None)
_pending = {}  # ars -> ("ok", "") | ("fail", grund): Ergebnis des letzten echten Abrufs, noch nicht gemeldet
_details = {}  # (id, version) -> {"instruction": str, "area": [polygone] | None}


def read_ars(raw):
    """Regionalschlüssel aus der Einstellung: Ziffern, auf den Kreis gekürzt, mit Nullen auf 12 Stellen.
    „05314“, „053140000000“ und „05 314 000“ ergeben alle 053140000000. Ungültig → Bonn."""
    digits = re.sub(r"\D", "", str(raw or ""))
    if len(digits) < 5:
        digits = DEFAULT_ARS
    return digits[:5] + "0000000"


# ---------------------------------------------------------------------------
# Punkt im Polygon
# ---------------------------------------------------------------------------
def _in_ring(lon, lat, ring):
    """Strahlverfahren: Wie oft schneidet ein Strahl nach Osten die Kanten? Ungerade = innen."""
    inside = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        if (y1 > lat) != (y2 > lat):
            x = x1 + (lat - y1) * (x2 - x1) / (y2 - y1)
            if x > lon:
                inside = not inside
    return inside


def _polygons(geo):
    """Alle Polygone (Liste von Ringen) aus einer GeoJSON-Struktur, egal wie verschachtelt."""
    if not isinstance(geo, dict):
        return []
    kind = geo.get("type")
    if kind == "FeatureCollection":
        return [p for f in geo.get("features") or [] for p in _polygons(f)]
    if kind == "Feature":
        return _polygons(geo.get("geometry"))
    if kind == "GeometryCollection":
        return [p for g in geo.get("geometries") or [] for p in _polygons(g)]
    if kind == "Polygon":
        return [geo.get("coordinates") or []]
    if kind == "MultiPolygon":
        return list(geo.get("coordinates") or [])
    return []


def contains(polygons, lat, lon):
    """Liegt (lat, lon) in einem der Polygone? Erster Ring = Außenrand, weitere = Löcher."""
    for rings in polygons:
        if rings and _in_ring(lon, lat, rings[0]) and not any(_in_ring(lon, lat, h) for h in rings[1:]):
            return True
    return False


# ---------------------------------------------------------------------------
# Abruf
# ---------------------------------------------------------------------------
def _get_json(session, path):
    r = session.get(f"{API}/{path}", headers=HEADERS, timeout=TIMEOUT)
    if r.status_code != 200:
        raise RuntimeError(f"NINA: HTTP {r.status_code} für {path}")
    return r.json()


def first_sentence(text, limit=90):
    """Erster Satz der Handlungsempfehlung, ohne HTML. Zu lang → None (dann lieber nichts)."""
    if not text:
        return None
    plain = html.unescape(re.sub(r"<[^>]+>", " ", text))
    plain = re.sub(r"\s+", " ", plain).strip()
    m = re.match(r"(.+?[.!])(\s|$)", plain)
    s = (m.group(1) if m else plain).strip()
    return s if 0 < len(s) <= limit else None


def details(session, wid, version):
    """Handlungsempfehlung und Gebiet einer Meldung (je Version gemerkt)."""
    key = (wid, version)
    if key in _details:
        return _details[key]
    out = {"instruction": None, "area": None}
    try:
        cap = _get_json(session, f"warnings/{wid}.json")
        infos = cap.get("info") or []
        de = next((i for i in infos if str(i.get("language", "")).lower().startswith("de")), infos[0] if infos else {})
        out["instruction"] = first_sentence(de.get("instruction"))
    except Exception as exc:
        logger.info("Warnungen: Details zu %s nicht lesbar: %s", wid, exc)
    try:
        polys = _polygons(_get_json(session, f"warnings/{wid}.geojson"))
        out["area"] = polys or None
    except Exception as exc:
        logger.info("Warnungen: Gebiet zu %s nicht lesbar: %s", wid, exc)
    _details[key] = out
    return out


def fetch(ars, session=None):
    """Rohe Einträge des Kreises (ohne DWD, ohne Entwarnungen)."""
    session = session or requests.Session()
    out = []
    for it in _get_json(session, f"dashboard/{ars}.json") or []:
        pl = it.get("payload") or {}
        data = pl.get("data") or {}
        if data.get("provider") in SKIP_PROVIDERS or data.get("msgType") == "Cancel" or data.get("valid") is False:
            continue
        title = ((it.get("i18nTitle") or {}).get("de") or data.get("headline") or "").strip()
        if not title:
            continue
        try:
            sent = datetime.fromisoformat(it.get("sent"))
        except (TypeError, ValueError):
            sent = None
        out.append({"id": it.get("id") or pl.get("id"), "version": pl.get("version"), "title": title,
                    "provider": data.get("provider") or "", "severity": data.get("severity") or "",
                    "sent": sent})
    return out


def load(ars, lat, lon, session=None):
    """Aktuelle Warnungen für den Wetter-Ort, wichtigste zuerst.

    Jede Warnung: title, instruction (erster Satz oder None), here (True = Ort liegt im Warngebiet,
    None = Gebiet unbekannt → gilt), level ("rot"/"gelb"), rank, sent (datetime), id, version, provider,
    severity. Warnungen anderswo im Kreis fallen weg.
    """
    session = session or requests.Session()
    hit = _cache.get(ars)
    if hit and _time.monotonic() - hit[0] < CACHE_MIN * 60:
        raw = hit[1]
    else:
        try:
            raw = fetch(ars, session)
            _pending[ars] = ("ok", "")
        except Exception as exc:  # Zusatz: nie das ganze Bild verlieren
            logger.warning("Warnungen: NINA nicht erreichbar: %s", exc)
            _pending[ars] = ("fail", str(exc))
            raw = None
        _cache[ars] = (_time.monotonic(), raw)
    if not raw:
        return []
    out = []
    for w in raw:
        d = details(session, w["id"], w["version"])
        here = None
        if d["area"] and lat is not None and lon is not None:
            here = contains(d["area"], lat, lon)
        sev = SEVERITY.get(w["severity"], 2)
        if here is False:
            logger.info("Warnungen: %s gilt nicht am Wetter-Ort – weggelassen", w["title"])
            continue
        out.append(dict(w, instruction=d["instruction"], here=here,
                        level="rot" if sev >= 2 else "gelb", rank=sev))
    out.sort(key=lambda w: (-w["rank"], -(w["sent"].timestamp() if w["sent"] else 0)))
    return out


def report_status(ars):
    """In der laufenden Runde melden, ob NINA gebraucht wurde und wie der letzte echte Abruf ausging."""
    kind, detail = _pending.pop(ars, ("use", ""))
    if kind == "ok":
        status.ok(STATUS_NAME)
    elif kind == "fail":
        status.fail(STATUS_NAME, detail)
    else:
        status.use(STATUS_NAME)


def signature(warnings):
    """Kurzer Schlüssel der gezeigten Warnungen – ändert er sich, muss das Bild neu (Nachtbild-Cache)."""
    return "|".join(f"{w['id']}:{w['version']}" for w in warnings)


def since_text(w, tz):
    """„seit 6:40“ (Zeit der Meldung in Ortszeit) oder ""."""
    return f"seit {w['sent'].astimezone(tz):%H:%M}".replace("seit 0", "seit ") if w.get("sent") else ""


def reset():
    """Zwischenspeicher leeren (Tests)."""
    _cache.clear()
    _details.clear()
    _pending.clear()
