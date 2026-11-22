"""
Polarlicht-Alarm fürs Nachtbild (seit 1.37).

Quelle
------
Space Weather Prediction Center der NOAA, frei und ohne Schlüssel:
  https://services.swpc.noaa.gov/products/noaa-planetary-k-index-forecast.json
Antwort (seit 2025): Liste von Objekten, je ein 3-Stunden-Abschnitt in UTC,
  {"time_tag": "2026-11-24T18:00:00", "kp": 1.67, "observed": "predicted", "noaa_scale": null}
Ältere Fassung: Liste von Listen mit einer Kopfzeile ["time_tag", "kp", "observed", "noaa_scale"].
Beide werden gelesen.

Der Kp-Index (0–9) misst, wie stark das Erdmagnetfeld gestört ist. Je höher, desto weiter südlich ist
Polarlicht zu sehen. Für Bonn (50,7° N) gilt als Faustregel: ab Kp 7 tief am Nordhorizont möglich, ab Kp 8
auch mit bloßem Auge deutlich (Mai 2024, November 2025). Darunter höchstens mit der Handykamera.

Das Nachtbild zeigt das Polarlicht nur, wenn
  * in den dunklen Stunden der kommenden Nacht ein Kp-Wert ≥ KP_MIN vorhergesagt oder gemessen ist und
  * der Himmel überwiegend klar ist (wie bei Sternschnuppen und Planeten).
Die Kurzfassung in der Himmelszeile erscheint auch bei Bewölkung („Polarlicht möglich, aber bewölkt“).

Zwischenspeicher 60 Minuten (auch für Fehlschläge). Ohne Daten liefert night_info() None, und das Nachtbild
bleibt wie bisher (pixelgleich).
"""

import logging
import math
import time as _time
from datetime import datetime, timedelta, timezone

import requests

try:
    from . import status
except ImportError:  # Tests importieren die Module ohne Paket
    import status

logger = logging.getLogger(__name__)

URL = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index-forecast.json"
HEADERS = {"User-Agent": "InkyPi-Tagesdashboard/1.37 (privates E-Ink-Display; github.com/leonschwarze/InkyPi_Dashboard)"}
STATUS_NAME = "Polarlicht"
CACHE_MIN = 60
TIMEOUT = 15
KP_MIN = 7          # ab hier im Bild (Faustregel für Bonn, siehe oben)
KP_STRONG = 8       # ab hier mit roten Spitzen (starke Stürme färben die oberen Ränder rot)
DARK_FROM, DARK_TO = 18, 6   # dunkle Stunden (Ortszeit) im Winterhalbjahr; im Sommer ohnehin kaum Chancen
CLOUD_MAX = 60      # Bewölkung bis hierhin zählt als „klar genug“ (wie beim Planeten-Punkt)

_cache = {}  # "kp" -> (monotonic, [(datetime UTC, kp, art)] | None)


def parse(data):
    """[(Beginn UTC, kp, "observed"/"estimated"/"predicted")] aus beiden Antwortformaten."""
    out = []
    rows = data or []
    for row in rows:
        try:
            if isinstance(row, dict):
                tag, kp, kind = row["time_tag"], row["kp"], row.get("observed") or ""
            else:
                tag, kp, kind = row[0], row[1], row[2] if len(row) > 2 else ""
                if tag == "time_tag":  # Kopfzeile der alten Fassung
                    continue
            when = datetime.fromisoformat(str(tag).replace("Z", "").replace(" ", "T")).replace(tzinfo=timezone.utc)
            out.append((when, float(kp), str(kind)))
        except (KeyError, IndexError, TypeError, ValueError):
            continue
    out.sort(key=lambda v: v[0])
    return out


def fetch(session=None):
    session = session or requests.Session()
    r = session.get(URL, headers=HEADERS, timeout=TIMEOUT)
    if r.status_code != 200:
        raise RuntimeError(f"NOAA: HTTP {r.status_code}")
    return parse(r.json())


def dark_hours(now, night_end=None):
    """(Beginn, Ende) der dunklen Stunden, die das Nachtbild betrifft: ab jetzt (frühestens DARK_FROM Uhr)
    bis zum Morgen (DARK_TO Uhr bzw. Ende des Nachtfensters)."""
    tz = now.tzinfo
    if now.hour < DARK_TO:  # nach Mitternacht: die laufende Nacht
        start = now
        end = datetime.combine(now.date(), datetime.min.time(), tz) + timedelta(hours=DARK_TO)
    else:
        start = max(now, datetime.combine(now.date(), datetime.min.time(), tz) + timedelta(hours=DARK_FROM))
        end = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), tz) + timedelta(hours=DARK_TO)
    if night_end and night_end > start:
        end = min(end, max(night_end, start + timedelta(hours=1)))
    return start, end


def peak(values, start, end):
    """Höchster Kp-Wert, dessen 3-Stunden-Abschnitt die Zeit start–end berührt: (Beginn, kp) oder None."""
    hits = [(w, kp) for w, kp, _ in values if w < end and w + timedelta(hours=3) > start]
    if not hits:
        return None
    return max(hits, key=lambda v: (v[1], -v[0].timestamp()))


def summarize(values, now, wx=None, night_end=None, kp_min=KP_MIN):
    """Info fürs Nachtbild oder None (kein Polarlicht zu erwarten).
    {"kp", "when" (Ortszeit), "strong", "draw", "text"}"""
    start, end = dark_hours(now, night_end)
    top = peak(values or [], start, end)
    if not top or top[1] < kp_min - 0.34:  # 6,67 = „7−“ zählt als 7
        return None
    when, kp = top
    local = max(when.astimezone(now.tzinfo), start)
    cloud = (wx or {}).get("cloud")
    clear = cloud is not None and cloud < CLOUD_MAX and not (wx or {}).get("wet")
    kp_txt = str(round(kp))
    hour = local.hour if local.minute < 30 else (local.hour + 1) % 24
    text = f"Polarlicht möglich: Kp {kp_txt} ab {hour} Uhr · tief im Norden"
    if not clear:
        text = f"Polarlicht möglich (Kp {kp_txt}), aber bewölkt"
    return {"kp": kp, "when": local, "strong": kp >= KP_STRONG - 0.34, "draw": clear, "text": text}


def load_values(session=None):
    """Kp-Werte (mit Zwischenspeicher) oder None. Meldet Erfolg/Ausfall an die Statusanzeige."""
    status.use(STATUS_NAME)
    hit = _cache.get("kp")
    if hit and _time.monotonic() - hit[0] < CACHE_MIN * 60:
        return hit[1]
    try:
        values = fetch(session)
        status.ok(STATUS_NAME)
    except Exception as exc:  # Zusatz: nie das ganze Bild verlieren
        logger.warning("Polarlicht: NOAA nicht verfügbar: %s", exc)
        status.fail(STATUS_NAME, exc)
        values = None
    _cache["kp"] = (_time.monotonic(), values)
    return values


def night_info(values, now, wx=None, night_end=None, kp_min=KP_MIN):
    """Polarlicht fürs Nachtbild aus den Kp-Werten oder None; mit Logzeile."""
    if not values:
        return None
    start, end = dark_hours(now, night_end)
    top = peak(values, start, end)
    info = summarize(values, now, wx, night_end, kp_min)
    logger.info("Polarlicht: höchster Kp %s in der Nacht%s", f"{top[1]:.2f}".replace(".", ",") if top else "?",
                (f" → {info['text']}" + (" (gezeichnet)" if info["draw"] else "")) if info else "")
    return info


def reset():
    """Zwischenspeicher leeren (Tests)."""
    _cache.clear()


# ----------------------------------------------------------------------
# Zeichnung: Vorhang (Leons Wahl aus zwei Entwürfen, 1.37)
# ----------------------------------------------------------------------
GREEN, RED = "#2E9E3F", "#E3001B"


def svg(W, water, rnd, strong=False, x0=None, x1=None, gap_at=None):
    """Polarlicht-Vorhang in der Szene (als Erstes gezeichnet, also hinter Sternen, Mond und Stadt).

    Schmale senkrechte Strahlen; Fuß und Oberkante folgen sanften Wellen (wie ein Vorhang im Wind). Die Strahlen
    sind 3 breit mit 2 Abstand – nach dem Einrasten 3 px Grün, 2 px Himmel, keine Mischfarben. Zwei Vorhänge mit
    einer Lücke, damit es nicht wie ein Zaun wirkt; an ihren Enden werden die Strahlen niedriger. Ab Kp 8
    (strong) ein roter Saum oben – starke Stürme färben die oberen Ränder rot.
    x0/x1: Bereich (Standard: ganze Breite). gap_at: Mitte der Lücke (Standard: zufällig um die Mitte); dort
    steht z. B. die Pegellatte mit ihrem Wert."""
    x0 = 0 if x0 is None else x0
    x1 = W if x1 is None else x1
    out = []
    span = x1 - x0
    auto = x0 + span * rnd.uniform(0.42, 0.58)   # immer ziehen, damit der Zufall danach gleich bleibt
    gap_at = auto if gap_at is None else gap_at
    half = max(span * 0.05, 34)
    ph1, ph2 = rnd.uniform(0, 6.28), rnd.uniform(0, 6.28)
    x = x0
    while x < x1 - 3:
        if abs(x - gap_at) < half:
            x += 5
            continue
        f = (x - x0) / span
        foot = water - 12 - 7 * math.sin(ph1 + f * 7.0)
        height = 30 + 20 * (0.5 + 0.5 * math.sin(ph2 + f * 11.0)) + rnd.uniform(-4, 4)
        edge = min(abs(x - x0), abs(x1 - x), abs(x - gap_at) - half) / (span * 0.06)
        height *= max(0.35, min(1.0, edge))
        top = foot - height
        out.append(f'<rect x="{x:.1f}" y="{top:.1f}" width="3" height="{foot - top:.1f}" fill="{GREEN}"/>')
        if strong:
            out.append(f'<rect x="{x:.1f}" y="{top - 8:.1f}" width="3" height="8" fill="{RED}"/>')
        x += 5
    return "".join(out)
