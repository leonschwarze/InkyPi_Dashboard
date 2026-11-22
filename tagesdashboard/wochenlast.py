"""
Wie voll ist die Woche? (seit 1.38, Wochenvorschau)

Zählt die Stunden mit Terminen der kommenden Woche und vergleicht sie mit dem Schnitt der vergangenen
Wochen: „19 h Termine · deutlich mehr als sonst (Ø 12 h)“.

Was zählt
---------
* Termine mit Uhrzeit. Ganztägige (Müll, Geburtstag, Urlaub) zählen nicht – sie sagen nichts über
  die Zeit, die ein Tag kostet.
* Je Tag nur die Zeit zwischen DAY_FROM und DAY_TO (7–23 Uhr): Ein Nachtzug von 22:15 bis 7:30 zählt
  45 Minuten, nicht neun Stunden.
* Überschneidungen nur einmal: Zwei Termine zugleich sind eine Stunde, nicht zwei.
* Abgelehnte Einladungen fehlen schon in der Terminliste (seit 1.26).

„Sonst“
-------
Mittelwert der HISTORY_WEEKS (8) vollen Wochen vor der laufenden. Wochen mit weniger als MIN_WEEK_H
(2 h) – Urlaub, Kalender leer – zählen nicht mit, sonst drückt ein Urlaub den Schnitt. Gibt es weniger
als MIN_WEEKS (3) gültige Wochen, steht nur die Zahl da, ohne Vergleich.

Die vergangenen Wochen kommen mit einer eigenen Kalenderabfrage (load_calendar(history=True) in
tagesdashboard.py), einmal am Tag zwischengespeichert – die Wochenvorschau läuft sonntags fünf Stunden lang.

Anzeige (Leons Wahl „C“): eine Zeile über der Pi-Zeile, „Woche: 21 h Termine · deutlich mehr als sonst
(Ø 11 h) · vollster Tag Di (9 h)“; „deutlich mehr“ in Rot. Ohne Kalender keine Zeile.
"""

from datetime import datetime, time, timedelta

DAY_FROM, DAY_TO = time(7, 0), time(23, 0)
KURZ = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
HISTORY_WEEKS = 8
MIN_WEEK_H = 2.0
MIN_WEEKS = 3
# Verhältnis zum Schnitt → Wort (von oben nach unten geprüft)
WORDS = ((1.3, "deutlich mehr als sonst"), (1.1, "mehr als sonst"), (0.9, "wie sonst"),
         (0.7, "ruhiger als sonst"), (0.0, "deutlich ruhiger als sonst"))


def day_hours(events, d, tz):
    """Stunden mit Terminen am Tag d (7–23 Uhr, Überschneidungen einmal)."""
    lo = datetime.combine(d, DAY_FROM, tz)
    hi = datetime.combine(d, DAY_TO, tz)
    spans = []
    for ev in events:
        if ev.get("all_day"):
            continue
        s, e = max(ev["start"], lo), min(ev["end"], hi)
        if e > s:
            spans.append((s, e))
    spans.sort()
    total, cur_s, cur_e = 0.0, None, None
    for s, e in spans:
        if cur_e is None or s > cur_e:
            if cur_e is not None:
                total += (cur_e - cur_s).total_seconds()
            cur_s, cur_e = s, e
        else:
            cur_e = max(cur_e, e)
    if cur_e is not None:
        total += (cur_e - cur_s).total_seconds()
    return total / 3600


def week_hours(events, monday, tz):
    """[Stunden Mo … So] der Woche ab monday."""
    return [day_hours(events, monday + timedelta(days=i), tz) for i in range(7)]


def average(events, this_monday, tz, weeks=HISTORY_WEEKS):
    """Schnitt der vollen Wochen vor this_monday oder None (zu wenige gültige Wochen)."""
    totals = []
    for back in range(1, weeks + 1):
        h = sum(week_hours(events, this_monday - timedelta(days=7 * back), tz))
        if h >= MIN_WEEK_H:
            totals.append(h)
    return sum(totals) / len(totals) if len(totals) >= MIN_WEEKS else None


def fmt_h(h):
    """„19 h“, unter 10 h mit halben Stunden: „4,5 h“."""
    r = round(h * 2) / 2 if h < 10 else round(h)
    return (f"{r:.1f}".replace(".", ",").replace(",0", "") if r < 10 else f"{r:.0f}") + " h"


def compare(total, avg):
    if not avg:
        return None
    ratio = round(total / avg, 3)  # 13,2 / 12 ist sonst 1,0999… statt 1,1
    return next(word for limit, word in WORDS if ratio >= limit)


def summary(days, avg):
    """Ergebnis für die Wochenvorschau.

    days: [Stunden Mo … So] der kommenden Woche. Gibt total, avg, word, peak (vollster Tag) und
    die Texte zurück.
    """
    total = sum(days)
    word = compare(total, avg)
    peak = max(range(7), key=lambda i: days[i])
    return {
        "total": total, "avg": avg, "word": word, "days": days,
        "total_text": fmt_h(total) + " Termine",
        "avg_text": f"Ø {fmt_h(avg)}" if avg else "",
        "peak_text": f"vollster Tag {KURZ[peak]} ({fmt_h(days[peak])})" if days[peak] >= 1 else "",
        "level": "hoch" if word and word.startswith("deutlich mehr") else "ruhig" if word and "ruhiger" in word else "",
    }
