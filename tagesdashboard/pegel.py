"""
Rhein auf echtem Pegel (seit 1.28): Wasserstand am Pegel Bonn fürs Nachtbild.

Quelle
------
PEGELONLINE der Wasserstraßen- und Schifffahrtsverwaltung des Bundes (WSV), frei und ohne Schlüssel:
  https://www.pegelonline.wsv.de/webservices/rest-api/v2/stations/BONN/W/measurements.json?start=P1D
Antwort: Liste [{"timestamp": "2026-11-16T23:30:00+01:00", "value": 116.0}, …], Werte in cm am Pegel
Bonn (Rhein-km 654,8), alle 15 Minuten. Der letzte Eintrag ist der aktuelle Stand, der Eintrag von vor
etwa 24 Stunden dient dem Trend („seit gestern −4 cm“).

Das Nachtbild wird einmal pro Nacht gezeichnet; der Pegel wird also selten abgefragt. Trotzdem 30 Minuten
Zwischenspeicher (auch für Fehlschläge), damit „Jetzt aktualisieren“ den Dienst nicht jedes Mal fragt.

Was die Zahlen bedeuten (Stadt Bonn, bonn.de/hochwasser): ab 700 cm werden erste Uferbereiche
überschwemmt, ab 950 cm spricht die Stadt von „großem Hochwasser“ (Hochwasserschutz in Beuel wird
überflutet). Normal sind im Winter etwa 3,8 m, im Spätsommer etwa 2,5 m; der niedrigste je gemessene
Stand war 63 cm (August 2026). Diese Schwellen stecken nur in der Grafik (nachtgrafik.PEGEL_Y), Text
gibt es keinen – die Zahl steht an der Pegellatte.

Ohne Daten (Dienst nicht erreichbar, letzter Wert älter als MAX_AGE) liefert load() None, und der Rhein
im Nachtbild bleibt wie bisher (pixelgleich).
"""

import logging
import time as _time
from datetime import datetime, timedelta

import requests

try:
    from . import status
except ImportError:  # Tests importieren die Module ohne Paket
    import status

logger = logging.getLogger(__name__)

STATION = "BONN"
URL = "https://www.pegelonline.wsv.de/webservices/rest-api/v2/stations/{station}/W/measurements.json"
HEADERS = {"User-Agent": "InkyPi-Tagesdashboard/1.28 (privates E-Ink-Display; github.com/leonschwarze/InkyPi_Dashboard)"}
STATUS_NAME = "Pegel"
CACHE_MIN = 30
MAX_AGE = timedelta(hours=6)        # älter: lieber den Rhein wie bisher zeichnen als einen falschen Stand
TREND_CM = 5                        # ab so viel Änderung in 24 h zeigt die Latte einen Pfeil
TIMEOUT = 15

_cache = {}  # station -> (monotonic, messwerte | None)


def fetch(station=STATION, session=None):
    """Messwerte der letzten 24 Stunden: [(datetime, cm)], aufsteigend."""
    session = session or requests.Session()
    r = session.get(URL.format(station=station), params={"start": "P1D"}, headers=HEADERS, timeout=TIMEOUT)
    if r.status_code != 200:
        raise RuntimeError(f"PEGELONLINE: HTTP {r.status_code}")
    out = []
    for m in r.json():
        try:
            out.append((datetime.fromisoformat(m["timestamp"]), float(m["value"])))
        except (KeyError, TypeError, ValueError):
            continue
    out.sort(key=lambda v: v[0])
    return out


def summarize(values, now):
    """Aktueller Stand und Änderung zu gestern, oder None, wenn es keinen frischen Wert gibt."""
    if not values:
        return None
    when, cm = values[-1]
    if now - when > MAX_AGE:
        logger.info("Pegel: letzter Wert von %s ist zu alt", when.isoformat())
        return None
    # Wert von vor etwa 24 Stunden (höchstens 3 Stunden daneben), sonst kein Trend
    target = when - timedelta(hours=24)
    old = min(values, key=lambda v: abs((v[0] - target).total_seconds()))
    diff = cm - old[1] if abs(old[0] - target) <= timedelta(hours=3) else None
    trend = 0
    if diff is not None and abs(diff) >= TREND_CM:
        trend = 1 if diff > 0 else -1
    return {"cm": cm, "when": when, "diff": diff, "trend": trend, "label": label(cm)}


def label(cm):
    """„1,16 m“ – zwei Nachkommastellen, deutsches Komma."""
    return f"{cm / 100:.2f}".replace(".", ",") + " m"


def load(now, station=STATION, session=None):
    """Pegel fürs Nachtbild oder None."""
    status.use(STATUS_NAME)
    hit = _cache.get(station)
    if hit and _time.monotonic() - hit[0] < CACHE_MIN * 60:
        values = hit[1]
    else:
        try:
            values = fetch(station, session)
            status.ok(STATUS_NAME)
        except Exception as exc:  # Zusatz: nie das ganze Bild verlieren
            logger.warning("Pegel: PEGELONLINE nicht verfügbar: %s", exc)
            status.fail(STATUS_NAME, exc)
            values = None
        _cache[station] = (_time.monotonic(), values)
    info = summarize(values, now) if values else None
    if info:
        logger.info("Pegel: %s %d cm (%s seit gestern)", station.title(), round(info["cm"]),
                    "?" if info["diff"] is None else f"{info['diff']:+.0f} cm")
    return info


def reset():
    """Zwischenspeicher leeren (Tests)."""
    _cache.clear()
