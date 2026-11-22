"""Die kleine Katze im Tagesdashboard (seit 1.14, Variante B + C).

B – Versteckspiel: Die Katze sitzt jedes Mal auf einer anderen Linie (Kopfzeile, Linie
    unter einer Tages-Überschrift, gestrichelte Linie über „+ weitere Termine“). Welcher
    Platz frei ist, weiß erst der Browser: Das Skript `placeCat()` im Template misst das
    fertige Layout und nimmt den ersten Platz der Reihenfolge, an dem die Katze nichts
    verdeckt. Passt sie nirgends hin, fehlt sie eben.
C – Wetterkatze: Bei Sturm hält sie sich fest, bei Regen sitzt sie unter dem Schirm, bei
    Schnee oder Frost trägt sie Schal, bei Sonne liegt sie auf dem Rücken. Seit 1.34 hat jede
    Wetterlage drei Posen, die sich abwechseln (WEATHER_POSES). Sonst kommt eine zufällige Pose.

Zufall: Er hängt am Datum und am 15-Minuten-Abschnitt der Uhrzeit. Dasselbe Datum und
dieselbe Uhrzeit ergeben dieselbe Katze (Tests sind wiederholbar), und zwei aufeinander-
folgende Abschnitte haben nie dieselbe Pose (die Posen eines Tages sind gemischt und
werden der Reihe nach durchlaufen).

Zeichnung: eigene Linien-SVGs, 1 Einheit = 1 px bei 800×480 (--u = 8 px). Die Strichstärke
hängt nicht an der Skalierung (vector-effect: non-scaling-stroke), sondern an --u, damit
die Katze so kräftig ist wie die übrigen Linien. Farbtupfer nur in Displayfarben.
"""
import random
from datetime import timedelta

# Farben als CSS-Variablen: Im Schwarz-Weiß-Modus (.mono) werden sie zur Textfarbe
RED, YELLOW, BLUE = "var(--cat-red)", "var(--cat-yellow)", "var(--cat-blue)"
GREEN = "var(--cat-green)"  # seit 1.34 (Blätter; Schwarz-Weiß: Hintergrund → nur Kontur)
GREEN_INK = "var(--cat-green-ink)"  # seit 1.35 für grüne Linien (Schwarz-Weiß: Textfarbe, sonst unsichtbar)

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


def _playing():
    """Katze geduckt und spielbereit, ohne Spielzeug (für spielt, maus, socke)."""
    tail = f'<path {L} d="M52 17 Q60 11 58 4.5 Q57 2 54.5 3.5"/>'
    body = (f'<path {F} d="M22 26.5 Q28 15 40 13.5 Q50 12.5 54 19 Q56.5 24 52 30 L48 33.5 L44 33.5'
            f' L46.5 28 Q38 30 30 30 L27 33.5 L23 33.5 Z"/>')
    paw = f'<path {F} d="M23 27 Q17 27 13.5 23.5 Q12.5 21.5 14.5 21.3 Q19 22 24 23.5"/>'
    head = (f'<path {F} d="M15 16 L14.5 6.5 L20 10 Q23 9.6 26 10.6 L30.5 7 L31 15.5 Q33 22 25 25.5'
            f' Q17 26 15 16 Z"/>'
            f'<circle {D} cx="20" cy="16" r="1.7"/><circle {D} cx="27" cy="16" r="1.7"/>'
            f'<path {D} d="M22.3 19.4 L24.7 19.4 L23.5 20.7 Z"/>')
    return tail + body + paw + head


def spielt():
    """Tatzt nach einem Wollknäuel."""
    yarn = (f'<g stroke="{RED}" fill="none">'
            f'<circle cx="7" cy="28.5" r="5" fill="var(--bg)"/>'
            f'<path d="M3 26 Q7 29 11.5 27 M2.6 29.5 Q7 32.5 11 31 M5 23.8 Q9 26 10.5 31.5"/>'
            f'<path d="M12 31 Q20 34 28 33"/></g>')
    return 62, 34, yarn + _playing()


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
    # Kopf 2 Einheiten höher: gedreht ragte das Kinn sonst unter die Linie (seit 1.20, test_katze prüft das)
    return 62, 26, legs + tail + body + f'<g transform="translate(0 -2)">{head}</g>'


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


# ---------------------------------------------------------------- seit 1.20

def maus():
    """Geduckt auf der Lauer, Hinterteil hoch – vorne flitzt eine Maus davon.
    Maus groß und schlicht: Tropfenkörper, ein deutlich abgesetztes rundes Ohr, langer Schwanz."""
    mouse = (f'<path {L} d="M22 31 Q28 25 32 29.5 Q34 31.5 36.5 28.5"/>'                # Schwanz
             f'<path {F} d="M0.5 30.5 Q6 22 14 21.5 Q23 21.3 23 30 L22.5 33.5 H6 Q2 33 0.5 30.5 Z"/>'  # Körper, Nase links
             f'<circle {F} cx="10.5" cy="20.5" r="4.2"/>'                                # Ohr vorne oben
             f'<circle {D} cx="5.5" cy="27" r="1.5"/>'                                    # Auge
             f'<circle {D} cx="0.9" cy="30.4" r="1.2"/>')                                 # Nase
    cat = _playing()
    return 92, 34, mouse + f'<g transform="translate(30 0)">{cat}</g>'


def laser():
    """Sitzt starr und starrt auf einen roten Laserpunkt vor den Pfoten: große Pupillen nach unten rechts."""
    dot = (f'<circle fill="{RED}" stroke="none" cx="47" cy="40.5" r="3.4"/>'
           f'<path stroke="{RED}" fill="none" d="M47 33.5 V32 M41 37 L40 36 M53 37 L54 36"/>')
    eyes = f'<circle {D} cx="16.8" cy="13.4" r="2.5"/><circle {D} cx="24.8" cy="13.4" r="2.5"/>'
    return 56, 44, _sitting_body() + _head(20, 13, eyes="none") + eyes + dot


def socke():
    """Abends zur Wäsche-Karte: tobt mit einer Socke (blau, rote Spitze, weißer Bund) statt mit dem Wollknäuel."""
    cat = _playing()
    sock = (f'<g transform="rotate(-10 11 26)">'
            f'<path fill="{BLUE}" stroke="currentColor" d="M3 16 H15 V26 Q15 28 17.5 29 L21 30.5'
            f' Q25 32.2 24 34 Q23 35.6 19.5 34.8 L9 32.5 Q3 31 3 25 Z"/>'
            f'<path fill="{RED}" stroke="currentColor" d="M19 29.6 L21 30.5 Q25 32.2 24 34 Q23 35.6 19.5 34.8 L17.5 34.3 Q19.5 32 19 29.6 Z"/>'
            f'<path fill="var(--bg)" stroke="currentColor" d="M2.5 12 H15.5 V17 H2.5 Z"/></g>')
    return 74, 34, f'<g transform="translate(0 -2)">{sock}</g>' + f'<g transform="translate(12 0)">{cat}</g>'


def karton():
    """„If it fits, I sits“: sitzt in einem Karton, nur Kopf und Pfoten schauen raus."""
    flaps = (f'<path {F} d="M5 25 L0.5 18 L13 18 L16 25 Z"/>'
             f'<path {F} d="M37 25 L41.5 18 L29 18 L26 25 Z"/>')
    box = f'<path {F} d="M5 25 H37 V43.5 H5 Z"/>'
    paws = (f'<path {F} d="M11 25 Q11 21.5 14 21.5 Q17 21.5 17 25"/>'
            f'<path {F} d="M25 25 Q25 21.5 28 21.5 Q31 21.5 31 25"/>')
    return 42, 44, flaps + _head(21, 17, 1.0) + box + paws


def tasse():
    """Schubst mit der Pfote eine Tasse über die Kante – mit Unschuldsblick.
    Tasse größer und mit Abstand zur Katze, Pfote berührt nur den Rand, ein Dampfkringel."""
    cup = (f'<g transform="translate(0 -0.6) rotate(20 56.5 43.5)">'
           f'<path fill="{RED}" stroke="currentColor" d="M43 28 H58 L57 42 Q56.5 43.5 55 43.5 H46 Q44.5 43.5 44 42 Z"/>'
           f'<path {L} d="M58 31.5 Q63.5 31.5 63 35.8 Q62.5 39 57.2 39"/>'
           f'<path {L} d="M49.5 24 Q47 21 49.5 18 Q52 15 49.5 12"/></g>')
    paw = f'<path {F} d="M27 30 Q34 26.5 41.5 27 Q43.8 27.5 43 29.5 Q41.8 31.5 36 31.3 Q31 31.4 27.5 34"/>'
    eyes = f'<path {L} d="M14 12.5 Q16 10.6 18 12.5 M22 12.5 Q24 10.6 26 12.5"/>'
    head = f'<g transform="rotate(-8 20 13)">{_head(20, 13, eyes="none")}{eyes}</g>'
    return 68, 44, _sitting_body() + head + paw + cup


def spaziert():
    """Spaziert die Linie entlang, Schwanz hoch, hinter sich große, einfache Pfotenabdrücke."""
    def print_(x):
        return (f'<g {D}><ellipse cx="{x}" cy="31.6" rx="2.6" ry="1.9"/>'
                f'<circle cx="{x - 2.6}" cy="27.6" r="1.1"/><circle cx="{x + 2.6}" cy="27.6" r="1.1"/></g>')
    prints = print_(54) + print_(64)
    tail = f'<path {L} d="M41 15 Q46 9 43 3 Q41.5 0.8 39.5 2.5"/>'
    back_legs = f'<path {L} d="M17 23 L13.5 33.5 M37 22 L40.5 33.5"/>'
    body = f'<path {F} d="M11 17.5 Q13 11.5 26 11.5 Q38 11 41.5 16 Q43.5 21 38.5 24 Q26 26.5 14 24.5 Q9.5 22.5 11 17.5 Z"/>'
    front_legs = f'<path {L} d="M20 24.5 L22.5 33.5 H25 M33 24 L31 33.5 H33.5"/>'
    return 68, 34, prints + tail + back_legs + body + front_legs + _head(12, 12, 0.9)


def zeitung():
    """Im Nachrichtenfenster: liest Zeitung. Große weiße Seite mit fetter Schlagzeile und
    nur zwei Textzeilen – so bleibt sie auch bei 2,4 px Strich als Zeitung erkennbar."""
    paper = (f'<path {F} d="M3 20 L37 18.5 L38 41 L4 42.5 Z"/>'
             f'<path fill="currentColor" stroke="currentColor" d="M8 23.3 L28 22.5 L28.2 25.5 L8.2 26.3 Z"/>'
             f'<path {L} d="M8.5 32 L33 31 M8.8 37.5 L25 36.8"/>')
    eyes = f'<circle {D} cx="16" cy="14" r="1.8"/><circle {D} cx="24" cy="14" r="1.8"/>'
    paws = (f'<path {F} d="M1 30 Q1 26.5 4 26.5 Q7 26.5 7 30 Q7 33.5 4 33.5 Q1 33.5 1 30 Z"/>'
            f'<path {F} d="M34 29 Q34 25.5 37 25.5 Q40 25.5 40 29 Q40 32.5 37 32.5 Q34 32.5 34 29 Z"/>')
    return 42, 44, _sitting_body() + _head(20, 13, eyes="none") + eyes + paper + paws


def koffer():
    """Am Zug-Dienstag im Zeitfenster: sitzt reisefertig neben ihrem Köfferchen."""
    case = (f'<path fill="{RED}" stroke="currentColor" d="M37 30 H53 Q54.5 30 54.5 31.5 V42 Q54.5 43.5 53 43.5'
            f' H37 Q35.5 43.5 35.5 42 V31.5 Q35.5 30 37 30 Z"/>'
            f'<path {L} d="M41.5 30 V27.5 H48.5 V30 M45 30 V43.5"/>')
    return 58, 44, _sitting_body() + _head(20, 13) + case


def partyhut():
    """An Geburtstagen aus Leons Liste: großes gelbes Partyhütchen mit rotem Band und Bommel."""
    hat = (f'<path fill="{YELLOW}" stroke="currentColor" d="M12.5 5 L20 -10 L27.5 5 Q20 7.4 12.5 5 Z"/>'
           f'<path fill="{RED}" stroke="none" d="M15.2 -0.4 L24.8 -0.4 L26 2.2 L14 2.2 Z"/>'
           f'<circle fill="{RED}" stroke="currentColor" cx="20" cy="-11.5" r="3"/>')
    # Das Hütchen ragt über den Kopf hinaus: alles 15 Einheiten tiefer, damit es in der viewBox liegt
    # (placeCat rechnet mit der viewBox; was darüber hinausragt, könnte Text überdecken).
    return 40, 59, f'<g transform="translate(0 15)">{_sitting_body()}{_head(20, 13)}{hat}</g>'


# ---------------------------------------------------------------- Ostereier (seit 1.24, ostereier.py wählt)

def narr():
    """Karneval: Narrenkappe in den Bonner Stadtfarben Rot und Gelb, Schellen an den Zipfeln."""
    cap = (f'<path fill="{RED}" stroke="currentColor" d="M10.5 7 Q5 1 2.5 -6.5 Q11 -4.5 20 3.5 Z"/>'
           f'<path fill="{YELLOW}" stroke="currentColor" d="M29.5 7 Q35 1 37.5 -6.5 Q29 -4.5 20 3.5 Z"/>'
           f'<path fill="{YELLOW}" stroke="currentColor" d="M9.5 5.5 Q20 1 30.5 5.5 L30.5 8.8 Q20 4.5 9.5 8.8 Z"/>'
           f'<circle fill="{YELLOW}" stroke="currentColor" cx="2.5" cy="-7.5" r="2.4"/>'
           f'<circle fill="{RED}" stroke="currentColor" cx="37.5" cy="-7.5" r="2.4"/>')
    return 40, 55, f'<g transform="translate(0 11)">{_sitting_body()}{_head(20, 13)}{cap}</g>'


def dirigent():
    """17.12. (Beethovens Taufe in Bonn): dirigiert mit erhobenem Taktstock, zwei Noten schweben."""
    def note(x, y):
        return (f'<ellipse fill="{BLUE}" stroke="currentColor" cx="{x}" cy="{y}" rx="2.6" ry="1.9"'
                f' transform="rotate(-20 {x} {y})"/>'
                f'<path {L} d="M{x + 2.3} {y - .6} V{y - 9} Q{x + 6} {y - 7} {x + 6.2} {y - 3.5}"/>')
    paw = (f'<path {F} d="M26 31 Q31 26.5 33 20 Q33.8 17 36.3 17.8 Q38.6 18.8 37.5 21.6 Q35.2 28.5 29.5 34.5"/>')
    baton = f'<path {L} d="M36.5 17.5 L44 7"/>'
    eyes = f'<path {L} d="M14 12.6 Q16 14.6 18 12.6 M22 12.6 Q24 14.6 26 12.6"/>'
    head = f'<g transform="rotate(-8 20 13)">{_head(20, 13, eyes="none")}{eyes}</g>'
    return 56, 44, _sitting_body(paws=1) + head + paw + baton + note(47, 22) + note(40, 33.5)


def schwarz():
    """Freitag, der 13.: Eine schwarze Katze läuft über die Linie (die spazierende Katze, ganz schwarz,
    gelbe Augen)."""
    w, h, inner = spaziert()
    inner = inner.replace('fill="var(--bg)"', 'fill="currentColor"')
    eyes = (f'<circle fill="{YELLOW}" stroke="none" cx="8.4" cy="11.6" r="1.7"/>'
            f'<circle fill="{YELLOW}" stroke="none" cx="15.6" cy="11.6" r="1.7"/>')
    return w, h, inner + eyes


def himbeerkuchen():
    """14.3. (π-Tag) auf einem Raspberry Pi: neben der Katze steht ein großes π auf einem Kuchen mit zwei
    Himbeeren. Das π aus einfachen Linien (gefüllt wirkte es bei ~40 px wie ein Tisch), die Himbeeren auf dem
    Kuchen (oben auf dem π sahen sie aus wie zwei Köpfe)."""
    pie = (f'<path fill="{YELLOW}" stroke="currentColor" d="M38 37.5 H62 L60.5 43.5 H39.5 Z"/>'
           f'<path {L} d="M39.5 20 Q41 18 44 18.5 H60.5 M46 18.8 Q46.5 31 42.5 37.5 M54.5 18.8 V33 Q54.5 36.5 59 35"/>'
           f'<circle fill="{RED}" stroke="currentColor" cx="40.6" cy="35" r="2.4"/>'
           f'<circle fill="{RED}" stroke="currentColor" cx="49.8" cy="35" r="2.4"/>')
    return 64, 44, _sitting_body() + _head(20, 13) + pie


def kuerbis():
    """31.10.: sitzt neben einem Kürbis mit großen Dreieckaugen und Zackenmund (Gelb statt Orange –
    Orange kann das Display nicht)."""
    pumpkin = (f'<path {L} d="M51 25.5 Q51 21.5 54 20"/>'
               f'<path fill="{YELLOW}" stroke="currentColor" d="M51 25.5 Q38.5 24 38.5 34.5 Q38.5 43.5 51 43.5'
               f' Q63.5 43.5 63.5 34.5 Q63.5 24 51 25.5 Z"/>'
               f'<path {D} d="M42.5 33 L48 33 L45.2 28 Z M54 33 L59.5 33 L56.8 28 Z'
               f' M43 36 L59 36 Q57.5 41 51 41 Q44.5 41 43 36 Z"/>')
    return 64, 44, _sitting_body() + _head(20, 13) + pumpkin


def grundgesetz():
    """23.5. (Grundgesetz, 1949 in Bonn verkündet): hält ein Buch in Schwarz-Rot-Gold vor der Brust."""
    book = (f'<path fill="currentColor" stroke="currentColor" d="M9.5 24 H30.5 V29 H9.5 Z"/>'
            f'<path fill="{RED}" stroke="none" d="M9.5 29 H30.5 V34 H9.5 Z"/>'
            f'<path fill="{YELLOW}" stroke="none" d="M9.5 34 H30.5 V39.5 H9.5 Z"/>'
            f'<path {L} d="M9.5 24 H30.5 V39.5 H9.5 Z"/>')
    paws = (f'<path {F} d="M6 38 Q6 34.5 9 34.5 Q12 34.5 12 38 Q12 41 9 41 Q6 41 6 38 Z"/>'
            f'<path {F} d="M28 38 Q28 34.5 31 34.5 Q34 34.5 34 38 Q34 41 31 41 Q28 41 28 38 Z"/>')
    return 40, 44, _sitting_body() + _head(20, 13) + book + paws


# ---------------------------------------------------------------- Ratssitzung (seit 1.27, solange die Livestream-Karte steht)

def rednerpult():
    """Spricht am Rednerpult ins Mikrofon: breites blaues Pult verdeckt den Körper, großer roter
    Mikrofonkopf am Schwanenhals rechts neben dem Gesicht."""
    desk = (f'<path fill="{BLUE}" stroke="currentColor" d="M3 23.5 L37 21 L34.5 43.5 H5.5 Z"/>'
            f'<path {L} d="M13 31 H27"/>')
    mic = (f'<path {L} d="M33.5 21.5 Q35.5 15 33.5 12.5"/>'
           f'<circle fill="{RED}" stroke="currentColor" cx="32.5" cy="10.5" r="3"/>')
    return 41, 44, _head(17, 12) + desk + mic


def akten():
    """Spät in der Ratssitzung (ab RAT_LATE_HOUR): schläft auf einem Stapel bunter Aktenordner."""
    w, h, cat = schlaeft()
    stack = (f'<path fill="{BLUE}" stroke="currentColor" d="M4 30 H46 V34.5 H4 Z"/>'
             f'<path fill="{RED}" stroke="currentColor" d="M7 34.5 H49 V39 H7 Z"/>'
             f'<path fill="{YELLOW}" stroke="currentColor" d="M3 39 H45 V43.5 H3 Z"/>'
             f'<path {L} d="M38 32.2 H42 M41 36.7 H45 M37 41.2 H41"/>')
    return 54, 44, f'<g transform="translate(0 1)">{cat}</g>' + stack


# ---------------------------------------------------------------- seit 1.34: Wetter-Varianten, Alltag, Advent
# Je Wetterlage zwei Varianten zur bisherigen Pose (WEATHER_POSES); sie wechseln sich reihum ab.

# ------------------------------------------------------------ Regen
def suedwester():
    """Regen: gelber Südwester, Tropfen ringsum."""
    # eine Form statt Kuppel + Krempe, ohne schwarzes Hutband: schmale gelbe Streifen und schwarze Linien auf Gelb
    # gaben rote Streupixel (dev/katze_pruefstand.py)
    hat = (f'<path fill="{YELLOW}" stroke="currentColor" d="M3 8 Q4 5.6 9 5.3 Q9.5 -4.5 20 -4.5 Q30.5 -4.5 31 5.3'
           f' Q36 5.6 37 8 Q38.5 11.2 35 10.6 Q20 7.6 5 10.6 Q1.5 11.2 3 8 Z"/>')
    drops = f'<path stroke="{BLUE}" fill="none" d="M2 21 l-1 3 M4 32 l-1 3 M42 18 l-1 3 M43 30 l-1 3"/>'
    return 44, 50, f'<g transform="translate(2 6)">{_sitting_body()}{_head(20, 13)}{hat}</g>' + drops


def fenster():
    """Regen: schaut hinter der Scheibe hinaus, dicke Tropfen laufen außen herunter."""
    frame = f'<path {L} d="M2 2 H46 V43.5 H2 Z M2 34 H46"/>'
    paws = (f'<path {F} d="M12 34 Q12 29.5 15.5 29.5 Q19 29.5 19 34 Z"/>'
            f'<path {F} d="M29 34 Q29 29.5 32.5 29.5 Q36 29.5 36 34 Z"/>')
    def drop(x, y):
        return f'<path d="M{x} {y} Q{x + 3} {y + 4.5} {x + 3} {y + 6.5} A3 3 0 0 1 {x - 3} {y + 6.5} Q{x - 3} {y + 4.5} {x} {y} Z"/>'
    drops = f'<g fill="{BLUE}" stroke="none">{drop(7.5, 6)}{drop(40.5, 10)}{drop(7.5, 21)}{drop(40.5, 24)}</g>'
    return 48, 44, _head(24, 22) + paws + frame + drops

# ------------------------------------------------------------ Schnee

def schneeflocke():
    """Schnee: schaut hoch zu einer großen Flocke, Pfote reckt sich."""
    def flake(cx, cy, r):
        p = ""
        for dx, dy in ((0, 1), (.87, .5), (.87, -.5)):
            p += f"M{cx - dx * r:.1f} {cy - dy * r:.1f} L{cx + dx * r:.1f} {cy + dy * r:.1f} "
        return f'<path stroke="{BLUE}" fill="none" d="{p}"/>'
    eyes = f'<circle {D} cx="22" cy="9.6" r="1.7"/><circle {D} cx="29" cy="11.2" r="1.7"/>'
    head = f'<g transform="rotate(18 20 13)">{_head(20, 13, eyes="none")}</g>' + eyes
    paw = f'<path {F} d="M26 33 Q32 26 34 18 Q35 15.3 37.4 16.2 Q39.5 17.3 38.5 20 Q36 29 30 36"/>'
    # 1,5 tiefer: das schräge Ohr ragte sonst 1 Einheit über die viewBox (test_katze misst das)
    inner = _sitting_body(paws=1) + head + paw + flake(46, 7, 6) + flake(52, 21, 3.5)
    return 56, 45.5, f'<g transform="translate(0 1.5)">{inner}</g>'


def schneemann():
    """Schnee: sitzt neben ihrem kleinen Schneemann mit Hut und gelber Nase."""
    man = (f'<circle {F} cx="54" cy="35.5" r="8"/>'
           f'<circle {F} cx="54" cy="21.5" r="6.2"/>'
           f'<path fill="currentColor" stroke="currentColor" d="M48 15 H60 M50.5 15 V9 H57.5 V15"/>'
           f'<circle {D} cx="51.7" cy="20.3" r="1.2"/><circle {D} cx="56.3" cy="20.3" r="1.2"/>'
           f'<path fill="{YELLOW}" stroke="currentColor" d="M53.6 22.4 L60 24 L53.6 25.2 Z"/>'
           f'<circle {D} cx="54" cy="33" r="1.2"/><circle {D} cx="54" cy="38" r="1.2"/>')
    return 64, 44, _sitting_body() + _head(20, 13) + man


# ------------------------------------------------------------ Frost
def muetze():
    """Frost: rote Bommelmütze, darunter schauen die Ohrspitzen raus."""
    hat = (f'<path fill="{RED}" stroke="currentColor" d="M10 5 Q10.5 -5.5 20 -5.5 Q29.5 -5.5 30 5 Z"/>'
           f'<path fill="var(--bg)" stroke="currentColor" d="M9 4 H31 V8 H9 Z"/>'
           f'<circle fill="{YELLOW}" stroke="currentColor" cx="20" cy="-8" r="3.2"/>')
    return 40, 56, f'<g transform="translate(0 12)">{_sitting_body()}{_head(20, 13)}{hat}</g>'


def decke():
    """Frost: als Kastenbrot unter einer blauen Decke, nur der Kopf schaut raus."""
    _, _, bread = kastenbrot()
    blanket = (f'<path fill="{BLUE}" stroke="currentColor" d="M21 29.5 L22.5 18 Q33 15 42.5 17.5 Q46.5 23 44.5 29.5 Z"/>'
               f'<path {L} d="M22.5 18 Q24 23 21 29.5"/>')
    return 47, 30, bread + blanket

# ------------------------------------------------------------ Sonne

def sonnenbrille():
    """Sonne: sitzt lässig mit dunkler Sonnenbrille, kleine Sonne daneben."""
    glasses = (f'<path fill="currentColor" stroke="currentColor" d="M12.5 11.5 H18.5 Q18.5 15.5 15.5 15.5 Q12.5 15.5 12.5 11.5 Z'
               f' M21.5 11.5 H27.5 Q27.5 15.5 24.5 15.5 Q21.5 15.5 21.5 11.5 Z"/>'
               f'<path {L} d="M18.5 12 H21.5"/>')
    smile = f'<path {L} d="M18.3 18.6 Q20 20 21.7 18.6"/>'
    sun = (f'<g stroke="currentColor"><circle cx="46" cy="9" r="4.2" fill="{YELLOW}"/>'
           f'<path fill="none" d="M46 1.5 V2.5 M53.5 9 H52.5 M51.3 3.7 L50.6 4.4 M51.3 14.3 L50.6 13.6'
           f' M40.7 3.7 L41.4 4.4 M38.5 9 H39.5"/></g>')
    return 56, 44, _sitting_body() + _head(20, 13, eyes="none") + glasses + smile + sun


def eis():
    """Sonne: schleckt ein großes Eis (gelbe Waffel, rote Kugel), Pfote hält die Waffel."""
    tongue = f'<ellipse fill="{RED}" stroke="currentColor" cx="24" cy="18" rx="1.6" ry="1.9"/>'
    cone = (f'<path fill="{YELLOW}" stroke="currentColor" d="M28.5 20 L39.5 20 L34 36 Z"/>'
            f'<circle fill="{RED}" stroke="currentColor" cx="34" cy="16" r="5.5"/>')
    head = f'<g transform="rotate(8 20 13)">{_head(20, 13, eyes="closed")}</g>'
    return 44, 44, _sitting_body() + head + tongue + cone

# ------------------------------------------------------------ Sturm

def drachen():
    """Sturm: hält die Schnur eines Drachens, der hoch im Wind steht."""
    kite = (f'<path fill="{RED}" stroke="currentColor" d="M52 1 L60 9 L52 19 L44 9 Z"/>'
            f'<path fill="{YELLOW}" stroke="none" d="M52 1.6 L59.2 9 H44.8 Z"/>'
            f'<path {L} d="M52 1 L60 9 L52 19 L44 9 Z"/>'
            f'<path {L} d="M52 19 Q55 23 52 26 Q49 29 52 32"/>'
            f'<path {L} d="M35 21 Q44 17 52 19"/>')
    paw = f'<path {F} d="M26 33 Q31 28 32.5 22 Q33.3 19 35.8 19.8 Q38 20.8 37 23.6 Q35 30 29.5 36"/>'
    head = f'<g transform="rotate(10 20 13)">{_head(20, 13)}</g>'
    return 62, 44, _sitting_body(paws=1) + head + paw + kite


def blaetter():
    """Sturm: sitzt mit zugekniffenen Augen, Blätter wirbeln vorbei, Schwanz weht."""
    wind = f'<path {L} d="M30 6 H44 M34 12 H50 M40 26 H50"/>'
    def leaf(x, y, c, rot):
        return (f'<g transform="rotate({rot} {x} {y})"><path fill="{c}" stroke="currentColor"'
                f' d="M{x - 4} {y} Q{x} {y - 4} {x + 4} {y} Q{x} {y + 4} {x - 4} {y} Z"/></g>')
    tail = f'<path {L} d="M30 43.5 Q37 43 40 39 Q42 36 46 37"/>'
    body = f'<path {F} d="M13.5 18 C8 25 8 35 10 43.5 L30 43.5 C32 35 32 25 26.5 18"/>'
    feet = f'<path {L} d="M14.5 43.5 Q14.5 39.5 17.5 39.5 Q20 39.5 20 43.5 Q20 39.5 22.5 39.5 Q25.5 39.5 25.5 43.5"/>'
    head = f'<g transform="rotate(-8 20 13)">{_head(20, 13, eyes="squint")}</g>'
    return 56, 44, (tail + body + feet + head + wind + leaf(50, 4, GREEN, 30) + leaf(52, 19, YELLOW, -20)
                    + leaf(36, 33, GREEN, 60))

# ------------------------------------------------------------ Alltag

def winkt():
    """Alltag: Winkekatze – eine Pfote hoch, zwei Bewegungsbögen."""
    paw = f'<path {F} d="M26 31 Q31 25 31.5 16 Q31.8 12.5 34.4 12.8 Q37 13.3 36.6 16.4 Q35.8 26.5 29.5 34.5"/>'
    lines = f'<path {L} d="M38.5 8 Q41.5 10.5 41 15 M42.5 6 Q46.5 10 45.5 16.5"/>'
    return 48, 44, _sitting_body(paws=1) + _head(20, 13) + paw + lines


def pflanze():
    """Alltag: knabbert an einer Topfpflanze (roter Topf, grüne Blätter)."""
    plant = (f'<path fill="{RED}" stroke="currentColor" d="M41 32 H57 L55 43.5 H43 Z"/>'
             f'<path fill="{GREEN}" stroke="currentColor" d="M49 32 Q41 25 35 22 Q42 20 49 30 Z"/>'
             f'<path fill="{GREEN}" stroke="currentColor" d="M49 32 Q47 20 50 12 Q55 20 49 32 Z"/>'
             f'<path fill="{GREEN}" stroke="currentColor" d="M49 32 Q55 24 61 23 Q57 31 49 32 Z"/>')
    head = f'<g transform="rotate(14 20 13)">{_head(20, 13, eyes="closed")}</g>'
    return 62, 44, _sitting_body() + head + plant


def fisch():
    """Alltag: stolz mit einem großen blauen Fisch im Maul."""
    fish = (f'<path fill="{BLUE}" stroke="currentColor" d="M8 23 Q16 17 25 21.5 L32 17.5 L31 23.5 L32.5 29.5 L25 25'
            f' Q16 29.5 8 23 Z"/>'
            f'<circle fill="var(--bg)" stroke="none" cx="12.5" cy="22.5" r="1.4"/>')
    return 40, 44, _sitting_body() + _head(20, 11.5, eyes="closed") + fish


def lichterkette():
    """Advent: hat sich eine Lichterkette umgelegt, die bis auf die Linie hängt (rot, gelb, blau)."""
    def bulb(x, y, c):
        return (f'<path fill="{c}" stroke="currentColor"'
                f' d="M{x - 2.4} {y} Q{x - 2.9} {y + 5} {x} {y + 6.3} Q{x + 2.9} {y + 5} {x + 2.4} {y} Z"/>')
    wire = f'<path {L} d="M1 43.5 Q3 30 11 22 Q20 27 29 22 Q37 26 39 31 Q41 38 47 43.5"/>'
    bulbs = bulb(4, 32, RED) + bulb(14, 24, YELLOW) + bulb(25, 24, BLUE) + bulb(37, 28, RED) + bulb(43, 37, YELLOW)
    return 50, 44, _sitting_body() + _head(20, 13) + wire + bulbs


# ---------------------------------------------------------------- seit 1.35: Nebel, Gewitter, Anlässe zu Karten,
# Ort und Zeit, fünf Alltags-Posen

def _raised_paw(tip_x=34.4, tip_y=12.8):
    """Pfote hoch neben dem Kopf (wie winkt)."""
    return (f'<path {F} d="M26 31 Q31 25 31.5 16 Q31.8 {tip_y - .3} {tip_x} {tip_y} Q37 13.3 36.6 16.4'
            f' Q35.8 26.5 29.5 34.5"/>')


# ------------------------------------------------------------ neue Wetterlagen
def nebel():
    """Nebel: sitzt hinter drei weißen Nebelschwaden, nur der Kopf schaut klar heraus."""
    def band(x0, x1, y):
        return f'<path {F} d="M{x0} {y} H{x1} Q{x1 + 3} {y} {x1 + 3} {y + 3} Q{x1 + 3} {y + 6} {x1} {y + 6} H{x0} Q{x0 - 3} {y + 6} {x0 - 3} {y + 3} Q{x0 - 3} {y} {x0} {y} Z"/>'
    return 50, 44, _sitting_body() + _head(20, 13) + band(6, 30, 23) + band(18, 44, 34.5)


def gewitter():
    """Gewitter: lugt mit großen Augen über die Linie, darüber dunkle Wolke mit gelbem Blitz."""
    cloud = (f'<path fill="currentColor" stroke="currentColor" d="M33 14 Q30 7 37 6 Q39 0 46 1.5 Q52 0 54 6'
             f' Q60 6.5 59.5 11 Q59 14 55 14 Z"/>'
             f'<path fill="{YELLOW}" stroke="currentColor" d="M45 12 L39.5 21 L44 21 L40.5 30 L51 18 L46 18 L49.5 12 Z"/>')
    eyes = f'<circle {D} cx="12.8" cy="16.6" r="2.4"/><circle {D} cx="21.2" cy="16.6" r="2.4"/>'
    paws = (f'<path {F} d="M5 30 Q5 24.5 9.5 24.5 Q14 24.5 14 30 Z"/>'
            f'<path {F} d="M20 30 Q20 24.5 24.5 24.5 Q29 24.5 29 30 Z"/>')
    return 61, 30, _head(17, 19, eyes="none") + f'<g transform="translate(0 2.4)">{eyes}</g>' + paws + cloud


# ------------------------------------------------------------ Anlässe zu vorhandenen Karten
def fernglas():
    """Regenradar-Karte: späht mit dem Fernglas (von vorn: zwei blaue Linsen) nach dem nächsten Schauer."""
    glass = (f'<path {L} d="M18.5 13.5 H21.5"/>'
             f'<circle fill="{BLUE}" stroke="currentColor" cx="14.5" cy="13.5" r="4.4"/>'
             f'<circle fill="{BLUE}" stroke="currentColor" cx="25.5" cy="13.5" r="4.4"/>')
    paws = (f'<path {F} d="M6.5 19 Q6.5 15.5 9.5 15.5 Q12.5 15.5 12.5 19 Q12.5 22 9.5 22 Q6.5 22 6.5 19 Z"/>'
            f'<path {F} d="M27.5 19 Q27.5 15.5 30.5 15.5 Q33.5 15.5 33.5 19 Q33.5 22 30.5 22 Q27.5 22 27.5 19 Z"/>')
    drops = f'<path stroke="{BLUE}" fill="none" d="M42 5 l-1 3 M47 11 l-1 3 M42 17 l-1 3"/>'
    return 50, 44, _sitting_body() + _head(20, 13, eyes="none") + glass + paws + drops


def helm():
    """Anfahrt mit dem Rad: blauer Fahrradhelm mit Lüftungsschlitzen."""
    helmet = (f'<path fill="{BLUE}" stroke="currentColor" d="M8.5 6.5 Q9 -4.5 20 -4.5 Q31 -4.5 31.5 6.5 Z"/>'
              f'<path fill="var(--bg)" stroke="none" d="M14 -1 L16 4.5 L18 4.5 L16.5 -2 Z M22 -2 L20.5 4.5 L22.5 4.5'
              f' L24.5 -1.2 Z"/>'
              f'<path {L} d="M10 7 Q11 14 15.5 17.5 M30 7 Q29 14 24.5 17.5"/>')
    return 40, 50, f'<g transform="translate(0 6)">{_sitting_body()}{_head(20, 13)}{helmet}</g>'


def haltestelle():
    """Anfahrt mit Bus und Bahn: wartet an der Haltestelle (gelbes Schild mit grünem H)."""
    sign = (f'<path {L} d="M48 18 V43.5"/>'
            f'<circle fill="{YELLOW}" stroke="{GREEN_INK}" cx="48" cy="11" r="8"/>'  # grüner Rand wie echt; schwarz gab rote Streupixel
            f'<path stroke="{GREEN_INK}" fill="none" d="M44.8 7 V15 M51.2 7 V15 M44.8 11 H51.2"/>')
    return 58, 44, _sitting_body() + _head(20, 13) + sign


def niest():
    """Pollenflug: niest kräftig, daneben eine gelbe Blume."""
    head = f'<g transform="rotate(-14 20 13)">{_head(20, 13, eyes="squint")}</g>'
    spray = f'<path {L} d="M6 16 L1 15 M6.5 19.5 L1.5 21 M8.5 22.5 L5 26"/>'
    petals = "".join(f'<circle cx="{47 + 6 * dx:.1f}" cy="{21 + 6 * dy:.1f}" r="3.2"/>'
                     for dx, dy in ((0, -1), (.95, -.31), (.59, .81), (-.59, .81), (-.95, -.31)))
    flower = (f'<path stroke="{GREEN_INK}" fill="none" d="M47 43.5 V28 M47 37 Q42 35 41 31"/>'
              f'<g fill="{YELLOW}" stroke="currentColor">{petals}</g>'
              f'<circle fill="{RED}" stroke="currentColor" cx="47" cy="21" r="2.8"/>')
    return 58, 44, _sitting_body() + head + spray + flower


def plakat():
    """Wahlkampftag: hält ein rotes Schild hoch."""
    sign = (f'<path {L} d="M34 40 V14"/>'
            f'<path fill="{RED}" stroke="currentColor" d="M25 1.5 H48 V16 H25 Z"/>'
            f'<path stroke="var(--bg)" fill="none" d="M29 6.5 H44 M29 11 H39"/>')
    paw = f'<path {F} d="M26 33 Q31 29 32 23 Q32.5 20 35 20.4 Q37.5 21 37 24 Q36 30 29.5 36"/>'
    return 50, 44, _sitting_body(paws=1) + _head(18, 13) + sign + paw


def karte():
    """Termin am Zielort: studiert eine Landkarte mit Fluss und rotem Ziel-Pin."""
    paper = (f'<path {F} d="M3 21 L13.5 19 L24 21 L37 19 L37 41 L24 43 L13.5 41 L3 43 Z"/>'
             f'<path {L} d="M13.5 19 V41 M24 21 V43"/>'
             f'<path stroke="{BLUE}" fill="none" d="M6 39 Q12 33 17 34 Q22 35 26 29 Q29 25 34 25"/>'
             f'<circle fill="{RED}" stroke="currentColor" cx="30" cy="31.5" r="2.6"/>')
    eyes = f'<circle {D} cx="16" cy="14" r="1.8"/><circle {D} cx="24" cy="14" r="1.8"/>'
    return 40, 44, _sitting_body() + _head(20, 12, eyes="none") + eyes + paper


def nachtmuetze():
    """Später Abend: blaue Zipfelmütze mit gelbem Bommel, Augen fallen zu."""
    cap = (f'<path fill="{BLUE}" stroke="currentColor" d="M9.5 5.5 Q11 -4 22 -4.5 Q31 -4.5 37 4 Q38.5 7 36.5 10'
           f' Q34 4 30.5 5.5 Z"/>'
           f'<path fill="var(--bg)" stroke="currentColor" d="M8.5 4.5 H31.5 V8.5 H8.5 Z"/>'
           f'<circle fill="{YELLOW}" stroke="currentColor" cx="37" cy="12.5" r="3"/>')
    return 42, 52, f'<g transform="translate(0 8)">{_sitting_body()}{_head(20, 13, eyes="closed")}{cap}</g>'


def haengematte():
    """Wochenende: liegt in einer roten Hängematte, Schwanz hängt raus."""
    posts = f'<path {L} d="M2 4 V34 M62 4 V34"/>'
    cat = f'<g transform="translate(10 -4)">{kastenbrot()[2]}</g>'
    hammock = (f'<path fill="{RED}" stroke="currentColor" d="M2 8 Q32 42 62 8 Q32 30 2 8 Z"/>'
               f'<path {L} d="M50 22 Q53 27 50 31"/>')
    return 64, 34, posts + cat + hammock


# ------------------------------------------------------------ Alltag
def laptop():
    """Sitzt am Laptop (blauer Deckel von hinten), Pfoten auf der Tastatur."""
    lid = (f'<path fill="{BLUE}" stroke="currentColor" d="M5 20 H35 L33 40 H7 Z"/>'
           f'<circle fill="var(--bg)" stroke="none" cx="20" cy="30" r="2.6"/>'
           f'<path fill="currentColor" stroke="currentColor" d="M2 40 H38 V43.5 H2 Z"/>')
    paws = (f'<path {F} d="M9 20.5 Q9 17 12.5 17 Q16 17 16 20.5"/>'
            f'<path {F} d="M24 20.5 Q24 17 27.5 17 Q31 17 31 20.5"/>')
    return 40, 44, _head(20, 11) + lid + paws


def kopfhoerer():
    """Hört Musik: Bügel über dem Kopf, rote Muscheln, zwei blaue Noten."""
    phones = (f'<path {L} d="M9 9 Q9 -2.5 20 -2.5 Q31 -2.5 31 9"/>'
              f'<path fill="{RED}" stroke="currentColor" d="M6 7 H11.5 V16 H6 Q4.5 16 4.5 14.5 V8.5 Q4.5 7 6 7 Z'
              f' M28.5 7 H34 Q35.5 7 35.5 8.5 V14.5 Q35.5 16 34 16 H28.5 Z"/>')

    def note(x, y):
        return (f'<ellipse fill="{BLUE}" stroke="currentColor" cx="{x}" cy="{y}" rx="2.5" ry="1.9"'
                f' transform="rotate(-20 {x} {y})"/><path {L} d="M{x + 2.2} {y - .6} V{y - 8.5}"/>')
    return 52, 48, (f'<g transform="translate(0 4)">{_sitting_body()}{_head(20, 13, eyes="closed")}{phones}'
                    f'{note(43, 14)}{note(47, 28)}</g>')


def ball():
    """Kunststück: balanciert einen rot-gelben Ball auf der Nase."""
    head = f'<g transform="rotate(-12 20 13)">{_head(20, 13)}</g>'
    ball_ = (f'<circle fill="{YELLOW}" stroke="currentColor" cx="17" cy="-5" r="6"/>'
             f'<path fill="{RED}" stroke="currentColor" d="M11.2 -6.5 Q17 -3 22.8 -6.5 Q23.4 -3 22 -1 Q17 2 12 -1'
             f' Q10.6 -3 11.2 -6.5 Z"/>')
    return 40, 56, f'<g transform="translate(0 12)">{_sitting_body()}{head}{ball_}</g>'


def flieger():
    """Schaut einem großen Papierflieger nach."""
    plane = (f'<g transform="rotate(-10 47 10)"><path {F} d="M34 9 L60 3 L45 17 Z"/>'
             f'<path {L} d="M60 3 L43 11.5 L45 17"/></g>')
    eyes = f'<circle {D} cx="22" cy="9.6" r="1.7"/><circle {D} cx="29" cy="11.2" r="1.7"/>'
    head = f'<g transform="rotate(18 20 13)">{_head(20, 13, eyes="none")}</g>' + eyes
    inner = _sitting_body() + head + plane
    return 62, 45.5, f'<g transform="translate(0 1.5)">{inner}</g>'


def seifenblasen():
    """Tatzt nach blauen Seifenblasen."""
    bubbles = (f'<g stroke="{BLUE}" fill="none"><circle cx="43" cy="8" r="5"/><circle cx="49" cy="20" r="3.4"/>'
               f'<circle cx="40" cy="25" r="2.6"/></g>'
               f'<path stroke="{BLUE}" fill="none" d="M40.5 5 Q41.5 4 43 4"/>')
    return 54, 44, _sitting_body(paws=1) + _head(18, 13) + _raised_paw() + bubbles


POSES = {
    "sitzt": sitzt, "putzt": putzt, "schmetterling": schmetterling, "schläft": schlaeft,
    "kastenbrot": kastenbrot, "lugt": lugt, "spielt": spielt, "streckt": streckt,
    "gähnt": gaehnt, "schwanzjagd": schwanzjagd, "rücken": ruecken,
    "sonnt": sonnt, "sturm": sturm, "schirm": schirm, "schal": schal,
    "maus": maus, "laser": laser, "karton": karton, "tasse": tasse, "spaziert": spaziert,
    "zeitung": zeitung, "koffer": koffer, "partyhut": partyhut, "socke": socke,
    # Ostereier (seit 1.24): nie zufällig, nur an ihrem Tag (ostereier.today)
    "narr": narr, "dirigent": dirigent, "schwarz": schwarz, "himbeerkuchen": himbeerkuchen,
    "kürbis": kuerbis, "grundgesetz": grundgesetz,
    # Ratssitzung (seit 1.27): nur über choose(occasions=["rat"]), nie zufällig
    "rednerpult": rednerpult, "akten": akten,
    # seit 1.34
    "südwester": suedwester, "fenster": fenster, "schneeflocke": schneeflocke, "schneemann": schneemann,
    "mütze": muetze, "decke": decke, "sonnenbrille": sonnenbrille, "eis": eis, "drachen": drachen,
    "blätter": blaetter, "winkt": winkt, "pflanze": pflanze, "fisch": fisch, "lichterkette": lichterkette,
    # seit 1.35
    "nebel": nebel, "gewitter": gewitter, "fernglas": fernglas, "helm": helm, "haltestelle": haltestelle,
    "niest": niest, "plakat": plakat, "karte": karte, "zipfelmütze": nachtmuetze, "hängematte": haengematte,
    "laptop": laptop, "kopfhörer": kopfhoerer, "ball": ball, "flieger": flieger, "seifenblasen": seifenblasen,
}
# Ostereier (seit 1.24): nur über choose(egg=…); geheim, darum auch nicht auf dem Posen-Bogen für die README
EGG_POSES = ("narr", "dirigent", "schwarz", "himbeerkuchen", "kürbis", "grundgesetz")
# Zufällige Posen (ohne die Wetter-Posen)
EVERYDAY = ["sitzt", "putzt", "schmetterling", "gähnt", "schläft", "kastenbrot", "lugt", "spielt", "streckt",
            "schwanzjagd", "rücken", "maus", "laser", "karton", "tasse", "spaziert",
            "winkt", "pflanze", "fisch",                               # seit 1.34
            "laptop", "kopfhörer", "ball", "flieger", "seifenblasen"]   # seit 1.35: 24
# Wetter (C): Anlass → Posen (seit 1.34 je drei, täglich gemischt und reihum wie die Alltags-Posen).
# Die erste ist die bisherige Pose. Reihenfolge der Schlüssel = Vorrang (siehe weather_reason).
WEATHER_POSES = {
    "sturm": ["sturm", "drachen", "blätter"],
    "gewitter": ["gewitter", "fenster"],           # seit 1.35 (vorher zählte Gewitter als Regen)
    "regen": ["schirm", "südwester", "fenster"],
    "nebel": ["nebel"],                             # seit 1.35
    "schnee": ["schal", "schneeflocke", "schneemann"],
    "frost": ["schal", "mütze", "decke"],
    "sonne": ["sonnt", "sonnenbrille", "eis"],
}
# Anlässe (seit 1.20): Anlass → Pose. Geburtstag geht dem Wetter vor, die übrigen kommen nach dem Wetter.
OCCASION_POSE = {"geburtstag": "partyhut", "nachrichten": "zeitung", "zug": "koffer", "waesche": "socke",
                 "advent": "lichterkette",  # seit 1.34: 1. Advent bis Heiligabend
                 # seit 1.35: zu vorhandenen Karten (Regenradar, Anfahrt Rad bzw. Bus/Bahn, Pollen-Kachel,
                 # Wahlkampf-Karte, Wetter am Zielort heute), spätabends und am Wochenende
                 "radar": "fernglas", "rad": "helm", "oepnv": "haltestelle", "pollen": "niest",
                 "wahlkampf": "plakat", "zielort": "karte", "abend": "zipfelmütze", "wochenende": "hängematte"}
# Seltene Anlässe (seit 1.35): nur auf jedem zweiten Anlass-Takt, also jedes vierte Mal – das Wochenende hat
# keine Karte, die es begrenzt, sonst läge die Katze das ganze Wochenende jedes zweite Mal in der Hängematte.
RARE_OCCASIONS = {"wochenende"}
LATE_HOUR = 22  # seit 1.35: ab hier Anlass „abend“ (Zipfelmütze), bis das Nachtbild um 23 Uhr übernimmt
# Ratssitzung (seit 1.27, Anlass „rat“ = die Livestream-Karte steht): Rednerpult, ab 21 Uhr schläft sie auf den Akten.
# Kommt wie die übrigen Anlässe nur auf jedem zweiten Takt, aber vor Osterei und Wetter (Leons Wahl).
RAT_POSE, RAT_LATE_POSE, RAT_LATE_HOUR = "rednerpult", "akten", 21
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
    """Warum die Katze sich anpasst: sturm, gewitter, schnee, regen, nebel, frost, sonne (Vorrang) – oder None."""
    r = _current_hour(records or [], now)
    if r is None:
        return None
    gust = r.get("wind_gust_speed") or 0
    if gust >= STORM_GUST:
        return "sturm"
    kind = {r.get("icon"), r.get("condition")}
    if "thunderstorm" in kind:  # seit 1.35 eigene Lage, vorher Regen
        return "gewitter"
    snowy = bool(kind & {"snow", "sleet"})
    wet = ((r.get("precipitation") or 0) >= RAIN_MM or bool(kind & {"rain", "hail"})
           or (nowcast or {}).get("state") == "jetzt")
    if snowy:
        return "schnee"
    if wet:
        return "regen"
    if "fog" in kind:  # seit 1.35
        return "nebel"
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


def weather_pose(reason, day, slot):
    """Pose zur Wetterlage: die Varianten des Tages gemischt und der Reihe nach – zwei aufeinanderfolgende
    Takte zeigen nie dieselbe (seit 1.34)."""
    order = _day_order(WEATHER_POSES[reason], day, f"wetter/{reason}")
    return order[slot % len(order)]


def occasion_slot(now):
    """Darf in diesem Takt ein Anlass die Pose bestimmen? Jeder zweite Takt – so sind die Anlass-Posen
    „eingestreut“ statt ständig da. Welcher Takt beginnt, wechselt täglich (Seed = Datum)."""
    start = random.Random(f"{now.date().isoformat()}/anlass").randrange(2)
    return (slot_of(now) + start) % 2 == 0


def choose(now, records=None, nowcast=None, weather=True, feels_like=None, occasions=(), egg=None):
    """Was die Katze diesmal tut und wo sie es zuerst versucht.

    occasions – aktive Anlässe aus OCCASION_POSE (geburtstag, nachrichten, zug, waesche, advent; seit 1.35 radar, rad,
                oepnv, pollen, wahlkampf, zielort, abend, wochenende) und „rat“
                (seit 1.27: Ratssitzung läuft, die Livestream-Karte steht)
    egg       – Pose eines Ostereis (seit 1.24, ostereier.today) oder None

    Rangfolge: Geburtstag > Ratssitzung > Osterei > Wetter > übrige Anlässe > Alltag. Anlässe (auch Geburtstag
    und Ratssitzung) zählen nur in jedem zweiten Takt (occasion_slot); Osterei und Wetter gelten immer, wenn sie
    zutreffen – an einem Ostereier-Tag mit Ratssitzung wechseln sich also Osterei und Rednerpult ab.

    main  – Pose, die sie am liebsten zeigt
    flat  – flache Pose für Linien mit wenig Platz darüber
    spots – Reihenfolge der Plätze (kopf, tag, mehr); das Skript im Template nimmt den ersten,
            an dem eine der beiden Posen frei steht
    seed  – Startpunkt für die Lage auf der Linie (wiederholbar)
    reason – was die Pose bestimmt hat (Wetter- oder Anlassname) oder None
    """
    slot = slot_of(now)
    day = now.date()
    everyday = _day_order(EVERYDAY, day, "pose")
    on_slot = occasion_slot(now)
    rare_ok = (slot // 2) % 2 == 0  # seit 1.35: seltene Anlässe nur auf jedem zweiten Anlass-Takt
    active = [o for o in OCCASION_POSE if o in set(occasions) and (rare_ok or o not in RARE_OCCASIONS)] if on_slot else []
    others = [o for o in active if o != "geburtstag"]
    council = on_slot and "rat" in set(occasions)
    weather_why = weather_reason(records, now, nowcast, feels_like) if weather else None
    if "geburtstag" in active:  # nur auf Anlass-Takten, an Ostereier-Tagen also im Wechsel mit dem Osterei
        reason, main = "geburtstag", OCCASION_POSE["geburtstag"]
    elif council:  # Ratssitzung (seit 1.27): vor Osterei und Wetter, spät schläft sie auf den Akten
        reason, main = "rat", RAT_LATE_POSE if now.hour >= RAT_LATE_HOUR else RAT_POSE
    elif egg:  # Ostereier (seit 1.24): an ihrem Tag in jedem Takt, vor dem Wetter
        reason, main = "osterei", egg
    elif weather_why:  # seit 1.34: Varianten reihum, Reihenfolge je Tag und Wetterlage gemischt
        reason, main = weather_why, weather_pose(weather_why, day, slot)
    elif others:  # mehrere zugleich (Zug-Dienstag im Nachrichtenfenster): abwechseln
        # Abwechseln auf den Anlass-Takten (slot // 2). Ist ein seltener Anlass dabei, ist slot // 2 hier immer
        # gerade – dann über slot // 4, sonst käme bei zwei Anlässen nur der erste dran (seit 1.35, Test).
        step = 4 if RARE_OCCASIONS & set(others) else 2
        reason = others[(slot // step) % len(others)]
        main = OCCASION_POSE[reason]
    else:
        reason, main = None, everyday[slot % len(everyday)]
    # Flache Ersatzpose: seit 1.34 zuerst eine flache Variante derselben Wetterlage (Decke, sonnt, Sturm),
    # damit das Wetter auch auf engen Linien sichtbar bleibt; sonst die nächste flache Alltags-Pose.
    same = [p for p in WEATHER_POSES.get(reason, []) if is_flat(p)]
    flat = main if is_flat(main) else same[0] if same else next(
        p for i in range(1, len(everyday) + 1) if is_flat(p := everyday[(slot + i) % len(everyday)]))
    spots = _day_order(SPOTS, day, "spot")
    k = slot % len(spots)
    spots = spots[k:] + spots[:k]
    if reason and not is_flat(main):  # Schirm, Schal, Partyhut, Zeitung, Koffer, Pult, Akten brauchen Höhe: zuerst die Kopfzeile
        spots.remove("kopf")
        spots.insert(0, "kopf")
    seed = random.Random(f"{day.isoformat()}/{slot}").randrange(1000)
    return {"main": pose(main), "flat": pose(flat), "spots": spots, "seed": seed, "reason": reason}
