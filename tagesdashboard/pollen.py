"""
Pollenflug: eine zusätzliche Wetter-Kachel, nur wenn mindestens eine ausgewählte Pollenart die
eingestellte Stufe erreicht (platzsparend – im Gegensatz zu Luftqualität/Radar/Zug keine eigene
Karte in der rechten Spalte, sondern eine schmale Kachel neben Wind, Böen & Co.). Eine eigene
Saison-Prüfung braucht es nicht: Außerhalb der jeweiligen Pollensaison meldet der DWD für eine Art
selbst "0" (keine Belastung), die Kachel erscheint dann von selbst nicht.

Quelle
------
DWD Pollenflug-Gefahrenindex: https://opendata.dwd.de/climate_environment/health/alerts/s31fg.json
Dokumentation: https://opendata.dwd.de/climate_environment/health/alerts/Beschreibung_pollen_s31fg.pdf
Einmal täglich aktualisiert (vormittags gegen 11 Uhr; freitags kommt die Vorhersage für Sonntag
dazu). `content[]` ist nach Region/Teilregion gegliedert:
  {"region_id": 40, "partregion_id": 41, "region_name": "Nordrhein-Westfalen",
   "partregion_name": "Rhein.-Westfäl. Tiefland",
   "Pollen": {"Graeser": {"today": "2", "tomorrow": "2-3", "dayafter_to": "-1"}, ...}}
Werte sind Strings auf einer Skala 0 (keine Belastung) – 3 (hohe Belastung), auch als Übergang
("1-2"); "-1" bedeutet keine Angabe. Bonn liegt in der Region Nordrhein-Westfalen (region_id 40),
Teilregion "Rhein.-Westfäl. Tiefland" (partregion_id 41) – die Niederrheinisch-Westfälische Bucht.

Acht Pollenarten (API-Schlüssel → Anzeige): Hasel, Erle, Esche, Birke, Graeser → Gräser, Roggen,
Beifuss → Beifuß, Ambrosia. In den Einstellungen einzeln abwählbar (pollenHasel … pollenAmbrosia).

Es wird immer der Wert für "today" verwendet (wie bei Radar und Luftqualität geht es um jetzt,
nicht um einen gewählten Fokus-Tag).

**Aus der Claude-Umgebung nicht erreichbar** (wie sensor.community, die UBA-Luftdaten-API und die
VRR-Auskunft) – nur gegen `dev/mock_pollen.py` getestet.
"""

import logging
import time as _time

import requests

logger = logging.getLogger(__name__)

URL = "https://opendata.dwd.de/climate_environment/health/alerts/s31fg.json"
DEFAULT_PARTREGION = "41"   # Rhein.-Westfäl. Tiefland (Bonn); Region Nordrhein-Westfalen = 40
CACHE_MIN = 60              # die Datei ändert sich nur einmal täglich
TIMEOUT = 15

TYPES = ("Hasel", "Erle", "Esche", "Birke", "Graeser", "Roggen", "Beifuss", "Ambrosia")
NAMES = {"Hasel": "Hasel", "Erle": "Erle", "Esche": "Esche", "Birke": "Birke",
         "Graeser": "Gräser", "Roggen": "Roggen", "Beifuss": "Beifuß", "Ambrosia": "Ambrosia"}
LEVEL_WORD = {1: "gering", 2: "mittel", 3: "hoch"}  # auch der CSS-Klassenname der Kachel (lvl-mittel/-hoch)

_cache = {}   # Schlüssel -> (monotonic, payload)


# ----------------------------------------------------------------------
# Einstellungen
# ----------------------------------------------------------------------
def read_config(opt, flag):
    if not flag("pollenEnabled"):
        return None
    level = (opt("pollenLevel") or "1").strip()
    level = level if level in ("1", "2", "3") else "1"
    types = [t for t in TYPES if flag(f"pollen{t}")]
    if not types:  # alle Arten abgewählt: nichts zu zeigen
        return None
    return {
        "level": int(level),
        "types": types,
        "partregion": (opt("pollenRegion") or "").strip() or DEFAULT_PARTREGION,
    }


# ----------------------------------------------------------------------
# Einstufung
# ----------------------------------------------------------------------
def classify(text):
    """"0".."3", auch Übergänge wie "1-2" → ganze Stufe 0–3 (der höhere Wert gilt, lieber einmal zu
    vorsichtig). "-1" oder unlesbar → None (keine Angabe, zählt nicht mit)."""
    if text is None:
        return None
    s = str(text).strip()
    if s in ("", "-1"):
        return None
    try:
        return max(0, min(3, round(float(s))))
    except ValueError:
        pass
    try:
        hi = max(float(p) for p in s.split("-"))
    except ValueError:
        return None
    return max(0, min(3, round(hi)))


# ----------------------------------------------------------------------
# Abruf
# ----------------------------------------------------------------------
def fetch_payload(session):
    r = session.get(URL, timeout=TIMEOUT)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    return r.json()


def find_region(entries, partregion):
    """Erst über die Teilregion, sonst (Regionen ohne Teilregion, z. B. Berlin/Brandenburg) über die Region."""
    for e in entries or []:
        if str(e.get("partregion_id")) == str(partregion):
            return e
    for e in entries or []:
        if str(e.get("region_id")) == str(partregion):
            return e
    return None


def load(cfg, now, session=None):
    """Rohdaten für die Wetter-Kachel oder None (unter der Schwelle, außerhalb der Saison oder
    keine Daten). `tagesdashboard.pollen_tile()` baut daraus die fertige Kachel (Icon, Text, CSS-Klasse)."""
    session = session or requests.Session()
    hit = _cache.get("pollen")
    if hit and _time.monotonic() - hit[0] < CACHE_MIN * 60:
        payload = hit[1]
    else:
        try:
            payload = fetch_payload(session)
        except Exception as exc:  # Pollen ist Zusatz: nie das ganze Bild verlieren
            logger.warning("Pollenflug nicht verfügbar: %s", exc)
            payload = None
        _cache["pollen"] = (_time.monotonic(), payload)
    if not payload:
        return None

    entries = payload.get("content") or []
    region = find_region(entries, cfg["partregion"])
    if region is None:
        logger.info("Pollenflug: Teilregion %s nicht gefunden. Verfügbare Teilregionen: %s",
                    cfg["partregion"], ", ".join(sorted({str(e.get("partregion_id")) for e in entries})))
        return None

    levels = {}
    for t in cfg["types"]:
        day = (region.get("Pollen") or {}).get(t) or {}
        lvl = classify(day.get("today"))
        if lvl:
            levels[t] = lvl
    if not levels:
        return None
    worst = max(levels.values())
    if worst < cfg["level"]:
        return None

    order = sorted(levels, key=lambda t: (-levels[t], TYPES.index(t)))
    lead = order[0]
    more = [t for t in order[1:] if levels[t] >= cfg["level"]]

    logger.info("Pollen: %s (Teilregion %s) → %s", {NAMES[t]: levels[t] for t in levels},
                region.get("partregion_name") or region.get("region_name"), LEVEL_WORD[worst])
    return {
        "level": worst,
        "word": LEVEL_WORD[worst],
        "lead": NAMES[lead],
        "more": len(more),
    }
