"""
Bonner Silhouette für das Nachtbild – jede Nacht ein bisschen anders.

Das Band zeigt Münster, Langer Eugen, Post Tower, die Kennedybrücke und das Siebengebirge
mit Petersberg, Drachenfels und Ölberg, davor den Rhein. Der Himmel zeigt die kommende Nacht:
  * Sterne bei klarem Himmel (Anzahl nach Bewölkung, Lage wechselt jeden Tag)
  * Wolken, Regen- oder Schneestriche, Nebelbänder
  * den Mond in seiner Phase; seine Lage wechselt täglich
Dazu eine Zeile zum Tageslicht (Länge, Änderung zum Vortag, Countdown zur Sonnenwende).

Gezeichnet wird nur mit den sechs Displayfarben (helle Wolken werden fein gerastert).
Die Gebäude sind eigene, vereinfachte Umrisse.
"""

import math
import random
from datetime import date, datetime, timedelta, timezone

SKY, STAR, INK, WHITE, CLOUD = "#0B3D91", "#FFE500", "#000000", "#FFFFFF", "#BFDCFF"
WATER, H = 104, 130
SYNODIC = 29.530588853
NEW_MOON_REF = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)


# ----------------------------------------------------------------------
# Wetter und Tageslicht
# ----------------------------------------------------------------------
def night_weather(records, start, end):
    """Bewölkung, Niederschlag, Schnee und Nebel zwischen start und end."""
    hours = [r for r in records if start <= r["dt"] < end]
    if not hours:
        return None
    clouds = [r["cloud_cover"] for r in hours if r.get("cloud_cover") is not None]
    icons = {r.get("icon") for r in hours} | {r.get("condition") for r in hours}
    precip = sum(r.get("precipitation") or 0 for r in hours)
    return {
        "cloud": sum(clouds) / len(clouds) if clouds else None,
        "precip": precip,
        "wet": precip >= 0.3 or bool(icons & {"rain", "snow", "sleet", "hail"}),
        "snowy": bool(icons & {"snow", "sleet"}),
        "fog": "fog" in icons,
    }


def describe(wx):
    if wx is None:
        return ""
    c = wx["cloud"] or 0
    if wx["wet"]:
        return "Schnee" if wx["snowy"] else "Regen"
    if wx["fog"]:
        return "Nebel"
    return "sternklar" if c < 30 else "leicht bewölkt" if c < 60 else "bewölkt" if c < 85 else "bedeckt"


def _length(sun_times, d):
    sr, ss = sun_times(d)
    return (ss - sr).total_seconds() / 60 if sr and ss else None


def _solstice(sun_times, year, month):
    """Tag mit kürzestem (Dezember) bzw. längstem (Juni) Tageslicht."""
    days = [date(year, month, k) for k in range(15, 28)]
    vals = [(d, _length(sun_times, d)) for d in days]
    vals = [v for v in vals if v[1] is not None]
    if not vals:
        return None
    return (min if month == 12 else max)(vals, key=lambda v: v[1])[0]


def daylight(sun_times, d):
    """„9 h 7 min Tageslicht (−3 min) · Wintersonnenwende in 39 Tagen“ (Änderung zum Vortag)."""
    today, before = _length(sun_times, d), _length(sun_times, d - timedelta(days=1))
    if today is None:
        return ""
    first = f"{int(today // 60)} h {round(today % 60)} min Tageslicht"
    if before is not None:
        diff = round(today - before)
        first += f" ({'+' if diff > 0 else '−'}{abs(diff)} min)" if diff else " (wie am Vortag)"
    parts = [first]
    for month, name in ((12, "Wintersonnenwende"), (6, "Sommersonnenwende")):
        for year in (d.year, d.year + 1):
            s = _solstice(sun_times, year, month)
            if s is None or s < d:
                continue
            gap = (s - d).days
            if gap == 0:
                parts.append(f"heute {name}")
            elif gap <= 45:
                parts.append(f"{name} in {gap} Tag{'en' if gap != 1 else ''}")
            break
    return " · ".join(parts)


# ----------------------------------------------------------------------
# Zeichnen
# ----------------------------------------------------------------------
def _moon(cx, cy, r, when):
    age = ((when - NEW_MOON_REF).total_seconds() / 86400) % SYNODIC
    phase = age / SYNODIC
    rx = abs(math.cos(2 * math.pi * phase)) * r
    waxing, gibbous = phase < 0.5, 0.25 < phase < 0.75
    side = 1 if waxing else 0
    back = (1 if gibbous else 0) if waxing else (0 if gibbous else 1)
    return (f'<path d="M{cx},{cy - r} A{r},{r} 0 0 {side} {cx},{cy + r} A{rx:.2f},{r} 0 0 {back} {cx},{cy - r} Z" fill="{STAR}"/>'
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{STAR}" stroke-width="1.6"/>')


# Stadt in eigenen Koordinaten (0–400 breit, Grundlinie WATER). Einfache Umrisse.
CITY = [
    # Häuser links mit Giebeln
    "M0,104 L0,86 L16,86 L16,80 L30,80 L30,88 L44,88 L44,82 L54,74 L64,82 L64,104 Z",
    # Bonner Münster: Langhaus, Vierungsturm mit hoher Spitze, zwei Osttürme
    "M66,104 L66,84 L106,84 L106,56 L110,56 L114,22 L118,56 L122,56 L122,84 L128,84 L128,64 L131,64 L133,46 "
    "L135,64 L140,64 L140,64 L143,64 L145,46 L147,64 L150,64 L150,104 Z",
    # Häuser
    "M150,104 L150,86 L170,86 L170,80 L190,80 L190,90 L202,90 L202,104 Z",
    # Langer Eugen (Abgeordnetenhochhaus) mit Dachaufbau
    "M204,104 L204,38 L222,38 L222,34 L232,34 L232,38 L240,38 L240,104 Z",
    "M240,104 L240,88 L262,88 L262,104 Z",
    # Post Tower: zwei gegeneinander versetzte Hälften
    "M266,104 L266,6 L281,6 L281,104 Z",
    "M281,104 L281,10 L296,10 L296,104 Z",
    # Schürmann-Bau / UN-Campus
    "M300,104 L300,70 L346,70 L346,76 L360,76 L360,104 Z",
    "M360,104 L360,84 L398,84 L398,104 Z",
]
WINDOWS = [(206, 238, 42, 100, 10), (268, 294, 12, 100, 12), (302, 344, 74, 100, 6), (2, 62, 90, 102, 4)]
# Siebengebirge in eigenen Koordinaten (0–300 breit): Petersberg (mit Hotel), Drachenfels (Ruine), Ölberg
HILLS = ("M0,104 C20,86 40,70 60,68 L96,68 C104,70 112,76 120,72 C132,64 140,56 148,54 L150,48 L156,48 "
         "L156,54 C164,58 174,66 184,62 C202,50 222,46 242,48 C264,52 284,66 300,72 L300,104 Z")
HOTEL = (66, 62, 24, 6)


def svg(now, wx, width=800, seed=None, cat=None):
    """SVG-Band für die Nacht. width: 800 quer, 480 hochkant.
    cat: Funktion (Mondmitte x, Oberkante des Mondes) → SVG; dann schläft eine Katze auf dem Mond (seit 1.15)."""
    W = width
    s = min(1.0, (W - 230) / 400)  # Stadt im Hochformat etwas kleiner
    rnd = random.Random(seed if seed is not None else now.date().toordinal())
    cloud = (wx or {}).get("cloud") or 0
    wet, snowy, fog = (wx or {}).get("wet"), (wx or {}).get("snowy"), (wx or {}).get("fog")
    out = [f'<svg viewBox="0 0 {W} {H}" class="art-svg" preserveAspectRatio="xMidYMid meet">',
           f'<rect width="{W}" height="{WATER}" fill="{SKY}"/>']

    # Sterne
    n = 0 if wet or fog else 80 if cloud < 30 else 45 if cloud < 60 else 14 if cloud < 85 else 0
    n = round(n * W / 800)
    for _ in range(n):
        out.append(f'<circle cx="{rnd.uniform(3, W - 3):.0f}" cy="{rnd.uniform(3, 66):.0f}" '
                   f'r="{rnd.choice((1.2, 1.4, 1.7, 2.2))}" fill="{STAR}"/>')

    # Mond: Lage wechselt täglich, nie hinter dem Post Tower
    city_w = 400 * s
    hills_x = W - 300 * s
    slots = [x for x in range(int(city_w) + 20, int(hills_x) + 40, 12)] + [x for x in range(20, int(250 * s), 12)]
    if cat:  # Mond sitzt tiefer: nur über niedriger Bebauung (Brücke, Häuser links), nie hinter Münster/Langem Eugen
        slots = [x for x in range(int(city_w) + 26, int(hills_x) + 34, 12)] + [x for x in range(26, int(50 * s), 12)]
    mx = slots[(now.date().toordinal() * 7) % len(slots)] if slots else W // 2
    if not (wet and cloud >= 85):
        # Mit Katze etwas größer und tiefer, damit sie oben auf dem Mond Platz hat
        my, mr = (48, 18) if cat else (26, 14)
        out.append(_moon(mx, my, mr, now))

    # Wolken (hell, werden auf dem Display fein gerastert)
    if cloud >= 45:
        for _ in range(3 if cloud < 70 else 5 if cloud < 90 else 8):
            out.append(f'<ellipse cx="{rnd.uniform(20, W - 20):.0f}" cy="{rnd.uniform(14, 48):.0f}" '
                       f'rx="{rnd.uniform(45, 95) * W / 800 + 20:.0f}" ry="{rnd.uniform(9, 15):.0f}" fill="{CLOUD}"/>')

    # Katze auf dem Mond nach den Wolken: Sie schläft obenauf und wird nicht verdeckt
    if cat and not (wet and cloud >= 85):
        out.append(cat(mx, my - mr))

    # Stadt und Berge (Stadt links, Siebengebirge rechts, beide unten verankert)
    out.append(f'<g transform="translate(0,{WATER}) scale({s:.3f}) translate(0,-{WATER})">')
    out += [f'<path d="{p}" fill="{INK}"/>' for p in CITY]
    for x0, x1, y0, y1, k in WINDOWS:
        for _ in range(k):
            out.append(f'<rect x="{rnd.uniform(x0, x1 - 3):.0f}" y="{rnd.uniform(y0, y1 - 3):.0f}" width="3" height="3" fill="{STAR}"/>')
    for y in (34, 62, 88):  # Fugen der Sky-Lobbys im Post Tower
        out.append(f'<rect x="266" y="{y}" width="30" height="1.6" fill="{SKY}"/>')
    out.append("</g>")
    out.append(f'<g transform="translate({hills_x:.1f},{WATER}) scale({s:.3f}) translate(0,-{WATER})">'
               f'<path d="{HILLS}" fill="{INK}"/>'
               f'<rect x="{HOTEL[0]}" y="{HOTEL[1]}" width="{HOTEL[2]}" height="{HOTEL[3]}" fill="{INK}"/>'
               f'<rect x="72" y="64" width="3" height="2" fill="{STAR}"/><rect x="80" y="64" width="3" height="2" fill="{STAR}"/>'
               f'</g>')

    # Rhein mit Kennedybrücke und Spiegelungen
    out.append(f'<rect y="{WATER}" width="{W}" height="{H - WATER}" fill="{INK}"/>')
    bx0, bx1 = city_w + 4, hills_x + 30 * s
    if bx1 - bx0 > 40:
        out.append(f'<rect x="{bx0:.0f}" y="{WATER - 6}" width="{bx1 - bx0:.0f}" height="3" fill="{INK}"/>')
        for k in range(1, 4):
            px = bx0 + (bx1 - bx0) * k / 4
            out.append(f'<rect x="{px - 1.5:.0f}" y="{WATER - 6}" width="3" height="6" fill="{INK}"/>')
    for x in [222 * s, 281 * s, 330 * s] + ([mx] if not (wet and cloud >= 85) else []):
        for k in range(3):
            out.append(f'<rect x="{x - 9 + k * 5:.0f}" y="{WATER + 5 + k * 6}" width="{18 - k * 5}" height="2" fill="{STAR}"/>')

    # Niederschlag und Nebel vor allem
    if wet:
        for _ in range(round(120 * W / 800)):
            x, y = rnd.uniform(0, W), rnd.uniform(0, WATER - 8)
            if snowy:
                out.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="1.9" fill="{WHITE}"/>')
            else:
                out.append(f'<line x1="{x:.0f}" y1="{y:.0f}" x2="{x - 4:.0f}" y2="{y + 10:.0f}" stroke="{WHITE}" stroke-width="1.5"/>')
    if fog:
        for y in (66, 80, 94):
            out.append(f'<rect y="{y}" width="{W}" height="6" fill="{CLOUD}"/>')
    out.append("</svg>")
    return "".join(out)
