"""
Helle Planeten im Nachtbild (seit 1.19, Variante C).

Wie bei den Sternschnuppenströmen (meteore.py) und den Mondfinsternissen (finsternisse.py) steht im
Nachtbild eine Textzeile, wenn einer der vier mit bloßem Auge auffälligen Planeten – Venus, Jupiter,
Mars, Saturn – gerade bemerkenswert ist:
  * Venus als Morgen- oder Abendstern, mit der größten Helligkeit als Höhepunkt.
  * Jupiter, Mars und Saturn (äußere Planeten) rund um ihre Opposition – dann stehen sie die ganze
    Nacht am Himmel, nicht nur morgens oder abends; anders als Venus sind sie nie "Morgen-" oder
    "Abendstern" im eigentlichen Sinn.
Nur am Höhepunkt selbst (Opposition bzw. größte Helligkeit) und bei klarem Himmel zeichnet
nachtgrafik.svg() zusätzlich einen auffällig hellen Punkt an den Himmel – wie die SVG-Sternschnuppen
nur in der Maximumnacht. Vor dem Höhepunkt zählt ein Vorlauf von LEAD_DAYS (kürzer als bei den
Mondfinsternissen, weil Oppositionen deutlich häufiger vorkommen); danach – wie bei den
Mondfinsternissen – keine Anzeige mehr, auch wenn der Planet noch länger sichtbar bleibt. Das hält
die Zeile auf echte Höhepunkte beschränkt, sonst wäre praktisch immer irgendein Planet "sichtbar"
und die Zeile würde ihren Ausnahme-Charakter verlieren.

Daten: von Hand recherchierte Fenster und Höhepunkte (u. a. sterngucker.de, earthsky.org,
spektrum.de, telescopeschool.com, starwalk.space), Stand November 2026. Wie die Mondfinsternisse
keine jahresperiodische Formel – die Umlaufzeiten von Venus (~584 Tage), Mars (~780 Tage), Jupiter
(~399 Tage) und Saturn (~378 Tage) passen nicht ins Kalenderjahr –, sondern konkrete, nicht
erneuerbare Fenster, die nach ihrem Ende aufgefrischt werden müssen (siehe „Offene Ideen" in
CLAUDE.md).
"""

from datetime import date, timedelta

LEAD_DAYS = 14  # Vorlauf vor dem Höhepunkt (kürzer als bei Finsternissen: Oppositionen sind häufiger)

# Name, Fensterbeginn (erste sinnvolle Sichtbarkeit), Fensterende (nächste Konjunktion bzw. Ende der
# auffälligen Helligkeit), Höhepunkt (Opposition bzw. größte Helligkeit), Helligkeit in mag,
# fester Morgen-/Abendstern-Begriff (None bei den äußeren Planeten, die nie "Morgen-"/"Abendstern" sind)
PLANETS = [
    ("Venus",   date(2026, 11, 1),  date(2027, 6, 15), date(2026, 11, 25), "-4,9", "Morgenstern"),
    ("Jupiter", date(2026, 8, 20),  date(2027, 4, 28), date(2027, 2, 11),  "-2,9", None),
    ("Saturn",  date(2026, 4, 15),  date(2027, 4, 7),  date(2026, 10, 4),  "0,3",  None),
    ("Mars",    date(2026, 10, 14), date(2027, 7, 1),  date(2027, 2, 19),  "-1,2", None),
]


def _at_peak(d, peak):
    """Wie bei Sternschnuppen und Mondfinsternissen: der Höhepunkttag selbst und die Folgenacht."""
    return d in (peak, peak + timedelta(days=1))


def active(d):
    """Für den Abend d (wie in special_view: vor 12 Uhr heute, sonst morgen) der Planet mit dem
    nächsten, noch nicht vergangenen Höhepunkt, sonst None. Felder: name, kind ("Morgenstern",
    "Abendstern" oder "Opposition"), mag, at_peak, text (immer anzuzeigen)."""
    candidates = []
    for name, start, end, peak, mag, fixed_kind in PLANETS:
        if d < start or d > end:
            continue  # außerhalb des recherchierten Fensters (siehe Docstring, "aufgefrischt werden")
        if d > peak + timedelta(days=1):
            continue  # Höhepunkt schon vorbei – keine Anzeige mehr (wie bei den Mondfinsternissen)
        at_peak = _at_peak(d, peak)
        gap = 0 if at_peak else (peak - d).days
        if not at_peak and gap > LEAD_DAYS:
            continue
        candidates.append((gap, name, peak, mag, fixed_kind, at_peak))
    if not candidates:
        return None
    gap, name, peak, mag, fixed_kind, at_peak = min(candidates, key=lambda c: c[0])
    kind = fixed_kind or "Opposition"
    if fixed_kind:
        if at_peak:
            text = f"Planeten: Venus heute Nacht am hellsten · {kind} ({mag} mag)"
        else:
            text = (f"Planeten: Venus {kind} · größte Helligkeit in {gap} "
                    f"Tag{'en' if gap != 1 else ''} ({mag} mag)")
    else:
        if at_peak:
            text = f"Planeten: {name} heute Nacht in Opposition · die ganze Nacht sichtbar ({mag} mag)"
        else:
            text = f"Planeten: {name} in {gap} Tag{'en' if gap != 1 else ''} in Opposition ({mag} mag)"
    return {"name": name, "kind": kind, "mag": mag, "at_peak": at_peak, "text": text}


def show_dot(info, wx):
    """Nur am Höhepunkt selbst und bei klarem Himmel (wie bei den starken Sternschnuppenströmen)
    zeichnet nachtgrafik.svg() einen auffällig hellen Punkt; sonst bleibt das Nachtbild bis auf die
    Textzeile unverändert."""
    if not info or not info["at_peak"] or not wx:
        return False
    if wx.get("wet") or wx.get("fog"):
        return False
    return (wx.get("cloud") or 0) < 30
