"""Ostereier im Tagesdashboard (seit 1.24): kleine Überraschungen an seltenen Tagen und bei seltenem Wetter.

Bewusst nirgends angekündigt (nicht in der README, kein Schalter – Leons Wunsch), nur hier und in CLAUDE.md
beschrieben. Fast alle laufen über die Katze: Sie hat schon den Platzsucher placeCat im Template, ein Osterei
verdeckt also nie etwas. Ist die Katze aus (catEnabled), bleiben nur die Grüße im Kopf, der Regenbogen und das
Sternbild.

Tage (today):
  Karneval         11.11. ab 11:11 („Bonn Alaaf!“), Weiberfastnacht („Beuel Alaaf!“ – in Beuel 1824 entstanden)
                   bis Veilchendienstag, Rosenmontag „Bonn Alaaf!“: Narrenkappe in Rot-Gelb
  Beethoven        17.12. (1770 in Bonn getauft): Katze dirigiert, ohne Text
  Grundgesetz      23.5. (1949 in Bonn verkündet): Buch in Schwarz-Rot-Gold, „77 Jahre Grundgesetz“
  Freitag, der 13. schwarze Katze läuft über die Linie, ohne Text
  π-Tag            14.3.: π auf einem Himbeerkuchen (das Display hängt an einem Raspberry Pi), ohne Text
  Halloween        31.10.: Kürbis, ohne Text
Wetter (rainbow): Sonne und Regen in derselben Stunde → Regenbogen hinter dem Wettersymbol (auch ohne Katze).
Nacht (felis_night): Lalandes Sternbild Katze in einigen klaren Nächten im Nachtbild (nachtgrafik.svg).

Nur in der normalen Ansicht (Nachtbild: nur das Sternbild). Kein Zufall bei den Tagen: Das Bild bleibt an
einem Ostereier-Tag so ruhig wie sonst auch (InkyPi zeichnet nur bei geänderten Pixeln neu).
"""
import random
from datetime import date, datetime, time, timedelta

try:
    from .katze import _current_hour
except ImportError:  # Tests ohne Paket
    from katze import _current_hour


def easter(year):
    """Ostersonntag (gregorianisch, anonymer Algorithmus nach Meeus/Jones/Butcher)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def karneval(d):
    """Name des Karnevalstages oder None. Weiberfastnacht = Ostern − 52 Tage, Rosenmontag = − 48,
    Veilchendienstag = − 47 (Aschermittwoch ist vorbei)."""
    e = easter(d.year)
    return {e - timedelta(days=52): "Weiberfastnacht", e - timedelta(days=51): "Rußiger Freitag",
            e - timedelta(days=50): "Karnevalssamstag", e - timedelta(days=49): "Karnevalssonntag",
            e - timedelta(days=48): "Rosenmontag", e - timedelta(days=47): "Veilchendienstag"}.get(d)


SESSION_START = time(11, 11)


def today(now):
    """Osterei für jetzt: {name, pose, greeting} oder None (greeting: Text für den Kopf oder None)."""
    d = now.date()
    md = (d.month, d.day)
    if md == (11, 11):
        if now.time() >= SESSION_START:
            return {"name": "sessionsbeginn", "pose": "narr", "greeting": "Bonn Alaaf!"}
        return None
    jeck = karneval(d)
    if jeck:
        greeting = {"Weiberfastnacht": "Beuel Alaaf!", "Rosenmontag": "Bonn Alaaf!"}.get(jeck)
        return {"name": "karneval", "pose": "narr", "greeting": greeting}
    if md == (12, 17):
        return {"name": "beethoven", "pose": "dirigent", "greeting": None}
    if md == (5, 23) and d.year > 1949:
        return {"name": "grundgesetz", "pose": "grundgesetz", "greeting": f"{d.year - 1949} Jahre Grundgesetz"}
    if md == (3, 14):
        return {"name": "pi-tag", "pose": "himbeerkuchen", "greeting": None}
    if md == (10, 31):
        return {"name": "halloween", "pose": "kürbis", "greeting": None}
    if d.day == 13 and d.weekday() == 4:
        return {"name": "freitag13", "pose": "schwarz", "greeting": None}
    return None


def boundaries(now, days=2):
    """Grenzen für den Bild-Cache (nur mit Zug aktiv): Mitternacht und am 11.11. um 11:11."""
    tz = now.tzinfo
    out = []
    for k in range(days):
        d = now.date() + timedelta(days=k)
        out.append(datetime.combine(d + timedelta(days=1), time(0, 0), tz))
        if (d.month, d.day) == (11, 11):
            out.append(datetime.combine(d, SESSION_START, tz))
    return sorted(t for t in out if t > now)


# ---------------------------------------------------------------- Regenbogen am Wettersymbol
RAINBOW_SUN_MIN = 15   # Sonnenminuten in der laufenden Stunde …
RAINBOW_MM = 0.1       # … und mindestens so viel Regen (wie die Regenregel der Katze)


def rainbow(records, now):
    """Sonne und Regen in derselben Stunde (Stundenwert nach Zeitstempel, wie die Katze). Bei Schnee nicht."""
    r = _current_hour(records or [], now)
    return bool(r) and (r.get("sunshine") or 0) >= RAINBOW_SUN_MIN and (r.get("precipitation") or 0) >= RAINBOW_MM \
        and r.get("icon") not in ("snow", "sleet") and r.get("condition") not in ("snow", "sleet", "hail")


# Vier Bänder in Displayfarben (Orange und Violett kann das Display nicht), dicker als die Linien, damit
# sie links und rechts von Wolke und Sonne zu sehen sind. Feste Farben: im Schwarz-Weiß-Modus ausgeblendet.
RAINBOW_SVG = (
    '<svg class="wx-rainbow" viewBox="0 0 64 64" aria-hidden="true">'
    '<g fill="none" stroke-width="4.2">'
    '<path stroke="#E3001B" d="M2.5 42 A29.5 29.5 0 0 1 61.5 42"/>'
    '<path stroke="#FFC400" d="M7 42 A25 25 0 0 1 57 42"/>'
    '<path stroke="#2E9E3F" d="M11.5 42 A20.5 20.5 0 0 1 52.5 42"/>'
    '<path stroke="#0082C9" d="M16 42 A16 16 0 0 1 48 42"/>'
    '</g></svg>')


# ---------------------------------------------------------------- Sternbild Katze im Nachtbild
# Felis: 1799 von Jérôme Lalande (Katzenfreund) zwischen Wasserschlange und Luftpumpe eingeführt, 1801 in
# Bodes „Uranographia“ gezeichnet, in der offiziellen Liste der IAU von 1930 nicht mehr dabei. Seit 2018
# heißt dort ein Stern „Felis“.
FELIS_CHANCE = 0.06    # Anteil der klaren Nächte (bei klarem Himmel etwa zwei Nächte im Monat)
FELIS_CLOUD = 30       # Bewölkung unter … % wie „sternklar“ und die Sternschnuppen-Striche
# Sterne (x, y, Radius) einer sitzenden Katze von vorn wie die Dashboard-Katze: zwei spitze Ohren, Körper,
# Schwanz rechts hochgebogen; etwa 38 × 42 Einheiten. (Eine erste Fassung im Profil sah aus wie ein Tisch.)
FELIS_STARS = [(4, 0, 2.1), (11, 7, 1.5), (18, 0, 2.1), (21, 12, 1.7), (25, 34, 1.7), (22, 42, 2.4),
               (2, 42, 1.7), (-1, 30, 1.5), (1, 12, 1.7), (32, 41, 1.5), (36, 27, 2.1)]
FELIS_LINES = [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 6), (6, 7), (7, 8), (8, 0), (5, 9), (9, 10)]


def felis_night(d, wx):
    """Ist in der Nacht d (Datum wie im Nachtbild) das Sternbild Katze zu sehen? Klarer Himmel und Zufall nach
    Datum – wiederholbar, damit das Nachtbild die ganze Nacht gleich bleibt."""
    if not wx or wx.get("wet") or wx.get("fog") or (wx.get("cloud") if wx.get("cloud") is not None else 100) >= FELIS_CLOUD:
        return False
    return random.Random(f"{d.isoformat()}/felis").random() < FELIS_CHANCE


def felis_svg(x0, y0, k=1.0, line="#FFFFFF", star="#FFE500"):
    """Sternbild als SVG: weiße Linien (rein auf Blau, keine Mischfarbe), darüber gelbe Sterne wie am übrigen Himmel."""
    pts = [(x0 + x * k, y0 + y * k, r) for x, y, r in FELIS_STARS]
    out = [f'<g stroke="{line}" stroke-width="1.4" stroke-linecap="round">']
    out += [f'<line x1="{pts[a][0]:.1f}" y1="{pts[a][1]:.1f}" x2="{pts[b][0]:.1f}" y2="{pts[b][1]:.1f}"/>'
            for a, b in FELIS_LINES]
    out.append("</g>")
    out += [f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{star}"/>' for x, y, r in pts]
    return "".join(out)
