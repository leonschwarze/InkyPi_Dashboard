"""
Laufen der Woche (seit 1.38, Wochenvorschau): „Diese Woche 17,5 km gelaufen“.

Woher die Zahlen kommen
-----------------------
Apple Health hat keine Schnittstelle, die der Pi abfragen könnte. Deshalb schreibt ein iPhone-Kurzbefehl
nach jedem Lauf eine Zeile in eine Textdatei in der Nextcloud (Standard: InkyPi/laufen.txt):

    2026-11-22;5,2;31

Datum, Kilometer, Minuten (Minuten dürfen fehlen; Trenner ; oder Leerzeichen, Komma oder Punkt, „km“ und
„min“ dürfen dabeistehen, Zeilen mit # sind Kommentare). Der Pi liest die Datei per WebDAV mit
demselben Zugang wie den Kalender – an dieselbe Nextcloud, an die das App-Passwort gebunden ist (1.33).

Was angezeigt wird
------------------
Eine Zeile über der Pi-Zeile (Leons Wahl „Laufen A“): „Laufen: 17,5 km · 3 Läufe · Ø 13,8 km in den vier
Wochen davor“. Gezählt wird die Woche Mo–So, in der die Wochenvorschau läuft (sonntags: die Woche, die
gerade endet). Ohne Datei oder ohne einen einzigen Lauf in den letzten fünf Wochen: keine Zeile.

Abruf höchstens alle CACHE_MIN Minuten, auch Fehlschläge. Statusname „Laufbuch“ (nur Fehler beim
Abruf, eine fehlende Datei ist kein Ausfall).
"""

import logging
import re
import time as _time
from datetime import date, timedelta
from urllib.parse import quote

try:
    from . import status
except ImportError:  # Tests importieren die Module ohne Paket
    import status

logger = logging.getLogger(__name__)

DEFAULT_PATH = "InkyPi/laufen.txt"
STATUS_NAME = "Laufbuch"
CACHE_MIN = 30
AVG_WEEKS = 4
MAX_BYTES = 200_000   # ein Laufbuch hat nach Jahren ein paar Kilobyte; mehr ist keins
TIMEOUT = 15

_cache = {}  # url -> (monotonic, text | None)

LINE = re.compile(r"^\s*(\d{4}-\d{2}-\d{2}|\d{1,2}\.\d{1,2}\.\d{4})[\s;,]+(\d+(?:[.,]\d+)?)\s*(?:km)?"
                  r"(?:[\s;,]+(\d+(?:[.,]\d+)?)\s*(?:min)?)?", re.I)


def clean_path(raw):
    """Pfad in der Nextcloud: ohne führenden /, ohne „..“, nur übliche Zeichen. Ungültig → Standard."""
    p = str(raw or "").strip().strip("/")
    if not p or ".." in p.split("/") or not re.fullmatch(r"[\w .\-/äöüÄÖÜß]{1,200}", p):
        return DEFAULT_PATH
    return p


def parse(text):
    """[(date, km, minuten | None)] aus dem Laufbuch; unlesbare Zeilen werden übersprungen."""
    out = []
    for line in (text or "").splitlines():
        if line.lstrip().startswith("#"):
            continue
        m = LINE.match(line)
        if not m:
            continue
        ds, km, mins = m.groups()
        try:
            if "-" in ds:
                d = date.fromisoformat(ds)
            else:
                dd, mm, yy = (int(x) for x in ds.split("."))
                d = date(yy, mm, dd)
            km = float(km.replace(",", "."))
            mins = float(mins.replace(",", ".")) if mins else None
        except ValueError:
            continue
        if 0 < km < 200:
            out.append((d, km, mins))
    return out


def fetch(client, user, path):
    """Inhalt des Laufbuchs oder None (Datei fehlt). Wirft bei anderen Fehlern."""
    url = client.root + "files/" + quote(user, safe="") + "/" + quote(path, safe="/")
    r = client.session.get(url, timeout=TIMEOUT, stream=True)
    if r.status_code == 404:
        return None
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    data = r.raw.read(MAX_BYTES + 1, decode_content=True) if hasattr(r, "raw") and r.raw else r.content
    if len(data) > MAX_BYTES:
        raise RuntimeError("Datei zu groß")
    return data.decode("utf-8", errors="replace")


def load(client, user, path):
    """Läufe aus der Nextcloud (zwischengespeichert) oder None."""
    status.use(STATUS_NAME)
    key = (client.root, user, path)
    hit = _cache.get(key)
    if hit and _time.monotonic() - hit[0] < CACHE_MIN * 60:
        text = hit[1]
    else:
        try:
            text = fetch(client, user, path)
            status.ok(STATUS_NAME)
            if text is None:
                logger.info("Laufbuch: %s nicht gefunden", path)
        except Exception as exc:  # Zusatz: nie das ganze Bild verlieren
            logger.warning("Laufbuch nicht lesbar: %s", exc)
            status.fail(STATUS_NAME, exc)
            text = None
        _cache[key] = (_time.monotonic(), text)
    return parse(text) if text else None


def fmt_km(km):
    r = round(km, 1)
    return (f"{r:.1f}".replace(".", ",").replace(",0", "")) + " km"


def week_of(d):
    return d - timedelta(days=d.weekday())


def summary(runs, today):
    """Zahlen für die Wochenvorschau oder None.

    runs: [(date, km, min)]; today: Tag der Wochenvorschau (meist Sonntag).
    """
    if not runs:
        return None
    monday = week_of(today)
    weeks = {}
    for d, km, mins in runs:
        if d > today:
            continue
        weeks.setdefault(week_of(d), []).append(km)
    this = weeks.get(monday, [])
    prev = [sum(weeks.get(monday - timedelta(days=7 * i), [])) for i in range(1, AVG_WEEKS + 1)]
    if not this and not any(prev):
        return None
    km = sum(this)
    avg = sum(prev) / len(prev)
    return {
        "km": km, "count": len(this), "avg": avg,
        "km_text": fmt_km(km), "avg_text": f"Ø {fmt_km(avg)}" if avg else "",
        "count_text": "kein Lauf" if not this else ("1 Lauf" if len(this) == 1 else f"{len(this)} Läufe"),
    }


def reset():
    _cache.clear()
