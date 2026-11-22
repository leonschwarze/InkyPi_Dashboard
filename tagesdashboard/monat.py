"""
Monatsbild (seit 1.38, Leons Wahl „C Raster + Liste“): am Monatsersten der ganze Monat auf einen Blick.

Links der Monat als Kalenderraster Mo–So: je Tag ein farbiger Punkt pro Termin (Kalenderfarbe, höchstens
fünf, dann „+“), mehrtägige ganztägige Termine als schmales Band, Feiertage (NRW) und Wochenenden mit
rotem Datum, Geburtstage als Törtchen, heute schwarz hinterlegt. Rechts eine Liste nach Datum:
Feiertage, Mehrtägiges, Geburtstage (mit Alter, wenn das Geburtsjahr bekannt ist). Im Kopf: Zahl der
Termine, freie Abende (wie in der Wochenvorschau), Feiertage.

Wann: am 1. eines Monats im Fenster monthFrom–monthTo (Standard 6–10 Uhr). Nachtbild und Festbild
haben Vorrang; fällt der Erste auf einen Sonntag, kommt abends wie gewohnt die Wochenvorschau.

Feiertage NRW: Neujahr, Karfreitag, Ostermontag, 1. Mai, Christi Himmelfahrt, Pfingstmontag,
Fronleichnam, Tag der Deutschen Einheit, Allerheiligen, 1. und 2. Weihnachtstag. Ostern aus
ostereier.easter.
"""

import calendar as pycal
from datetime import date, datetime, time, timedelta

try:
    from .ostereier import easter
    from .festtage import birthdays_on
except ImportError:  # Tests ohne Paket
    from ostereier import easter
    from festtage import birthdays_on

MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober",
          "November", "Dezember"]
KURZ = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


def holidays(year):
    """Gesetzliche Feiertage in NRW: {date: Name}."""
    e = easter(year)
    return {
        date(year, 1, 1): "Neujahr",
        e - timedelta(days=2): "Karfreitag",
        e + timedelta(days=1): "Ostermontag",
        date(year, 5, 1): "Tag der Arbeit",
        e + timedelta(days=39): "Himmelfahrt",
        e + timedelta(days=50): "Pfingstmontag",
        e + timedelta(days=60): "Fronleichnam",
        date(year, 10, 3): "Tag der Einheit",
        date(year, 11, 1): "Allerheiligen",
        date(year, 12, 25): "1. Weihnachtstag",
        date(year, 12, 26): "2. Weihnachtstag",
    }


LIST_MAX = {"landscape": 10, "portrait": 8}


def days_needed(today):
    """So viele Tage ab heute muss der Kalender liefern, damit das Raster bis zum letzten Tag reicht."""
    last = date(today.year, today.month, pycal.monthrange(today.year, today.month)[1])
    return (last - today).days + 1


def boundaries(now, start, end):
    """Beginn und Ende des Monatsbilds am nächsten Ersten (für den Bild-Cache)."""
    out = []
    for offset in (0, 1):
        d = now.date() + timedelta(days=offset)
        if d.day == 1:
            out.append(datetime.combine(d, start, tzinfo=now.tzinfo))
            e = d + timedelta(days=1) if start > end else d
            out.append(datetime.combine(e, end, tzinfo=now.tzinfo))
    return out


def grid(year, month, events, tz, birthdays=(), free_evening=None, today=None):
    """Raster des Monats.

    events: Rohtermine (start, end, all_day, title, color, fg) – abgelehnte sind schon weg.
    free_evening(items, d) → bool, oder None (keine Aussage über Abende).
    Gibt {"title", "head", "weeks": [{"kw", "days": [...]}], "summary", "entries", "free_days"} zurück.
    """
    hol = holidays(year)
    first = date(year, month, 1)
    last = date(year, month, pycal.monthrange(year, month)[1])
    weeks = pycal.Calendar(firstweekday=0).monthdatescalendar(year, month)

    def on_day(d):
        lo, hi = datetime.combine(d, time.min, tz), datetime.combine(d + timedelta(days=1), time.min, tz)
        return [ev for ev in events if ev["start"] < hi and (ev["end"] > lo or ev["start"] >= lo)]

    multi = [ev for ev in events if ev.get("all_day") and (ev["end"].date() - ev["start"].date()).days > 1]
    n_events, free_days, out_weeks = 0, [], []
    cells = {}
    for wk in weeks:
        days = []
        for d in wk:
            inside = d.month == month
            evs = on_day(d) if inside else []
            timed = sorted((e for e in evs if not e.get("all_day")), key=lambda e: e["start"])
            single = [e for e in evs if e.get("all_day") and e not in multi]
            bdays = birthdays_on(d, birthdays) if inside else []
            free = None
            if inside and free_evening is not None:
                items = [{"source": e} for e in evs]
                free = free_evening(items, d)
                if free:
                    free_days.append(d)
            n_events += len([e for e in timed if e["start"].date() == d]) + len(single)
            cell = {
                "num": d.day, "date": d, "inside": inside, "weekend": d.weekday() >= 5,
                "today": d == today, "past": bool(today and d < today),
                "holiday": hol.get(d) if inside else None,
                # Punkte: ganztägige eintägige zuerst, dann nach Beginn (Farbe des Kalenders)
                "dots": [e["color"] for e in single] + [e["color"] for e in timed],
                "bdays": bdays,
                "free": free,
                "band": None,
            }
            cells[d] = cell
            days.append(cell)
        out_weeks.append({"kw": wk[0].isocalendar()[1], "days": days})

    # Mehrtägige als schmale Bänder im Raster (Anfang/Ende abgerundet), höchstens zwei übereinander
    for ev in sorted(multi, key=lambda e: e["start"])[:2]:
        s = max(ev["start"].date(), first)
        e = min((ev["end"] - timedelta(seconds=1)).date(), last)
        d = s
        while d <= e:
            c = cells.get(d)
            if c:
                c["band"] = c["band"] or []
                c["band"].append({"color": ev["color"], "start": d == ev["start"].date(),
                                  "end": d == (ev["end"] - timedelta(seconds=1)).date()})
            d += timedelta(days=1)

    hol_in = [(d, n) for d, n in sorted(hol.items()) if d.month == month]
    bday_in = [(d, b) for d in (first + timedelta(days=i) for i in range((last - first).days + 1))
               for b in birthdays_on(d, birthdays)]
    summary = [f"{n_events} Termine" if n_events != 1 else "1 Termin"]
    if free_evening is not None:
        summary.append(f"{len(free_days)} freie Abende" if len(free_days) != 1 else "1 freier Abend")
    if hol_in:
        summary.append(("Feiertage " if len(hol_in) > 1 else "Feiertag ") + ", ".join(f"{d.day}." for d, _ in hol_in))

    # Liste rechts, nach Datum: Feiertage, Mehrtägiges (alle, nicht nur die gezeichneten Bänder), Geburtstage
    items = [(d, 0, {"kind": "hol", "day": f"{d.day}.{d.month}.", "text": n}) for d, n in hol_in]
    for ev in sorted(multi, key=lambda e: e["start"]):
        s_, e_ = max(ev["start"].date(), first), min((ev["end"] - timedelta(seconds=1)).date(), last)
        if e_ < s_:
            continue
        span = f"{s_.day}.–{e_.day}.{e_.month}." if s_ != e_ else f"{s_.day}.{s_.month}."
        items.append((s_, 1, {"kind": "multi", "day": span, "text": ev["title"], "color": ev["color"]}))
    for d, b in bday_in:
        items.append((d, 2, {"kind": "bday", "day": f"{d.day}.{d.month}.",
                             "text": b["name"] + (f" ({b['age']})" if b["age"] else "")}))
    items.sort(key=lambda x: (x[0], x[1]))
    return {
        "title": f"{MONATE[month - 1]} {year}",
        "head": KURZ,
        "weeks": out_weeks,
        "summary": summary,
        "entries": [x[2] for x in items],
        "free_days": free_days,
    }
