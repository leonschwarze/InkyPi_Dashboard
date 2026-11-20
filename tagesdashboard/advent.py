"""
Adventskranz im Kopf des Dashboards (seit 1.29).

In der Adventszeit (1. Advent bis Heiligabend) steht neben dem Datum ein kleiner Kranz mit vier
Kerzen; mit jedem Adventssonntag brennt eine mehr (von links). Er erscheint in der normalen Ansicht
und im Kopf der Wochenvorschau. Die Katze ist davon unabhängig: keine eigene Pose, sie weicht dem
Kranz nur aus (er ist für placeCat ein Hindernis wie jedes SVG).

  sundays(year)    die vier Adventssonntage eines Jahres
  candles(d)       wie viele Kerzen am Tag d brennen (0 = kein Kranz)
  wreath(lit)      SVG des Kranzes
  boundaries(now)  Tageswechsel, an denen sich der Kranz ändert (für den Bild-Cache)
"""

from datetime import date, datetime, time, timedelta

# Farben über CSS-Variablen (Standard: Displayfarben), damit der Schwarz-Weiß-Modus sie ersetzen kann;
# Konturen in der Textfarbe wie bei der Katze.
RED, YELLOW, GREEN = "var(--adv-red, #E3001B)", "var(--adv-yellow, #FFE500)", "var(--adv-green, #2E9E3F)"
INK = "currentColor"


def sundays(year):
    """Die vier Adventssonntage: Der 4. Advent ist der letzte Sonntag vor dem 25.12.

    Fällt der 25.12. selbst auf einen Sonntag, ist der 4. Advent der 18.12.; fällt der 24.12. auf einen
    Sonntag, sind 4. Advent und Heiligabend derselbe Tag.
    """
    xmas = date(year, 12, 25)
    back = (xmas.weekday() + 1) % 7 or 7  # weekday(): Montag = 0 … Sonntag = 6
    fourth = xmas - timedelta(days=back)
    return [fourth - timedelta(weeks=3 - i) for i in range(4)]


def candles(d):
    """Zahl der brennenden Kerzen am Tag d: vom 1. Advent bis Heiligabend 1–4, sonst 0."""
    first = sundays(d.year)
    if d < first[0] or d > date(d.year, 12, 24):
        return 0
    return sum(1 for s in first if s <= d)


def boundaries(now, days=2):
    """Mitternacht der nächsten Tage, falls sich dort der Kranz ändert (für den Bild-Cache außerhalb des Zugfensters)."""
    out = []
    for i in range(1, days + 1):
        d = now.date() + timedelta(days=i)
        if candles(d) != candles(d - timedelta(days=1)):
            out.append(datetime.combine(d, time(0), tzinfo=now.tzinfo))
    return out


# ----------------------------------------------------------------------
# Zeichnung: viewBox 40×36, steht mit der Unterkante auf der Kopflinie.
# In Displaygröße (800×480) ist der Kranz 34 × 31 px, eine Kerze 6 px breit.
# ----------------------------------------------------------------------
def _flame(cx, top):
    """Gelbe Flamme mit Kontur, Spitze bei top (10 hoch, 8 breit).

    Die Spitze ist abgerundet: An einer feinen Spitze treffen Gelb, Schwarz und Weiß in einem Pixel
    zusammen, und eink.py (erklärt nur Mischungen aus zwei Farben) macht daraus grüne/blaue Streupixel.
    """
    return (f'<path d="M{cx - 1.1:.1f},{top + 1.4:.1f} Q{cx},{top - 0.6:.1f} {cx + 1.1:.1f},{top + 1.4:.1f} '
            f'C{cx + 4.6:.1f},{top + 5.6:.1f} {cx + 3.9:.1f},{top + 10} {cx},{top + 10} '
            f'C{cx - 3.9:.1f},{top + 10} {cx - 4.6:.1f},{top + 5.6:.1f} {cx - 1.1:.1f},{top + 1.4:.1f} Z" '
            f'fill="{YELLOW}" stroke="{INK}" stroke-width="1.5" stroke-linejoin="round"/>')


def _candle(cx, top, bottom, lit, w=6.6):
    out = [f'<rect x="{cx - w / 2:.1f}" y="{top}" width="{w}" height="{bottom - top}" '
           f'fill="{RED}" stroke="{INK}" stroke-width="1.6"/>']
    if lit:
        out.append(_flame(cx, top - 11))
    else:  # Docht
        out.append(f'<line x1="{cx}" y1="{top}" x2="{cx}" y2="{top - 3}" stroke="{INK}" stroke-width="1.8"/>')
    return "".join(out)


def wreath(lit, cls="adv-ic"):
    """Kranz von vorn mit vier Kerzen; die ersten lit Kerzen (von links) brennen."""
    o = [f'<svg class="{cls}" viewBox="0 0 40 36" aria-hidden="true">']
    xs, tops = [5.8, 15.3, 24.7, 34.2], [16, 14, 14, 16]  # die inneren stehen hinten, also höher
    for i in (1, 2, 0, 3):  # hintere zuerst
        o.append(_candle(xs[i], tops[i], 28, i < lit))
    # Kranz: grüner Wulst mit Kontur und zwei roten Beeren
    o.append(f'<rect x="1" y="26" width="38" height="9" rx="4.5" fill="{GREEN}" stroke="{INK}" stroke-width="1.6"/>')
    for x in (12, 28):
        o.append(f'<circle cx="{x}" cy="30.5" r="2.3" fill="{RED}" stroke="{INK}" stroke-width="1.2"/>')
    o.append("</svg>")
    return "".join(o)
