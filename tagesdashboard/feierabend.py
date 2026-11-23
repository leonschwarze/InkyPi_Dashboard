"""Feierabend-Schwelle (seit 1.47, Leons Wahl „B Zeile unter Heute“, bis zum Nachtbild, ab 1 Termin).

Ist der letzte Termin des Tages vorbei, steht unter „Heute“ statt „Keine weiteren Termine“:
„✓ Feierabend seit 17:30 · 3 Termine“. Die Zeile bleibt, bis um 23 Uhr das Nachtbild übernimmt
(nach 20 Uhr also auch in der Abendansicht, die das Wetter für morgen zeigt).

Gezählt werden nur Termine mit Uhrzeit, die heute beginnen. Ganztägige (Müllabfuhr, Geburtstag)
zählen nie, abgelehnte und abgesagte Termine kommen gar nicht erst aus dem Kalender. Endet ein
heutiger Termin erst nach Mitternacht (Nachtzug nach Wien), gibt es heute keinen Feierabend.
"""


def hm(dt):
    return f"{dt.hour}:{dt.minute:02d}"


def todays(events, today):
    """Termine mit Uhrzeit und Dauer, die heute beginnen."""
    return [e for e in events
            if not e.get("all_day") and e["end"] > e["start"] and e["start"].date() == today]


def last_end(events, today):
    """Ende des letzten heutigen Termins – None ohne Termine oder wenn er erst nach Mitternacht endet."""
    evs = todays(events, today)
    if not evs:
        return None
    end = max(e["end"] for e in evs)
    return end if end.date() == today else None


def check(events, now, today):
    """Feierabend? Dann {since, since_text, count, count_text}, sonst None."""
    end = last_end(events, today)
    if end is None or now < end:
        return None
    n = len(todays(events, today))
    return {"since": end, "since_text": hm(end), "count": n,
            "count_text": f"{n} Termin{'e' if n != 1 else ''}"}


def boundaries(events, now, today):
    """Cache-Grenze: Das Bild wird zum Ende des letzten Termins neu gezeichnet (nicht bis zu 15 min später)."""
    end = last_end(events, today)
    return [end] if end and end > now else []


# Grünes Häkchen im Kreis vor der Zeile (32er-ViewBox; Kreis kräftig genug für E-Ink)
CHECK_ICON = ('<svg class="{cls}" viewBox="0 0 32 32" aria-hidden="true">'
              '<circle cx="16" cy="16" r="14" fill="#2E9E3F"/>'
              '<path d="M8.5 16.5 L14 22 L24 10.5" fill="none" stroke="#fff" stroke-width="4" stroke-linecap="round" '
              'stroke-linejoin="round"/></svg>')
