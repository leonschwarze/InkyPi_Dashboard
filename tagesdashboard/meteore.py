"""
Sternschnuppenströme im Nachtbild (seit 1.17, Variante C).

Im Nachtbild steht immer eine Textzeile, wenn in der kommenden Nacht einer der elf bekannten
Meteorströme aktiv ist ("Sternschnuppen: Perseiden aktiv · Maximum 12./13.8."). Nur bei den drei
kräftigsten Strömen (Quadrantiden, Perseiden, Geminiden) und nur in der Maximumnacht bei klarem
Himmel (Bewölkung < 30 %, dieselbe Schwelle wie bei "sternklar" in nachtgrafik.describe) zeichnet
nachtgrafik.svg() zusätzlich ein paar Sternschnuppen über den Himmel.

Daten: Aktivitätsfenster, Maximum und ZHR (Zenitale Stundenrate) nach der International Meteor
Organization, als feste Kalenderwerte wie beim Sonnenwende-Countdown in nachtgrafik.daylight –
keine tagesgenaue Berechnung für ein bestimmtes Jahr, das Maximum kann real um einen Tag abweichen.
Sind zwei Ströme gleichzeitig aktiv (z. B. Perseiden und Südliche Delta-Aquariiden im Hochsommer),
gewinnt der mit dem näheren Maximum.
"""

from datetime import date, timedelta

# (Name, Beginn, Ende, Maximum) je als (Monat, Tag); ZHR nach IMO; stark = Perseiden/Geminiden/
# Quadrantiden (einzige, bei denen zusätzlich SVG-Sternschnuppen gezeichnet werden).
SHOWERS = [
    ("Quadrantiden",              (12, 28), (1, 12),  (1, 3),   120, True),
    ("Lyriden",                   (4, 16),  (4, 25),  (4, 22),  18,  False),
    ("Eta-Aquariiden",            (4, 19),  (5, 28),  (5, 5),   50,  False),
    ("Südliche Delta-Aquariiden", (7, 12),  (8, 23),  (7, 30),  25,  False),
    ("Perseiden",                 (7, 17),  (8, 24),  (8, 12),  100, True),
    ("Draconiden",                (10, 6),  (10, 10), (10, 8),  10,  False),
    ("Orioniden",                 (10, 2),  (11, 7),  (10, 21), 20,  False),
    ("Tauriden",                  (9, 10),  (12, 10), (11, 5),  5,   False),
    ("Leoniden",                  (11, 6),  (11, 30), (11, 17), 15,  False),
    ("Geminiden",                 (12, 4),  (12, 17), (12, 14), 150, True),
    ("Ursiden",                   (12, 17), (12, 26), (12, 22), 10,  False),
]


def _in_window(d, start, end):
    """Monat/Tag-Fenster, auch über den Jahreswechsel (z. B. Quadrantiden 28.12.–12.1.)."""
    md = (d.month, d.day)
    if start <= end:
        return start <= md <= end
    return md >= start or md <= end


def _peak_distance(d, month, day):
    """Abstand in Tagen zum nächstgelegenen Kalenderjahr-Maximum (davor oder danach)."""
    best = None
    for year in (d.year - 1, d.year, d.year + 1):
        gap = abs((date(year, month, day) - d).days)
        best = gap if best is None else min(best, gap)
    return best


def _at_peak(d, month, day):
    """Die Maximumnacht selbst und die Folgenacht ("Maximum 12./13.8."), nicht die Nacht davor."""
    for year in (d.year - 1, d.year, d.year + 1):
        p = date(year, month, day)
        if d in (p, p + timedelta(days=1)):
            return True
    return False


def _peak_label(month, day):
    """„12./13.8.“ – die Nacht beginnt am Maximumstag und endet am Folgetag."""
    d1 = date(2023, month, day)  # Jahr beliebig, nur für die +1-Tag-Rechnung
    d2 = d1 + timedelta(days=1)
    if d2.month == d1.month:
        return f"{d1.day}./{d2.day}.{d1.month}."
    return f"{d1.day}.{d1.month}./{d2.day}.{d2.month}."


def active(d):
    """Für den Abend d (wie in special_view: vor 12 Uhr heute, sonst morgen) der aktive Strom mit
    dem nächsten Maximum, sonst None. Felder: name, zhr, stark, at_peak, text (immer anzuzeigen)."""
    matches = [s for s in SHOWERS if _in_window(d, s[1], s[2])]
    if not matches:
        return None
    name, start, end, peak, zhr, stark = min(matches, key=lambda s: _peak_distance(d, *s[3]))
    at_peak = _at_peak(d, *peak)
    if at_peak:
        text = f"Sternschnuppen: {name}-Maximum heute Nacht · ZHR {zhr}"
    else:
        text = f"Sternschnuppen: {name} aktiv · Maximum {_peak_label(*peak)}"
    return {"name": name, "zhr": zhr, "stark": stark, "at_peak": at_peak, "text": text}


def show_streaks(info, wx):
    """Nur bei starken Strömen (Quadrantiden/Perseiden/Geminiden) in der Maximumnacht und bei
    klarem, trockenem Himmel (wie "sternklar": Bewölkung < 30 %) zeichnet nachtgrafik.svg() SVG-
    Sternschnuppen; sonst bleibt das Nachtbild bis auf die Textzeile unverändert."""
    if not info or not info["stark"] or not info["at_peak"] or not wx:
        return False
    if wx.get("wet") or wx.get("fog"):
        return False
    return (wx.get("cloud") or 0) < 30
