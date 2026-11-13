"""Die kleine Katze im Tagesdashboard (seit 1.14, Variante B + C).

B – Versteckspiel: Die Katze sitzt jedes Mal auf einer anderen Linie (Kopfzeile, Linie
    unter einer Tages-Überschrift, gestrichelte Linie über „+ weitere Termine“). Welcher
    Platz frei ist, weiß erst der Browser: Das Skript `placeCat()` im Template misst das
    fertige Layout und nimmt den ersten Platz der Reihenfolge, an dem die Katze nichts
    verdeckt. Passt sie nirgends hin, fehlt sie eben.
C – Wetterkatze: Bei Sturm hält sie sich fest, bei Regen sitzt sie unter dem Schirm, bei
    Schnee oder Frost trägt sie Schal, bei Sonne liegt sie auf dem Rücken. Sonst kommt eine
    zufällige Pose.

Zufall: Er hängt am Datum und am 15-Minuten-Abschnitt der Uhrzeit. Dasselbe Datum und
dieselbe Uhrzeit ergeben dieselbe Katze (Tests sind wiederholbar), und zwei aufeinander-
folgende Abschnitte haben nie dieselbe Pose (die Posen eines Tages sind gemischt und
werden der Reihe nach durchlaufen).

Zeichnung: eigene Linien-SVGs, 1 Einheit = 1 px bei 800×480 (--u = 8 px). Die Strichstärke
hängt nicht an der Skalierung (vector-effect: non-scaling-stroke), sondern an --u, damit
die Katze so kräftig ist wie die übrigen Linien. Farbtupfer nur in Displayfarben.
"""
import math
import random
from datetime import timedelta

# Farben als CSS-Variablen: Im Schwarz-Weiß-Modus (.mono) werden sie zur Textfarbe
RED, YELLOW, BLUE = "var(--cat-red)", "var(--cat-yellow)", "var(--cat-blue)"

L = 'fill="none" stroke="currentColor"'      # Linie
F = 'fill="var(--bg)" stroke="currentColor"'  # Fläche: deckt Linien dahinter ab
D = 'fill="currentColor" stroke="none"'      # Punkt (Augen, Nase)

# Wetterregeln (C)
STORM_GUST = 60      # km/h Böen in der aktuellen Stunde (Bft 8)
RAIN_MM = 0.1        # mm in der aktuellen Stunde
FROST_FEELS = 0      # °C gefühlt (Windchill)
SUN_MIN = 40         # Sonnenminuten in der aktuellen Stunde …
SUN_TEMP = 15        # … bei mindestens so viel Grad

SLOT_MIN = 15        # Takt der Aktualisierung bei Leon


def _whiskers(cx, y, spread=5.5, out=6):
    l, r = cx - spread, cx + spread
    return (f'<path {L} d="M{l:.1f} {y:.1f} L{l - out:.1f} {y - 1:.1f} M{l:.1f} {y + 2:.1f} L{l - out + .5:.1f} {y + 3:.1f}'
            f' M{r:.1f} {y:.1f} L{r + out:.1f} {y - 1:.1f} M{r:.1f} {y + 2:.1f} L{r + out - .5:.1f} {y + 3:.1f}"/>')


def _head(cx, cy, s=1.0, eyes="open"):
    """Kopf von vorn mit Ohren; cx/cy = Mitte, s = Größe. eyes: open, closed, none."""
    def p(x, y):
        return f"{cx + x * s:.1f} {cy + y * s:.1f}"
    out = (f'<path {F} d="M{p(-9.8, -1.5)} L{p(-9, -11.5)} L{p(-3, -7.8)} Q{p(0, -8.6)} {p(3, -7.8)}'
           f' L{p(9, -11.5)} L{p(9.8, -1.5)} Q{p(11, 7)} {p(0, 8.5)} Q{p(-11, 7)} {p(-9.8, -1.5)} Z"/>')
    if eyes == "open":
        out += (f'<circle {D} cx="{cx - 4 * s:.1f}" cy="{cy - .5 * s:.1f}" r="{1.7 * s:.1f}"/>'
                f'<circle {D} cx="{cx + 4 * s:.1f}" cy="{cy - .5 * s:.1f}" r="{1.7 * s:.1f}"/>')
    elif eyes == "closed":  # zufrieden geschlossen
        out += f'<path {L} d="M{p(-6, -.5)} Q{p(-4, 1.5)} {p(-2, -.5)} M{p(2, -.5)} Q{p(4, 1.5)} {p(6, -.5)}"/>'
    elif eyes == "squint":  # zugekniffen (Sturm)
        out += f'<path {L} d="M{p(-6, -2)} L{p(-2.5, -.3)} L{p(-6, 1.2)} M{p(6, -2)} L{p(2.5, -.3)} L{p(6, 1.2)}"/>'
    out += f'<path {D} d="M{p(-1.3, 2.6)} L{p(1.3, 2.6)} L{p(0, 4)} Z"/>'
    return out + _whiskers(cx, cy + 3 * s, 6 * s, 5.5 * s)


def _sitting_body(paws=2):
    tail = f'<path {L} d="M33 43.5 Q40 42 38.5 34 Q37.5 29.5 34 29"/>'
    body = f'<path {F} d="M13.5 18 C8 25 8 35 10 43.5 L30 43.5 C32 35 32 25 26.5 18"/>'
    feet = "M14.5 43.5 Q14.5 39.5 17.5 39.5 Q20 39.5 20 43.5"
    if paws == 2:
        feet += " Q20 39.5 22.5 39.5 Q25.5 39.5 25.5 43.5"
    return tail + body + f'<path {L} d="{feet}"/>'


# ---------------------------------------------------------------- Posen
# Jede Funktion gibt (Breite, Höhe, SVG-Inhalt) zurück. Unterkante = die Linie, auf der sie sitzt.

def sitzt():
    return 40, 44, _sitting_body() + _head(20, 13)


def putzt():
    tongue = f'<ellipse fill="{RED}" stroke="currentColor" cx="19.6" cy="18.6" rx="1.6" ry="1.9"/>'
    paw = (f'<path {F} d="M23.5 37 Q25 29 21.8 22 Q20.8 18.6 24 18.2 Q27.2 17.9 27.8 21.5 Q29.2 29 28.5 37"/>'
           f'<path {L} d="M22.6 20.6 Q24.8 19.6 27.2 20.4"/>')
    return 40, 44, _sitting_body(paws=1) + _head(20, 13, eyes="closed") + tongue + paw


def schmetterling():
    wing = f'fill="{YELLOW}" stroke="currentColor"'
    bf = (f'<g transform="translate(43 8) rotate(20)">'
          f'<path {wing} d="M0 2 Q-4 -7 -8.5 -4 Q-10 1 0 2 Z"/>'
          f'<path {wing} d="M0 2 Q4 -7 8.5 -4 Q10 1 0 2 Z"/>'
          f'<path {wing} d="M0 2 Q-6 3 -5 6.5 Q-2 7.5 0 2 Z"/>'
          f'<path {wing} d="M0 2 Q6 3 5 6.5 Q2 7.5 0 2 Z"/>'
          f'<path {L} d="M0 -2 L-2 -6.5 M0 -2 L2 -6.5"/></g>')
    eyes = f'<circle {D} cx="17" cy="11.4" r="1.7"/><circle {D} cx="25" cy="11.4" r="1.7"/>'
    head = f'<g transform="rotate(14 20 13)">{_head(20, 13, eyes="none")}{eyes}</g>'
    return 54, 44, _sitting_body() + head + bf


def schlaeft(zz_color=BLUE):
    zz = (f'<g stroke="{zz_color}" fill="none"><path d="M37 8 h5 l-5 5 h5"/>'
          f'<path d="M45 2 h3.5 l-3.5 3.5 h3.5"/></g>') if zz_color else ""
    body = f'<path {F} d="M5 29 Q3 13 22 11 Q42 10 47 23 Q48.5 29 44 29 Z"/>'
    tail = f'<path {L} d="M46.5 26 Q42 29.5 33 28 Q28.5 27.2 29.5 24.8"/>'
    head = (f'<path {F} d="M7 29 Q5 21 9.5 17.5 L10 10.5 L15 14.5 Q18 13.8 21 15 L26 12 L25.5 18.5'
            f' Q28.5 23.5 25 29 Z"/>'
            f'<path {L} d="M11.5 21.8 Q13.3 23.4 15.1 21.8 M18 21.8 Q19.8 23.4 21.6 21.8"/>'
            f'<path {D} d="M15.5 24.6 L18 24.6 L16.75 25.9 Z"/>')
    return 54, 30, body + tail + head + zz


def kastenbrot():
    body = (f'<path {F} d="M6 29.5 Q4 18 12 16 L36 15.5 Q44 17 42 29.5 Z"/>'
            f'<path {L} d="M42 25 Q47 25 46 20"/>')
    return 47, 30, body + _head(15, 15.5, 0.95, eyes="closed")


def lugt():
    paws = (f'<path {F} d="M5 24 Q5 18.5 9.5 18.5 Q14 18.5 14 24 Z"/>'
            f'<path {F} d="M20 24 Q20 18.5 24.5 18.5 Q29 18.5 29 24 Z"/>'
            f'<path {L} d="M8 24 V21.5 M11 24 V21.5 M23 24 V21.5 M26 24 V21.5"/>')
    return 34, 24, _head(17, 14) + paws


def spielt():
    yarn = (f'<g stroke="{RED}" fill="none">'
            f'<circle cx="7" cy="28.5" r="5" fill="var(--bg)"/>'
            f'<path d="M3 26 Q7 29 11.5 27 M2.6 29.5 Q7 32.5 11 31 M5 23.8 Q9 26 10.5 31.5"/>'
            f'<path d="M12 31 Q20 34 28 33"/></g>')
    tail = f'<path {L} d="M52 17 Q60 11 58 4.5 Q57 2 54.5 3.5"/>'
    body = (f'<path {F} d="M22 26.5 Q28 15 40 13.5 Q50 12.5 54 19 Q56.5 24 52 30 L48 33.5 L44 33.5'
            f' L46.5 28 Q38 30 30 30 L27 33.5 L23 33.5 Z"/>')
    paw = f'<path {F} d="M23 27 Q17 27 13.5 23.5 Q12.5 21.5 14.5 21.3 Q19 22 24 23.5"/>'
    head = (f'<path {F} d="M15 16 L14.5 6.5 L20 10 Q23 9.6 26 10.6 L30.5 7 L31 15.5 Q33 22 25 25.5'
            f' Q17 26 15 16 Z"/>'
            f'<circle {D} cx="20" cy="16" r="1.7"/><circle {D} cx="27" cy="16" r="1.7"/>'
            f'<path {D} d="M22.3 19.4 L24.7 19.4 L23.5 20.7 Z"/>')
    return 62, 34, yarn + tail + body + paw + head


def streckt():
    tail = f'<path {L} d="M49 10 Q52 4 49 1"/>'
    body = (f'<path {F} d="M20 22 Q31 18 43 10.5 Q49.5 7.5 51.5 13 Q53 20 51 33.5 L46 33.5 L45.2 24.5'
            f' Q36 29 26 30.5 Z"/>')
    legs = f'<path {F} d="M25 29 L6.5 31 Q4 31.3 4.2 32.5 Q4.4 33.5 6.5 33.5 L25 33.5 Z"/>'
    return 56, 34, tail + body + legs + _head(15, 22, 0.9, eyes="closed")


def gaehnt():
    """Sitzt und gähnt: Augen zugekniffen, Maul weit offen."""
    mouth = (f'<ellipse fill="currentColor" stroke="currentColor" cx="20" cy="19.6" rx="3" ry="3.4"/>'
             f'<ellipse fill="{RED}" stroke="none" cx="20" cy="21" rx="1.7" ry="1.4"/>')
    head = (f'<g transform="rotate(-10 20 13)">{_head(20, 13, eyes="none")}'
            f'<path {L} d="M14 12.6 Q16 11 18 12.6 M22 12.6 Q24 11 26 12.6"/>{mouth}</g>')
    return 40, 44, _sitting_body() + head


def _polar(cx, cy, rad, deg):
    a = math.radians(deg)
    return cx + rad * math.cos(a), cy + rad * math.sin(a)


def schwanzjagd():
    """Jagt den eigenen Schwanz: dreht den Kopf nach hinten, tatzt nach der Schwanzspitze, dreht sich."""
    spin = f'<path {L} d="M6 31 Q3.5 25.5 6.5 20 M54 31 Q56.5 25.5 53.5 20 M2 26.5 H3 M57 26.5 H58"/>'  # dreht sich
    tail = f'<path {L} d="M46 19 Q53 14 50 6.5 Q47 1 40 3 Q36 4.5 37 8"/>'
    body = (f'<path {F} d="M13 22.5 Q15 13.5 29 13 Q43 12.5 47 18.5 Q49 23 45 26.5 L44.5 33.5 L40.5 33.5'
            f' L40.5 28 Q31 29.5 22 28.5 L20.5 33.5 L16.5 33.5 L17 27 Q12.5 26 13 22.5 Z"/>')
    eyes = f'<circle {D} cx="13.6" cy="11.8" r="1.7"/><circle {D} cx="20.6" cy="9.6" r="1.7"/>'
    head = f'<g transform="rotate(28 15 13)">{_head(15, 13, 0.85, eyes="none")}</g>' + eyes
    swish = f'<path {L} d="M33 2.5 L30.5 1.5 M34 6 L31.5 6.5"/>'          # Schwanzspitze zuckt
    return 60, 34, f'<g transform="translate(3 0)">{tail}{body}{head}{swish}</g>' + spin


def ruecken():
    """Liegt ausgestreckt auf dem Rücken: Bauch nach oben, Pfötchen angewinkelt, Kopf zur Seite."""
    body = (f'<path {F} d="M14 25.5 Q14 13.5 31 13 Q47 13 49 25.5 Z"/>'
            f'<path {L} d="M25 18.5 Q31 16.8 37 18.5"/>')                     # Bauchfell
    legs = (f'<path {L} d="M20 15.5 Q18.5 9.5 22 7.8 Q24 7 24.5 9 M26.5 13.6 Q26.5 7.5 30.5 6.6 Q32.5 6.3 32.5 8.3'
            f' M38 13.8 Q39.5 7.8 43.5 7.5 Q45.5 7.5 45.2 9.5 M43.5 16 Q47 10.5 51 11 Q53 11.4 52 13.2"/>')
    tail = f'<path {L} d="M48.5 24 Q55 25.5 59 22 Q60.5 20.5 59 19.5"/>'
    head = (f'<g transform="rotate(-30 12 17)">{_head(12, 17, 0.85, eyes="closed")}</g>'
            f'<path {L} d="M10.6 21.3 Q12 22.6 13.4 21.3"/>')                     # zufriedenes Lächeln
    return 62, 26, legs + tail + body + head


def sonnt():
    """Wetterkatze bei Sonne: liegt lang ausgestreckt, Kopf auf den Pfoten, und genießt."""
    sun = (f'<g stroke="currentColor"><circle cx="51" cy="7" r="4.2" fill="{YELLOW}"/>'
           f'<path fill="none" d="M51 -0.5 V0.5 M58.5 7 H57.5 M56.3 1.7 L55.6 2.4 M56.3 12.3 L55.6 11.6'
           f' M45.7 1.7 L46.4 2.4"/></g>')
    body = f'<path {F} d="M15 27.5 Q15 16 31 15.5 Q46 15.5 48 27.5 Z"/>'
    tail = f'<path {L} d="M47.5 26 Q54 27.5 58.5 24"/>'
    paws = f'<path {F} d="M2.5 27.5 Q2.5 24 6 24 L17 24 L17 27.5 Z"/>'
    smile = f'<path {L} d="M11.8 23.4 Q13 24.6 14.2 23.4"/>'
    return 60, 28, body + tail + _head(13, 17, 0.9, eyes="closed") + smile + paws + sun


def sturm():
    """Wetterkatze bei Sturm: duckt sich flach auf die Linie, Fell und Schwanz im Wind."""
    wind = f'<path {L} d="M24 3 H33 M30 7.5 H40 M21 9.5 H26"/>'
    tail = f'<path {L} d="M46 20 Q52 16.5 56 19 Q59 21 61 18.5"/>'
    body = (f'<path {F} d="M14 25.5 Q13 15.5 28 14.5 Q42 14 47 19.5 Q49.5 25.5 45 25.5 Z"/>'
            f'<path {L} d="M30 14.5 l2 -2 M36 14.6 l2 -2 M42 16 l2 -2"/>')
    claws = (f'<path {F} d="M8 25.5 Q8 22 11.5 22 Q15 22 15 25.5 Z"/>'
             f'<path {L} d="M10 25.5 V27.2 M12.5 25.5 V27.2"/>')
    head = f'<g transform="rotate(-8 14 15)">{_head(14, 15, 0.85, eyes="squint")}</g>'
    return 62, 28, wind + tail + body + head + claws


def schirm():
    """Wetterkatze bei Regen: sitzt unter einem kleinen Schirm."""
    drops = f'<path stroke="{BLUE}" fill="none" d="M3 26 l-1 3 M6 36 l-1 3 M41 24 l-1 3 M43 35 l-1 3"/>'
    canopy = (f'<path fill="{BLUE}" stroke="currentColor" d="M3 17 Q23 -5 43 17 Q39.7 13.8 36.3 17'
              f' Q33 13.8 29.7 17 Q26.4 13.8 23 17 Q19.6 13.8 16.3 17 Q13 13.8 9.7 17 Q6.3 13.8 3 17 Z"/>'
              f'<path {L} d="M23 3.5 V1"/>')
    _, _, cat = sitzt()
    return 46, 54, drops + canopy + f'<g transform="translate(3 10)">{cat}</g>'


def schal():
    """Wetterkatze bei Frost oder Schnee: roter Schal wie das Kleidungssymbol."""
    _, _, cat = sitzt()
    scarf = (f'<path fill="{RED}" stroke="currentColor" d="M12 20 Q20 25.5 28 20 L28.6 24 Q20 29 11.4 24 Z"/>'
             f'<path fill="{RED}" stroke="currentColor" d="M23 25.5 L26.5 25 L27.5 33.5 L23.8 34 Z"/>')
    return 40, 44, cat + scarf


POSES = {
    "sitzt": sitzt, "putzt": putzt, "schmetterling": schmetterling, "schläft": schlaeft,
    "kastenbrot": kastenbrot, "lugt": lugt, "spielt": spielt, "streckt": streckt,
    "gähnt": gaehnt, "schwanzjagd": schwanzjagd, "rücken": ruecken,
    "sonnt": sonnt, "sturm": sturm, "schirm": schirm, "schal": schal,
}
# Zufällige Posen (ohne die Wetter-Posen)
EVERYDAY = ["sitzt", "putzt", "schmetterling", "gähnt", "schläft", "kastenbrot", "lugt", "spielt", "streckt",
            "schwanzjagd", "rücken"]
# Wetter (C): Anlass → Pose. Reihenfolge = Vorrang.
WEATHER_POSE = {"sturm": "sturm", "regen": "schirm", "schnee": "schal", "frost": "schal", "sonne": "sonnt"}
# Flache Posen passen auch auf Linien mit wenig Platz darüber
FLAT_MAX_H = 34
SPOTS = ["kopf", "tag", "mehr"]


def on_moon(cx, top, k=0.95, stroke=2.1, ring=1.6):
    """Nachtbild (seit 1.15): schlafende Katze auf dem Mond. cx = Mondmitte, top = Oberkante des Mondes
    (Mitte des Mondrings), in Einheiten der Nachtgrafik (ca. 0,92 px). Weißer Körper mit schwarzen Linien hebt
    sich vom Nachthimmel ab; ein „Z“ gelb wie die Sterne. Die Unterkante berührt den gelben Ring nur (keine
    Überdeckung): Kanten aus drei Farben (Schwarz, Gelb, Blau) kann eink.py nicht sauber einrasten, dann
    entstehen grüne und rote Einzelpixel. Ohne Zufall: Das Nachtbild bleibt die ganze Nacht gleich."""
    w, h, inner = schlaeft(zz_color=None)
    z = '<path stroke="#FFE500" fill="none" d="M38 4 h6.5 l-6.5 6.5 h6.5"/>'
    x = cx - 26 * k                               # Körpermitte der Pose liegt bei x ≈ 26
    bottom = top - ring / 2 - stroke / 2          # Linienunterkante = Außenkante des Rings
    y = bottom - 29 * k                           # Unterkante der Pose liegt bei y = 29
    return (f'<g transform="translate({x:.1f} {y:.1f}) scale({k})" stroke-width="{stroke / k:.2f}"'
            f' stroke-linecap="round" stroke-linejoin="round" style="color:#000000; --bg:#FFFFFF">{inner}{z}</g>')


def pose(name):
    """Pose als Wörterbuch für das Template: SVG, Breite, Höhe (Einheiten bei --u = 8 px)."""
    w, h, inner = POSES[name]()
    svg = (f'<svg class="cat" viewBox="0 0 {w} {h}" stroke-linecap="round" stroke-linejoin="round"'
           f' aria-hidden="true">{inner}</svg>')
    return {"name": name, "w": w, "h": h, "svg": svg}


def is_flat(name):
    return POSES[name]()[1] <= FLAT_MAX_H


# ---------------------------------------------------------------- Wetter (C)

def _current_hour(records, now):
    """Stundenwert der laufenden Stunde – wie im übrigen Dashboard nach dem Zeitstempel des Datensatzes
    (Tageskurve und „Regen 17–23 Uhr“ tun das auch; sonst hielte die Katze um 16:15 schon den Schirm,
    während darüber „Regen ab 17 Uhr“ steht)."""
    hour = now.replace(minute=0, second=0, microsecond=0)
    near = [r for r in records if abs(r["dt"] - hour) < timedelta(minutes=30)]
    return min(near, key=lambda r: abs(r["dt"] - hour)) if near else None


def weather_reason(records, now, nowcast=None, feels_like=None):
    """Warum die Katze sich anpasst: sturm, regen, schnee, frost, sonne – oder None."""
    r = _current_hour(records or [], now)
    if r is None:
        return None
    gust = r.get("wind_gust_speed") or 0
    if gust >= STORM_GUST:
        return "sturm"
    kind = {r.get("icon"), r.get("condition")}
    snowy = bool(kind & {"snow", "sleet"})
    wet = ((r.get("precipitation") or 0) >= RAIN_MM or bool(kind & {"rain", "hail", "thunderstorm"})
           or (nowcast or {}).get("state") == "jetzt")
    if snowy:
        return "schnee"
    if wet:
        return "regen"
    temp = r.get("temperature")
    felt = feels_like(temp, r.get("wind_speed"), r.get("relative_humidity")) if feels_like else temp
    if felt is not None and felt <= FROST_FEELS:
        return "frost"
    if (r.get("sunshine") or 0) >= SUN_MIN and temp is not None and temp >= SUN_TEMP:
        return "sonne"
    return None


# ---------------------------------------------------------------- Auswahl (B)

def slot_of(now):
    """Nummer des 15-Minuten-Abschnitts seit Mitternacht."""
    return (now.hour * 60 + now.minute) // SLOT_MIN


def _day_order(items, day, salt):
    order = list(items)
    random.Random(f"{day.isoformat()}/{salt}").shuffle(order)
    return order


def choose(now, records=None, nowcast=None, weather=True, feels_like=None):
    """Was die Katze diesmal tut und wo sie es zuerst versucht.

    main  – Pose, die sie am liebsten zeigt (Wetter-Pose oder die nächste des Tages)
    flat  – flache Pose für Linien mit wenig Platz darüber
    spots – Reihenfolge der Plätze (kopf, tag, mehr); das Skript im Template nimmt den ersten,
            an dem eine der beiden Posen frei steht
    seed  – Startpunkt für die Lage auf der Linie (wiederholbar)
    """
    slot = slot_of(now)
    day = now.date()
    everyday = _day_order(EVERYDAY, day, "pose")
    reason = weather_reason(records, now, nowcast, feels_like) if weather else None
    main = WEATHER_POSE[reason] if reason else everyday[slot % len(everyday)]
    flat = main if is_flat(main) else next(
        p for i in range(1, len(everyday) + 1) if is_flat(p := everyday[(slot + i) % len(everyday)]))
    spots = _day_order(SPOTS, day, "spot")
    k = slot % len(spots)
    spots = spots[k:] + spots[:k]
    if reason and not is_flat(main):  # Schirm und Schal brauchen Höhe: zuerst die Kopfzeile
        spots.remove("kopf")
        spots.insert(0, "kopf")
    seed = random.Random(f"{day.isoformat()}/{slot}").randrange(1000)
    return {"main": pose(main), "flat": pose(flat), "spots": spots, "seed": seed, "reason": reason}
