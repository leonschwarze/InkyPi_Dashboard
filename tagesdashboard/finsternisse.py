"""
Mondfinsternisse im Nachtbild (seit 1.18, Variante C wie bei den Sternschnuppenströmen).

Im Nachtbild steht eine Textzeile, wenn eine der hier hinterlegten Mondfinsternisse höchstens
LEAD_DAYS Tage entfernt ist ("Mondfinsternis in 45 Tagen (21.2.): Halbschattenfinsternis · ...").
Nur bei einer **totalen** Mondfinsternis und nur in der Nacht selbst färbt nachtgrafik.svg() den
Mond rötlich (Blutmond) – unabhängig von der Bewölkung, die ohnehin schon entscheidet, ob der Mond
überhaupt gezeichnet wird.

Anders als die Meteorströme sind Finsternisse keine jährlich wiederkehrenden Ereignisse, sondern
konkrete Kalendertermine. ECLIPSES ist deshalb keine Formel, sondern eine von Hand recherchierte,
endliche Liste (mehrere deutsche Astronomie-Portale, u. a. sterngucker.de, Stand November 2026).
Sie braucht von Zeit zu Zeit eine Auffrischung, siehe „Offene Ideen“ in CLAUDE.md.

Sonnenfinsternisse bleiben bewusst außen vor: Sie finden tagsüber statt und passen nicht zum
Nachtbild (23–6 Uhr); eine Ankündigung dafür wäre ein eigenes Feature an anderer Stelle.
"""

from datetime import date, timedelta

LEAD_DAYS = 45  # wie beim Sonnenwende-Countdown in nachtgrafik.daylight

# (Datum, Art, stark = Blutmond/totale Verfinsterung, Uhrzeit- und Sichtbarkeits-Hinweis für Bonn)
ECLIPSES = [
    (date(2027, 2, 21), "Halbschattenfinsternis", False, "0:13 Uhr, kaum wahrnehmbar"),
    (date(2028, 12, 31), "totale Mondfinsternis", True, "ab 16:53 Uhr, ab kurz nach Mondaufgang sichtbar"),
    (date(2029, 6, 26), "totale Mondfinsternis", True, "ab 3:23 Uhr, Mond geht während der Totalität unter"),
    (date(2029, 12, 20), "totale Mondfinsternis", True, "ab 22:43 Uhr, komplett sichtbar"),
    (date(2030, 6, 15), "partielle Mondfinsternis", False, "ab 18:34 Uhr, Mond etwa halb verdeckt"),
]


def _at_peak(d, ev_date):
    """Die Nacht des Ereignisses selbst, auf beide Arten gelesen – wie meteore._at_peak: Je
    nachdem, ob der Zielabend d vor oder nach Mitternacht berechnet wurde (special_view: vor
    12 Uhr heute, sonst morgen), trägt dieselbe physische Nacht das Datum des Ereignisses oder
    das des Folgetages."""
    return d in (ev_date, ev_date + timedelta(days=1))


def next_eclipse(d):
    """Für den Abend d die nächste bevorstehende oder aktuelle Mondfinsternis, wenn sie höchstens
    LEAD_DAYS Tage entfernt ist, sonst None. Felder: date, kind, stark, at_peak, text (immer
    anzuzeigen, sobald nicht None)."""
    for ev_date, kind, stark, info in ECLIPSES:
        if d > ev_date + timedelta(days=1):
            continue  # schon vorbei, nächste Tabellenzeile prüfen
        at_peak = _at_peak(d, ev_date)
        gap = 0 if at_peak else (ev_date - d).days
        if not at_peak and gap > LEAD_DAYS:
            return None  # nächster Termin gefunden, aber noch zu weit weg
        if at_peak:
            text = f"Mondfinsternis heute Nacht: {kind} · {info}"
        else:
            text = f"Mondfinsternis in {gap} Tag{'en' if gap != 1 else ''} ({ev_date.day}.{ev_date.month}.): {kind} · {info}"
        return {"date": ev_date, "kind": kind, "stark": stark, "at_peak": at_peak, "text": text}
    return None


def show_blood_moon(info):
    """Nur bei einer totalen Mondfinsternis in der Nacht selbst färbt nachtgrafik.svg() den Mond
    rötlich; sonst bleibt das Nachtbild bis auf die Textzeile unverändert."""
    return bool(info and info["stark"] and info["at_peak"])
