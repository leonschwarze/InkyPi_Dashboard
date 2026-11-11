"""
Besondere Ansichten des Tagesdashboards:

  Nachtbild       (Standard 23–6 Uhr): ruhiges Bild für den kommenden Tag – Wetter, erste
                  Termine, Zug, Mondphase. Wird die ganze Nacht nicht neu gezeichnet.
  Wochenvorschau  (Standard sonntags 18–23 Uhr): die kommende Woche Mo–So in Zeilen mit
                  Wetter und Terminen.

Hier stehen nur die Datenaufbereitung und die Zeitfenster; gezeichnet wird im Template.
"""

import math
from datetime import datetime, time, timedelta, timezone

WOCHENTAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
KURZ = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September",
          "Oktober", "November", "Dezember"]


def hm(dt):
    return f"{dt.hour}:{dt.minute:02d}"


# ----------------------------------------------------------------------
# Zeitfenster (dürfen über Mitternacht gehen, z. B. 23:00–06:00)
# ----------------------------------------------------------------------
def in_window(now, start, end, weekday=None):
    t = now.time().replace(second=0, microsecond=0)
    if start <= end:
        hit = start <= t < end
        day = now.weekday()
    else:
        hit = t >= start or t < end
        day = now.weekday() if t >= start else (now.weekday() - 1) % 7  # Fenster begann gestern
    return hit and (weekday is None or day == weekday)


def window_end(now, start, end):
    """Ende des Fensters, in dem `now` liegt (für das eingefrorene Nachtbild)."""
    d = now.date()
    if start > end and now.time() >= start:
        d += timedelta(days=1)
    return datetime.combine(d, end, tzinfo=now.tzinfo)


def boundaries(now, start, end, days=2):
    out = []
    for offset in range(-1, days + 1):
        d = now.date() + timedelta(days=offset)
        out.append(datetime.combine(d, start, tzinfo=now.tzinfo))
        e = d + timedelta(days=1) if start > end else d
        out.append(datetime.combine(e, end, tzinfo=now.tzinfo))
    return out


# ----------------------------------------------------------------------
# Mond (ohne Internet berechnet; Genauigkeit etwa ±½ Tag)
# ----------------------------------------------------------------------
SYNODIC = 29.530588853
NEW_MOON_REF = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)


def moon(dt, cls="moon-svg"):
    age = ((dt - NEW_MOON_REF).total_seconds() / 86400) % SYNODIC
    lit = (1 - math.cos(2 * math.pi * age / SYNODIC)) / 2  # beleuchteter Anteil 0..1
    if age < 1.0 or age > SYNODIC - 1.0:
        name = "Neumond"
    elif age < 6.4:
        name = "zunehmende Sichel"
    elif age < 8.4:
        name = "erstes Viertel"
    elif age < 13.8:
        name = "zunehmender Mond"
    elif age < 15.8:
        name = "Vollmond"
    elif age < 21.1:
        name = "abnehmender Mond"
    elif age < 23.1:
        name = "letztes Viertel"
    else:
        name = "abnehmende Sichel"
    return {"name": name, "lit": lit, "svg": moon_svg(age, cls)}


def moon_svg(age, cls):
    """Mond als SVG: dunkle Scheibe, beleuchteter Teil gelb. Die Schattengrenze ist eine
    Halbellipse, deren Breite vom beleuchteten Anteil abhängt."""
    r, c = 20, 24
    phase = age / SYNODIC                      # 0 Neumond, .5 Vollmond
    rx = abs(math.cos(2 * math.pi * phase)) * r
    waxing = phase < 0.5
    gibbous = 0.25 < phase < 0.75
    side = 1 if waxing else 0                  # beleuchtete Seite: rechts (zunehmend) / links
    # Außenbogen über die beleuchtete Seite, zurück über die Schattengrenze
    sweep_back = (1 if gibbous else 0) if waxing else (0 if gibbous else 1)
    lit_path = (f"M{c},{c - r} A{r},{r} 0 0 {side} {c},{c + r} "
                f"A{rx:.2f},{r} 0 0 {sweep_back} {c},{c - r} Z")
    return (f'<svg class="{cls}" viewBox="0 0 48 48" aria-hidden="true">'
            f'<circle cx="{c}" cy="{c}" r="{r}" fill="#0B3D91"/>'
            f'<path d="{lit_path}" fill="#FFE500"/>'
            f'<circle cx="{c}" cy="{c}" r="{r}" fill="none" stroke="#000" stroke-width="2.4"/></svg>')


# ----------------------------------------------------------------------
# Wetter je Tag
# ----------------------------------------------------------------------
def day_summary(w, dwd, icons, records, d, icon_cls="wk-icon"):
    day = [r for r in records if r["dt"].date() == d]
    if len(day) < 6:  # zu wenig Stunden: lieber nichts anzeigen als Unsinn
        return None
    temps = [r["temperature"] for r in day if r.get("temperature") is not None]
    probs = [r["precipitation_probability"] for r in day if r.get("precipitation_probability") is not None]
    precip = sum(r.get("precipitation") or 0 for r in day)
    clouds = [r["cloud_cover"] for r in day if 7 <= r["dt"].hour <= 20 and r.get("cloud_cover") is not None]
    icon = w.day_icon(day)
    return {
        "icon": icons.weather_icon(icon, icon_cls),
        "tmax": dwd.de_num(max(temps)) if temps else "–",
        "tmin": dwd.de_num(min(temps)) if temps else "–",
        "prob": max(probs) if probs else None,
        "precip": dwd.de_num(precip, 1) if precip >= 0.05 else "0",
        "rainy": (max(probs) if probs else 0) >= 50 or precip >= 1,
        "text": dwd.condition_text(icon, precip / max(len(day), 1),
                                   sum(clouds) / len(clouds) if clouds else None, True),
    }


def night_low(records, now, until_hour=7):
    end = datetime.combine(now.date() + timedelta(days=0 if now.hour < 12 else 1), time(until_hour), tzinfo=now.tzinfo)
    temps = [r["temperature"] for r in records if now <= r["dt"] < end and r.get("temperature") is not None]
    return min(temps) if temps else None


# ----------------------------------------------------------------------
# Ansichten
# ----------------------------------------------------------------------
def train_chip(train_cfg, d):
    if not train_cfg or d.weekday() not in train_cfg["days"]:
        return None
    return f"{train_cfg['label']} {train_cfg['dep'].hour}:{train_cfg['dep'].minute:02d}"


def night(now, records, items, w, dwd, icons, train_cfg, sun_cache, max_events=5):
    """Nachtbild für den kommenden Tag (vor Mittag: heute, sonst morgen)."""
    d = now.date() if now.hour < 12 else now.date() + timedelta(days=1)
    wx = day_summary(w, dwd, icons, records, d, "nt-icon") if records else None
    low = night_low(records, now) if records else None
    sr, _ = sun_cache(d) if sun_cache else (None, None)
    timed = [it for it in items if not it["all_day"]]
    return {
        "weekday": WOCHENTAGE[d.weekday()],
        "date": f"{d.day}. {MONATE[d.month - 1]}",
        "kw": d.isocalendar()[1],
        "wx": wx,
        "night_low": dwd.de_num(low) if low is not None else None,
        "frost": low is not None and low <= 0,
        "sunrise": hm(sr) if sr else None,
        "all_day": [it for it in items if it["all_day"]][:2],
        "events": timed[:max_events],
        "more": max(0, len(timed) - max_events),
        "train": train_chip(train_cfg, d),
        "train_from": f"ab {train_cfg['station']}" if train_chip(train_cfg, d) else "",
        "moon": moon(datetime.combine(now.date(), time(23), tzinfo=now.tzinfo)),
    }


def week(now, records, day_items, w, dwd, icons, train_cfg, per_row=3):
    """Wochenvorschau: die nächsten Tage Mo–So (sonntags: ab morgen)."""
    start = now.date() + timedelta(days=(7 - now.weekday()) % 7 or 7)  # nächster Montag
    rows, total, rainy = [], 0, []
    for i in range(7):
        d = start + timedelta(days=i)
        items = day_items(d)
        wx = day_summary(w, dwd, icons, records, d) if records else None
        if wx and wx["rainy"]:
            rainy.append(KURZ[d.weekday()])
        total += len([it for it in items if not it["all_day"]])
        rows.append({
            "name": KURZ[d.weekday()],
            "date": f"{d.day}.{d.month}.",
            "weekend": d.weekday() >= 5,
            "wx": wx,
            "items": items[:per_row],
            "more": max(0, len(items) - per_row),
            "train": train_chip(train_cfg, d),
        })
    end = start + timedelta(days=6)
    span = (f"{start.day}.–{end.day}. {MONATE[end.month - 1]}" if start.month == end.month
            else f"{start.day}. {MONATE[start.month - 1]} – {end.day}. {MONATE[end.month - 1]}")
    summary = [f"{total} Termin{'e' if total != 1 else ''}"]
    if rainy:
        summary.append("Regen " + ", ".join(rainy))
    elif records:
        summary.append("kaum Regen")
    return {"kw": start.isocalendar()[1], "span": span, "summary": " · ".join(summary), "rows": rows}
