"""
Regenradar: Niederschlag der nächsten zwei Stunden am Wetter-Ort.

Quelle: DWD-Radarkomposit RV über Bright Sky (https://api.brightsky.dev/radar), ohne Schlüssel.
  * 1 Bildpunkt = 1 km², Werte in 0,01 mm je 5 Minuten (45 = 0,45 mm in 5 min = 5,4 mm/Std.)
  * Bilder im 5-Minuten-Takt: Messung bis jetzt, danach Vorhersage (Nowcast) für 2 Stunden
  * lat/lon liegen im mittleren Bildpunkt; distance = Meter vom Mittelpunkt bis zum Rand

Für den Ort zählt nicht nur der eine Bildpunkt, sondern der stärkste Wert im Umkreis von
POINT_R km: Radar und Vorhersage sind auf etwa einen Kilometer unscharf, und "sicher trocken"
soll lieber einmal zu vorsichtig sein.
"""

import base64
import logging
import sys
import time as _time
import zlib
from array import array
from datetime import datetime, timedelta

import requests

logger = logging.getLogger(__name__)

API = "https://api.brightsky.dev/radar"
DIST_M = 2000       # Ausschnitt ±2 km → 5×5 Bildpunkte (klein halten: die volle Karte wären MB)
POINT_R = 1         # Umkreis in km (Bildpunkten) für den Wert am Ort
WET_MMH = 0.2       # ab hier zählt es als Regen (mm/Std.); darunter ist es Radarrauschen
DRY_GAP_MIN = 15    # kürzere Pausen gehören noch zum selben Regen
HORIZON_MIN = 120
SCALE_MMH = 4.0     # Balken voll hoch (wie RAIN_SCALE der Tageskurve)
CACHE_MIN = 4       # RV kommt alle 5 Minuten
TIMEOUT = 10
HEADERS = {"User-Agent": "InkyPi-Tagesdashboard (privates E-Ink-Display)"}

# Stufen wie in der Tageskurve (mm/Std.)
LEVELS = [(1.0, "leicht"), (4.0, "maessig"), (float("inf"), "stark")]
LEVEL_TEXT = {"leicht": "leicht", "maessig": "mäßig", "stark": "stark"}

_cache = {}


# ----------------------------------------------------------------------
# Abruf
# ----------------------------------------------------------------------
def _decode(raw, h, w):
    """compressed: base64 → zlib → 2-Byte-Ganzzahlen (Little Endian) → Zeilen."""
    data = array("h")
    data.frombytes(zlib.decompress(base64.b64decode(raw)))
    if sys.byteorder == "big":
        data.byteswap()
    return [list(data[r * w:(r + 1) * w]) for r in range(h)]


def fetch(lat, lon, now, session=None):
    """Liefert [(zeit, gitter)] ab jetzt; gitter[zeile][spalte], Zeile 0 = Norden."""
    key = (round(lat, 3), round(lon, 3))
    hit = _cache.get(key)
    if hit and _time.monotonic() - hit[0] < CACHE_MIN * 60:
        return hit[1]
    start = now.replace(second=0, microsecond=0) - timedelta(minutes=now.minute % 5 + 5)
    params = {"lat": f"{lat:.4f}", "lon": f"{lon:.4f}", "distance": DIST_M, "format": "compressed",
              "date": start.isoformat(), "last_date": (start + timedelta(minutes=HORIZON_MIN + 10)).isoformat(),
              "tz": str(now.tzinfo)}
    session = session or requests.Session()
    r = session.get(API, params=params, headers=HEADERS, timeout=TIMEOUT)
    if r.status_code != 200:
        raise RuntimeError(f"Radar: HTTP {r.status_code}")
    size = 2 * (DIST_M // 1000) + 1
    frames = []
    for fr in r.json().get("radar", []):
        t = datetime.fromisoformat(fr["timestamp"]).astimezone(now.tzinfo)
        frames.append((t, _decode(fr["precipitation_5"], size, size)))
    frames.sort(key=lambda f: f[0])
    _cache[key] = (_time.monotonic(), frames)
    return frames


# ----------------------------------------------------------------------
# Auswertung
# ----------------------------------------------------------------------
def mmh(value):
    """0,01 mm je 5 min → mm/Std."""
    return value * 0.12


def level(rate):
    return next(name for limit, name in LEVELS if rate < limit)


def at_home(grid, r=POINT_R):
    c = len(grid) // 2
    return max(mmh(grid[y][x]) for y in range(c - r, c + r + 1) for x in range(c - r, c + r + 1))


def series(frames, now):
    """[(zeit, mm/Std.)] von jetzt bis +2 Std. am Ort."""
    return [(t, at_home(g)) for t, g in frames if now - timedelta(minutes=5) < t <= now + timedelta(minutes=HORIZON_MIN)]


def episodes(points):
    """Regenabschnitte [(beginn, ende, max mm/Std.)]; kurze Pausen werden überbrückt.
    beginn = Anfang des ersten nassen 5-Minuten-Schritts, ende = None, wenn es bis zum Horizont regnet."""
    eps, cur, dry = [], None, 0
    for i, (t, v) in enumerate(points):
        if v >= WET_MMH:
            if cur is None:
                cur = [t - timedelta(minutes=5) if i else t, None, v]
            cur[2], dry = max(cur[2], v), 0
            cur[1] = t
        elif cur is not None:
            dry += 5
            if dry >= DRY_GAP_MIN:
                eps.append(tuple(cur))
                cur, dry = None, 0
    if cur is not None:
        cur[1] = None if dry == 0 else cur[1]
        eps.append(tuple(cur))
    return eps


def _hm(t):
    return f"{t.hour}:{t.minute:02d}"


def summary(frames, now, word="Regen"):
    """Was die nächsten zwei Stunden bringen – None, wenn es trocken bleibt.
    word: "Regen", "Schnee" oder "Niederschlag" (das Radar kennt die Art nicht, sie kommt aus der Vorhersage)."""
    pts = series(frames, now)
    if len(pts) < 6:
        return None
    eps = episodes(pts)
    if not eps:
        return None
    begin, end, _ = eps[0]
    now_wet = begin <= now + timedelta(minutes=5)
    lv = level(max(e[2] for e in eps))
    if now_wet:
        top = f"{word} hält an" if end is None else f"{word} bis etwa {_hm(end)}"
    else:
        top = f"{word} ab {_hm(begin)}" if end is None else f"{word} {_hm(begin)}–{_hm(end)}"
    after = ""
    if len(eps) > 1:
        b2, e2, _ = eps[1]
        after = f"ab {_hm(b2)} wieder" if e2 is None else f"wieder {_hm(b2)}–{_hm(e2)}"
    elif end is not None:
        after = "danach trocken bis " + _hm(pts[-1][0])
    return {
        "state": "jetzt" if now_wet else "kommt",
        "top": top,
        "after": after,
        "level": lv,
        "level_text": LEVEL_TEXT[lv],
        "points": pts,
        "episodes": eps,
        "strip": strip(pts),
    }


# ----------------------------------------------------------------------
# Darstellung
# ----------------------------------------------------------------------
def strip(pts, width=240, height=40):
    """Balkenband: ein Balken je 5 Minuten, Höhe = Stärke (feste Skala wie die Tageskurve: 4 mm/Std. = voll).
    Ticks an vollen Stunden (Position als Prozent der Breite)."""
    n = len(pts)
    slot = width / n
    bars = []
    for i, (t, v) in enumerate(pts):
        if v < WET_MMH:
            continue
        h = height * max(min(v / SCALE_MMH, 1.0), 0.28)  # auch Niesel bleibt sichtbar
        bars.append(f'<rect class="rd-bar {level(v)}" x="{i * slot + slot * 0.1:.1f}" y="{height - h:.1f}" '
                    f'width="{slot * 0.8:.1f}" height="{h:.1f}"/>')
    ticks = []
    for i, (t, _) in enumerate(pts):
        x = (i + 1) * slot / width * 100
        if t.minute == 0 and 22 < x < 88:  # nicht in "jetzt" hinein und nicht über den Rand
            ticks.append({"x": x, "text": f"{t.hour}"})
    svg = (f'<svg class="rd-strip" viewBox="0 0 {width} {height}" preserveAspectRatio="none">'
           + "".join(bars)
           + f'<line class="rd-axis" x1="0" y1="{height}" x2="{width}" y2="{height}" vector-effect="non-scaling-stroke"/>'
           + "</svg>")
    return {"svg": svg, "ticks": ticks}
