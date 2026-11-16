"""ISS-Überflug im Nachtbild (seit 1.23): Der nächste gut sichtbare Überflug als Textzeile und
als gestrichelte Bahn mit kleiner Station über der Silhouette.

Sichtbar heißt: Die ISS steht über dem Horizont, wird noch von der Sonne beschienen, und bei uns
ist es schon dunkel genug (Sonne mindestens 6° unter dem Horizont). Das passiert in der
Dämmerung, im Winter also abends gegen 17–20 Uhr und morgens gegen 5–7 Uhr. Gezeigt werden nur
Überflüge, die hoch genug steigen (MIN_EL) und hell genug sind (MAX_MAG) – sonst steht die Zeile
Woche für Woche im Bild, und man sieht sie doch nicht.

Quelle der Bahndaten
--------------------
Celestrak (https://celestrak.org), Allgemeine Bahndaten (GP) der ISS im TLE-Format:
  https://celestrak.org/NORAD/elements/gp.php?CATNR=25544&FORMAT=TLE
Celestrak sperrt (HTTP 403), wenn dieselben Daten öfter als alle 2 Stunden geladen werden. Darum
lädt dieses Modul höchstens alle `REFRESH_H` = 2 Stunden – auch nach einem Fehlschlag nicht
früher – und legt die letzte Antwort zusätzlich in eine Datei im Temp-Ordner, damit ein Neustart
von InkyPi nicht sofort wieder lädt. Eine ältere Bahn bleibt bis zu `MAX_AGE_D` = 7 Tage brauchbar
(die Zeitfehler wachsen mit dem Alter, aber auf eine Minute genau reicht für eine Textzeile).

Rechnung
--------
* Bahn: `lib/sgp4` (reine Python-Kopie der Bibliothek sgp4, MIT-Lizenz, keine Installation auf dem Pi),
  alle `STEP_S` = 10 Sekunden für die nächsten `HORIZON_H` Stunden.
* Koordinaten: TEME → fest mit der Erde (Sternzeit nach IAU 1982) → Himmelsrichtung/Höhe am Ort.
  Polbewegung und Nutation bleiben unberücksichtigt (Fehler unter 0,1°).
* Sonne: einfache Formel (Meeus), Fehler unter 0,02° – für „Sonne 6° unter dem Horizont“ weit genug.
* Erdschatten: Zylinder mit Erdradius (der Halbschatten dauert bei der ISS nur Sekunden).
* Helligkeit: geschätzt aus Entfernung und Beleuchtungswinkel (diffuse Kugel, −1,8 mag bei
  1000 km und halber Beleuchtung). Das trifft die Größenordnung (± 1 mag), nicht jede Messung.

Ein Überflug (dict): start, peak, end (datetime, mit Zeitzone des `now`), start_az, peak_az,
end_az (Grad, 0 = Nord), peak_el (Grad), mag (kleiner = heller), shadow (datetime oder None:
die ISS verschwindet im Erdschatten, statt unterzugehen), shadow_az, path [(az, el), …].
"""
import logging
import math
import os
import tempfile
import time as _time
from datetime import datetime, timedelta, timezone

import requests

try:
    from .lib.sgp4.api import Satrec, WGS72, jday
    from . import status
except ImportError:  # Tests importieren die Module ohne Paket
    from lib.sgp4.api import Satrec, WGS72, jday
    import status

logger = logging.getLogger(__name__)

URL = "https://celestrak.org/NORAD/elements/gp.php?CATNR=25544&FORMAT=TLE"
REFRESH_H = 2       # Celestrak sperrt bei häufigeren Abrufen
MAX_AGE_D = 7       # ältere Bahndaten werden nicht mehr benutzt
TIMEOUT = 15
CACHE_FILE = os.path.join(tempfile.gettempdir(), "inkypi_iss_tle.txt")

HORIZON_H = 30      # so weit voraus wird gerechnet (reicht von heute Abend bis morgen früh)
STEP_S = 10         # Zeitschritt der Rechnung
MIN_SEEN_EL = 10    # darunter verdeckt der Horizont (Häuser, Bäume, Dunst) fast immer
SUN_DARK = -6.0     # Sonne mindestens so tief: bürgerliche Dämmerung
MIN_EL = 25         # nur Überflüge, die hoch genug steigen
MAX_MAG = -1.5      # … und hell genug sind

R_EARTH = 6371.0
WGS84_A, WGS84_F = 6378.137, 1 / 298.257223563

DIRS = ["Nord", "Nordost", "Ost", "Südost", "Süd", "Südwest", "West", "Nordwest"]
DIRS_SHORT = ["N", "NO", "O", "SO", "S", "SW", "W", "NW"]

_tle = {"lines": None, "epoch": None, "tried": None}     # tried: time.monotonic() des letzten Abrufs
_passes_cache = {}


# ----------------------------------------------------------------------
# Bahndaten (TLE)
# ----------------------------------------------------------------------
def parse_tle(text):
    """Die zwei Datenzeilen aus einer Celestrak-Antwort (mit oder ohne Namenszeile) oder None."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    for i, ln in enumerate(lines[:-1]):
        if ln.startswith("1 25544") and lines[i + 1].startswith("2 25544"):
            return ln, lines[i + 1]
    return None


def tle_epoch(line1):
    """Zeitpunkt der Bahnmessung (UTC) aus Zeile 1: Spalten 19–32 = Jahr (2 Stellen) + Tag des Jahres."""
    yy = int(line1[18:20])
    day = float(line1[20:32])
    year = 2000 + yy if yy < 57 else 1900 + yy
    return datetime(year, 1, 1, tzinfo=timezone.utc) + timedelta(days=day - 1)


def _save_cache(lines):
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except OSError:
        pass  # nur eine Zugabe


def _load_cache():
    try:
        mtime = os.path.getmtime(CACHE_FILE)
        with open(CACHE_FILE, encoding="utf-8") as f:
            lines = parse_tle(f.read())
    except OSError:
        return None, None
    return lines, mtime


def get_tle(now, session=None):
    """Aktuelle Bahndaten (line1, line2) oder None. Lädt höchstens alle REFRESH_H Stunden."""
    mono = _time.monotonic()
    if _tle["lines"] is None and _tle["tried"] is None:      # frischer Start: erst die Datei fragen
        lines, mtime = _load_cache()
        if lines:
            _tle["lines"], _tle["epoch"] = lines, tle_epoch(lines[0])
            age_h = (_time.time() - mtime) / 3600
            _tle["tried"] = mono - age_h * 3600              # Dateialter zählt als letzter Abruf
    due = _tle["tried"] is None or mono - _tle["tried"] >= REFRESH_H * 3600
    status.use("ISS")
    if due:
        _tle["tried"] = mono
        try:
            r = (session or requests.Session()).get(URL, timeout=TIMEOUT, headers={"User-Agent": "InkyPi-Tagesdashboard"})
            if r.status_code != 200:
                raise RuntimeError(f"HTTP {r.status_code}")
            lines = parse_tle(r.text)
            if not lines:
                raise RuntimeError("keine Bahndaten in der Antwort")
            _tle["lines"], _tle["epoch"] = lines, tle_epoch(lines[0])
            _save_cache(lines)
            status.ok("ISS")
        except Exception as exc:  # ISS ist Zusatz: nie das ganze Bild verlieren
            logger.warning("ISS-Bahndaten nicht verfügbar: %s", exc)
            status.fail("ISS", exc)
    if not _tle["lines"]:
        return None
    if now.astimezone(timezone.utc) - _tle["epoch"] > timedelta(days=MAX_AGE_D):
        logger.info("ISS-Bahndaten sind älter als %d Tage – kein Überflug", MAX_AGE_D)
        return None
    return _tle["lines"]


# ----------------------------------------------------------------------
# Astronomie
# ----------------------------------------------------------------------
def gmst(jd):
    """Greenwich-Sternzeit in Radiant (IAU 1982)."""
    t = (jd - 2451545.0) / 36525.0
    sec = 67310.54841 + (876600 * 3600 + 8640184.812866) * t + 0.093104 * t * t - 6.2e-6 * t ** 3
    return math.radians((sec % 86400) / 240.0) % (2 * math.pi)


def sun_eci(jd):
    """Richtung zur Sonne (Einheitsvektor, äquatorial ≈ TEME) und Rektaszension/Deklination (Radiant)."""
    n = jd - 2451545.0
    L = math.radians((280.460 + 0.9856474 * n) % 360)
    g = math.radians((357.528 + 0.9856003 * n) % 360)
    lam = L + math.radians(1.915) * math.sin(g) + math.radians(0.020) * math.sin(2 * g)
    eps = math.radians(23.439 - 0.0000004 * n)
    ra = math.atan2(math.cos(eps) * math.sin(lam), math.cos(lam))
    dec = math.asin(math.sin(eps) * math.sin(lam))
    return (math.cos(dec) * math.cos(ra), math.cos(dec) * math.sin(ra), math.sin(dec)), ra, dec


def sun_elevation(jd, lat, lon):
    """Höhe der Sonne über dem Horizont in Grad (ohne Refraktion). lon: Ost positiv."""
    _, ra, dec = sun_eci(jd)
    H = gmst(jd) + math.radians(lon) - ra
    phi = math.radians(lat)
    return math.degrees(math.asin(math.sin(phi) * math.sin(dec) + math.cos(phi) * math.cos(dec) * math.cos(H)))


def observer_ecef(lat, lon, alt_km=0.0):
    phi, lam = math.radians(lat), math.radians(lon)
    e2 = WGS84_F * (2 - WGS84_F)
    n = WGS84_A / math.sqrt(1 - e2 * math.sin(phi) ** 2)
    return ((n + alt_km) * math.cos(phi) * math.cos(lam),
            (n + alt_km) * math.cos(phi) * math.sin(lam),
            (n * (1 - e2) + alt_km) * math.sin(phi))


def look_angles(sat_ecef, obs_ecef, lat, lon):
    """(Azimut, Höhe in Grad, Entfernung in km) der Satellitenposition vom Beobachter aus."""
    dx, dy, dz = (sat_ecef[i] - obs_ecef[i] for i in range(3))
    phi, lam = math.radians(lat), math.radians(lon)
    e = -math.sin(lam) * dx + math.cos(lam) * dy
    n = -math.sin(phi) * math.cos(lam) * dx - math.sin(phi) * math.sin(lam) * dy + math.cos(phi) * dz
    u = math.cos(phi) * math.cos(lam) * dx + math.cos(phi) * math.sin(lam) * dy + math.sin(phi) * dz
    rng = math.sqrt(dx * dx + dy * dy + dz * dz)
    return math.degrees(math.atan2(e, n)) % 360, math.degrees(math.asin(u / rng)), rng


def in_shadow(r, sun):
    """Liegt die Position r (TEME, km) im Zylinderschatten der Erde? sun = Einheitsvektor zur Sonne."""
    proj = r[0] * sun[0] + r[1] * sun[1] + r[2] * sun[2]
    if proj >= 0:
        return False
    d2 = r[0] ** 2 + r[1] ** 2 + r[2] ** 2 - proj * proj
    return d2 < R_EARTH ** 2


def magnitude(rng, r, sun, obs_eci):
    """Geschätzte Helligkeit. Beleuchtungswinkel = Winkel Sonne–ISS–Beobachter."""
    to_obs = [obs_eci[i] - r[i] for i in range(3)]
    d = math.sqrt(sum(c * c for c in to_obs))
    cosphi = max(-1.0, min(1.0, sum(sun[i] * to_obs[i] for i in range(3)) / d))
    phi = math.acos(cosphi)
    fraction = math.sin(phi) + (math.pi - phi) * math.cos(phi)    # = π · Φ(φ), 1 bei φ = 90°
    return -1.8 + 5 * math.log10(rng / 1000.0) - 2.5 * math.log10(max(fraction, 1e-3))


# ----------------------------------------------------------------------
# Überflüge
# ----------------------------------------------------------------------
def compute_passes(lines, start_utc, hours, lat, lon, step_s=STEP_S):
    """Alle sichtbaren Überflüge ab start_utc (aware, UTC) in den nächsten `hours` Stunden.
    Reine Rechnung ohne Netz und Uhr – so lässt sie sich mit einer festen Bahn testen."""
    sat = Satrec.twoline2rv(lines[0], lines[1], WGS72)
    obs = observer_ecef(lat, lon)
    steps = int(hours * 3600 / step_s)
    segs, cur, last_i = [], None, None
    for i in range(steps + 1):
        t = start_utc + timedelta(seconds=i * step_s)
        jd, fr = jday(t.year, t.month, t.day, t.hour, t.minute, t.second + t.microsecond / 1e6)
        jdt = jd + fr
        err, r, _v = sat.sgp4(jd, fr)
        seen = False
        if err == 0:
            gm = gmst(jdt)
            c, s = math.cos(gm), math.sin(gm)
            ecef = (c * r[0] + s * r[1], -s * r[0] + c * r[1], r[2])           # TEME → fest mit der Erde
            az, el, rng = look_angles(ecef, obs, lat, lon)
            if el >= MIN_SEEN_EL:
                sun, _, _ = sun_eci(jdt)
                lit = not in_shadow(r, sun)
                dark = sun_elevation(jdt, lat, lon) <= SUN_DARK
                if lit and dark:
                    seen = True
                    ox = (c * obs[0] - s * obs[1], s * obs[0] + c * obs[1], obs[2])    # Beobachter in TEME
                    mag = magnitude(rng, r, sun, ox)
                    if cur is None or last_i != i - 1:
                        cur = {"pts": []}
                        segs.append(cur)
                    cur["pts"].append((t, az, el, mag))
                    last_i = i
                    cur["ended_by_shadow"] = False
                elif cur is not None and last_i == i - 1 and not lit and dark:
                    cur["ended_by_shadow"] = True                                  # gerade im Schatten verschwunden
    out = []
    for seg in segs:
        pts = seg["pts"]
        peak = max(pts, key=lambda p: p[2])
        brightest = min(p[3] for p in pts)
        first, last = pts[0], pts[-1]
        shadow = last[0] if seg.get("ended_by_shadow") else None
        out.append({"start": first[0], "peak": peak[0], "end": last[0],
                    "start_az": first[1], "peak_az": peak[1], "end_az": last[1],
                    "peak_el": peak[2], "mag": brightest,
                    "shadow": shadow, "shadow_az": last[1],
                    "path": [(p[1], p[2]) for p in pts]})
    return out


def passes(now, lat, lon, session=None):
    """Sichtbare Überflüge der nächsten Stunden (Zeitzone von `now`) oder []. Die Rechnung läuft
    höchstens alle 30 Minuten neu (der Zwischenspeicher hängt an Ort und Bahndaten)."""
    if lat is None or lon is None:
        return []
    lines = get_tle(now, session)
    if not lines:
        return []
    key = (round(lat, 2), round(lon, 2), lines[0], int(now.timestamp() // 1800))
    if key in _passes_cache:
        return _passes_cache[key]
    start = (now - timedelta(minutes=10)).astimezone(timezone.utc)     # einen laufenden Überflug nicht verpassen
    tz = now.tzinfo
    res = []
    try:
        for p in compute_passes(lines, start, HORIZON_H, lat, lon):
            for k in ("start", "peak", "end", "shadow"):
                if p[k]:
                    p[k] = p[k].astimezone(tz)
            res.append(p)
    except Exception:
        logger.exception("ISS-Überflüge konnten nicht berechnet werden")
        return []
    _passes_cache.clear()
    _passes_cache[key] = res
    logger.info("ISS: %d sichtbare Überflüge in den nächsten %d h (%d davon hell und hoch genug)",
                len(res), HORIZON_H, sum(1 for p in res if worth(p)))
    return res


# ----------------------------------------------------------------------
# Texte und Grafik
# ----------------------------------------------------------------------
def direction(az, short=False):
    i = int(((az % 360) + 22.5) // 45) % 8
    return (DIRS_SHORT if short else DIRS)[i]


def brightness(mag):
    return "sehr hell" if mag <= -3 else "hell" if mag <= -2 else "gut sichtbar"


def _hm(dt):
    return f"{dt.hour}:{dt.minute:02d}"


def worth(p):
    return p["peak_el"] >= MIN_EL and p["mag"] <= MAX_MAG


def height_word(el):
    return "fast senkrecht über uns" if el >= 75 else "hoch" if el >= 45 else "halbhoch"


def describe(p):
    """Texte für die Zeile im Nachtbild."""
    gone = p["shadow"] or p["end"]
    mins = max(1, round((gone - p["start"]).total_seconds() / 60))
    peak = f"{height_word(p['peak_el'])} im {direction(p['peak_az'])}en" if p["peak_el"] < 75 else height_word(p["peak_el"])
    return {
        "time": _hm(p["start"]),
        "route": f"von {direction(p['start_az'])} nach {direction(p['end_az'] if not p['shadow'] else p['shadow_az'])}",
        "route_short": f"{direction(p['start_az'], True)} → {direction(p['end_az'] if not p['shadow'] else p['shadow_az'], True)}",
        "peak": peak,
        "mins": f"{mins} Min",
        "bright": brightness(p["mag"]),
        "shadow": f"ab {_hm(p['shadow'])} im Erdschatten" if p["shadow"] else "",
    }


def night_arc(W):
    """Nachtbild: gestrichelte Bahn quer über den Himmel mit kleiner Station am höchsten Punkt
    (schematisch: links = Aufgang, rechts = Untergang)."""
    x0, x1, peak = W * 0.12, W * 0.88, 10
    xm = (x0 + x1) / 2
    star = "#FFE500"
    d = f"M{x0:.0f} 64 Q{xm:.0f} {peak - 26} {x1:.0f} 64"
    out = [f'<path d="{d}" fill="none" stroke="{star}" stroke-width="2" stroke-dasharray="5 6" stroke-linecap="round"/>']
    out.append(f'<path d="M{x1 - 9:.0f} 55 L{x1:.0f} 64 L{x1 - 12:.0f} 66" fill="none" stroke="{star}" stroke-width="2" '
               f'stroke-linecap="round" stroke-linejoin="round"/>')
    cy = 0.25 * 64 + 0.5 * (peak - 26) + 0.25 * 64
    out.append(f'<g transform="translate({xm - 11:.0f} {cy - 7:.0f}) scale(0.7)">'
               f'<rect x="0" y="0" width="9" height="20" fill="{star}"/><rect x="23" y="0" width="9" height="20" fill="{star}"/>'
               f'<rect x="9" y="8" width="14" height="4" fill="{star}"/><rect x="12" y="4" width="8" height="12" rx="2" fill="#FFFFFF"/></g>')
    return "".join(out)
