"""Urlaubsbild (seit 1.23): Steht ein Urlaub im Kalender, zeigt das Display statt des Dashboards
eine Abfahrtstafel mit Reiseziel, Rückkehrtag und Resttagen, dazu das Wetter am Ziel und zu Hause.

Erkennen: ganztägiger Termin über mindestens `MIN_DAYS` Tage, der heute läuft und eines der
Stichwörter enthält (Standard „Urlaub, Ferien, Reise“). Ziel: Ort des Termins, sonst der Rest des
Titels („Urlaub in Lyon“ → Lyon, „Urlaub Lyon“ → Lyon).

Wetter am Ziel: Der Ortsname wird einmal über die Geocoding-API von Open-Meteo (ohne Schlüssel) zu
Koordinaten, die Vorhersage kommt wie beim Wetter-Ort von Bright Sky. Klappt eines von beiden nicht
(oder kennt Bright Sky den Ort nicht), fehlt nur die Spalte „Ziel“ – die Tafel bleibt.

Gezeichnet wird wie bei den Festbildern ein einziges SVG in den sechs Displayfarben. Ohne Uhrzeit:
Das Bild bleibt den ganzen Tag gleich, InkyPi lässt das Display dann in Ruhe.
"""
import logging
import re
import time as _time
from datetime import timedelta

import requests

try:
    from . import festtage as ft
    from . import katze
    from . import status
except ImportError:  # Tests importieren die Module ohne Paket
    import festtage as ft
    import katze
    import status

logger = logging.getLogger(__name__)

BLACK, WHITE, RED, YELLOW, BLUE, GREEN = ft.BLACK, ft.WHITE, ft.RED, ft.YELLOW, ft.BLUE, ft.GREEN
FONT = ft.FONT
DEFAULT_KEYWORDS = "Urlaub, Ferien, Reise"
MIN_DAYS = 2   # kürzere ganztägige Termine („Reise“ für einen Tag) sind kein Urlaub
WOCHENTAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
WT_KURZ = ["MO", "DI", "MI", "DO", "FR", "SA", "SO"]


# ---------------------------------------------------------------- Erkennen
def keywords(text):
    return [k.strip().lower() for k in (text or DEFAULT_KEYWORDS).split(",") if k.strip()]


def read_min_days(text):
    """Ab wie vielen Tagen ein ganztägiger Termin als Urlaub gilt (1–60, sonst Standard)."""
    try:
        return max(1, min(60, int(str(text).strip())))
    except (TypeError, ValueError):
        return MIN_DAYS


def destination(ev, words):
    if ev.get("location"):
        return ev["location"].split(",")[0].strip()
    title = ev.get("title", "")
    m = re.search(r"\b(?:in|nach)\s+(.+)$", title, re.I)
    if m:
        return m.group(1).strip()
    for w in words:
        rest = re.sub(re.escape(w), "", title, flags=re.I).strip(" -–:")
        if rest != title.strip() and rest:
            return rest
    return ""


def find(events, today, words, min_days=MIN_DAYS):
    """Laufender Urlaub (Rohtermine aus nextcloud_kalender.parse_events) oder None."""
    for ev in events:
        if not ev.get("all_day"):
            continue
        first = ev["start"].date()
        last = (ev["end"] - timedelta(seconds=1)).date()
        if (last - first).days + 1 < min_days or not (first <= today <= last):
            continue
        if any(w in ev["title"].lower() for w in words):
            left = (last - today).days
            return {
                "dest": destination(ev, words) or "Urlaub",
                "first": first, "last": last, "left": left,
                "back": f"{WOCHENTAGE[last.weekday()]}, {last.day}.{last.month}.",
                "back_short": f"{WT_KURZ[last.weekday()]} {last.day}.{last.month}.",
                "left_text": ("heute geht’s heim" if left == 0 else "morgen geht’s heim" if left == 1
                              else f"noch {left} Tage"),
            }
    return None


# ---------------------------------------------------------------- Bausteine
def _t(x, y, s, size, fill=BLACK, anchor="start", stroke=None, sw=0):
    return ft.text(x, y, s, size, fill, anchor=anchor, stroke=stroke, sw=sw)


def _fit(word, width, max_size):
    em = sum(ft._em(c) for c in word) or 1
    return min(max_size, width / em)


def _icon(svg, x, y, size):
    """Wettersymbol (eigenes <svg> aus dwd_icons) an Position und Größe setzen."""
    return svg.replace("<svg ", f'<svg x="{x:.0f}" y="{y:.0f}" width="{size:.0f}" height="{size:.0f}" ', 1)


def _cat(x, y, k, stroke=2.6):
    w, h, inner = katze.POSES["koffer"]()
    return (f'<g transform="translate({x:.1f} {y:.1f}) scale({k})" stroke-width="{stroke / k:.2f}" '
            f'stroke-linecap="round" stroke-linejoin="round" style="color:{BLACK}; --bg:{WHITE}; '
            f'--cat-red:{RED}; --cat-yellow:{YELLOW}; --cat-blue:{BLUE}">{inner}</g>'), w * k, h * k


def _wx_lines(wx):
    if not wx:
        return "", ""
    sub = wx["text"] + (f" · Regen {wx['prob']} %" if wx.get("prob") else "")
    return f"{wx['tmax']}° / {wx['tmin']}°", sub


# ---------------------------------------------------------------- Wetter am Ziel
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
WEATHER_URL = "https://api.brightsky.dev/weather"
TIMEOUT = 15
GEO_RETRY_MIN = 60      # Ort nicht gefunden oder Dienst gestört: frühestens nach einer Stunde wieder fragen
WX_CACHE_MIN = 60       # Vorhersage: stündlich reicht (die Tafel ändert sich tagsüber kaum)

_geo = {}   # kleingeschriebener Ortsname -> (monotonic, (lat, lon) | None)
_wx = {}    # (lat, lon gerundet) -> (monotonic, records)


def geocode(dest, session=None):
    """(lat, lon) für einen Ortsnamen oder None. Gefundene Orte bleiben im Speicher (ändern sich nie)."""
    key = (dest or "").strip().lower()
    if not key:
        return None
    hit = _geo.get(key)
    if hit and (hit[1] is not None or _time.monotonic() - hit[0] < GEO_RETRY_MIN * 60):
        return hit[1]
    status.use("Reiseziel")
    pos = None
    try:
        r = (session or requests.Session()).get(GEOCODE_URL, params={"name": dest, "count": 1, "language": "de", "format": "json"},
                                      timeout=TIMEOUT)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}")
        res = (r.json().get("results") or [None])[0]
        if res:
            pos = (float(res["latitude"]), float(res["longitude"]))
            logger.info("Reiseziel %s → %.3f, %.3f (%s)", dest, pos[0], pos[1], res.get("country") or "?")
        else:
            logger.info("Reiseziel %s: Ort nicht gefunden", dest)
        status.ok("Reiseziel")
    except Exception as exc:  # Wetter am Ziel ist Zusatz
        logger.warning("Reiseziel %s nicht auffindbar: %s", dest, exc)
        status.fail("Reiseziel", exc)
    _geo[key] = (_time.monotonic(), pos)
    return pos


def fetch_records(pos, tz, now, parse_ts, session=None, source="Reiseziel"):
    """Stündliche Vorhersage für heute und morgen am Ziel (Liste von Datensätzen mit `dt`) oder [].

    `source` = Name in der Statusanzeige (das Wetter am Zielort nutzt dieselbe Abfrage, seit 1.30)."""
    key = (round(pos[0], 2), round(pos[1], 2))
    hit = _wx.get(key)
    if hit and _time.monotonic() - hit[0] < WX_CACHE_MIN * 60:
        return hit[1]
    status.use(source)
    records = []
    try:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        r = (session or requests.Session()).get(WEATHER_URL, params={
            "lat": pos[0], "lon": pos[1], "tz": getattr(tz, "key", "Europe/Berlin"),
            "date": start.isoformat(timespec="minutes"),
            "last_date": (start + timedelta(days=2)).isoformat(timespec="minutes")}, timeout=TIMEOUT)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}")
        for rec in r.json().get("weather", []):
            try:
                rec = dict(rec)
                rec["dt"] = parse_ts(rec["timestamp"], tz)
                records.append(rec)
            except (KeyError, ValueError):
                continue
        records.sort(key=lambda x: x["dt"])
        status.ok(source)
    except Exception as exc:
        logger.warning("Wetter am %s nicht verfügbar: %s", source, exc)
        status.fail(source, exc)
    _wx[key] = (_time.monotonic(), records)
    return records


# ---------------------------------------------------------------- Abfahrtstafel
def _flaps(x, y, word, ch, max_w, fg=BLACK):
    """Fallblatt-Zeile: ein Kärtchen je Zeichen (Leerzeichen = leeres Kärtchen)."""
    cw = ch * 0.68
    gap = ch * 0.08
    n = len(word)
    if n * (cw + gap) > max_w:  # zu lang: kleinere Kärtchen
        k = max_w / (n * (cw + gap))
        ch, cw, gap = ch * k, cw * k, gap * k
    out = []
    for i, c in enumerate(word.upper()):
        cx = x + i * (cw + gap)
        out.append(f'<rect x="{cx:.1f}" y="{y:.1f}" width="{cw:.1f}" height="{ch:.1f}" rx="{ch * 0.08:.1f}" fill="{WHITE}"/>')
        if c.strip():
            size = ch * 0.8 if c not in "MW" else ch * 0.68
            out.append(_t(cx + cw / 2, y + ch * 0.8, c, size, fg, anchor="middle"))
        out.append(f'<rect x="{cx:.1f}" y="{y + ch / 2 - 1.2:.1f}" width="{cw:.1f}" height="2.4" fill="{ft.NAVY}"/>')
    return "".join(out), n * (cw + gap)


def scene(W, H, info, today, wx_dest, wx_home):
    portrait = H > W
    out = [f'<svg viewBox="0 0 {W} {H}" class="ur-svg" xmlns="http://www.w3.org/2000/svg">',
           f'<rect width="{W}" height="{H}" fill="{WHITE}"/>']
    bh = 330 if not portrait else 500
    out.append(f'<rect width="{W}" height="{bh}" fill="{ft.NAVY}"/>')
    lx = 26
    label_w = 0 if portrait else 150
    fx = lx + label_w
    big, small = (80, 58) if not portrait else (70, 52)
    rows = [("Reiseziel", info["dest"], big), ("Zurück", info["back_short"], small),
            ("Noch", f"{info['left']} Tage" if info["left"] > 1 else info["left_text"], small)]
    y = 28
    for label, word, ch in rows:
        if portrait:
            out.append(_t(lx, y + 22, label, 22, WHITE))
            y += 32
            flap, _ = _flaps(lx, y, word, ch, W - 2 * lx)
        else:
            out.append(_t(lx, y + ch * 0.68, label, 24, WHITE))
            flap, _ = _flaps(fx, y, word, ch, W - fx - 26)
        out.append(flap)
        y += ch + (24 if portrait else 22)
    # Bahnsteigkante mit Katze und Koffer
    out.append(f'<rect y="{bh}" width="{W}" height="10" fill="{YELLOW}"/>')
    out.append(f'<rect y="{bh + 10}" width="{W}" height="3" fill="{BLACK}"/>')
    cat, cw, chh = _cat(W - 150, bh - 44 * 1.8 + 1, 1.8)
    out.append(cat)
    # Wetter unten
    wy = bh + (34 if not portrait else 28)
    col_w = (W - 52) / (1 if portrait else 2)
    shown = [(t, w_) for t, w_ in ((f"{info['dest']} heute", wx_dest), ("Zuhause in Bonn", wx_home)) if w_]
    for i, (title, wx_) in enumerate(shown):
        cx = 26 + (0 if portrait else i * col_w)
        cy = wy + (i * 88 if portrait else 0)
        t1, t2 = _wx_lines(wx_)
        out.append(_icon(wx_["icon"], cx, cy + 4, 70))
        out.append(_t(cx + 82, cy + 26, title, 20))
        out.append(_t(cx + 82, cy + 58, t1, 30))
        out.append(_t(cx + 82, cy + 82, t2, 17))
    out.append("</svg>")
    return "".join(out)
