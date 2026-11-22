"""
Lauf-Fenster (seit 1.37): die beste Zeit des Tages für eine Runde draußen.

Aus der Stundenvorhersage (Bright Sky) und dem Kalender wird die Zeitspanne gesucht, in der man
mindestens DAUER Minuten am Stück laufen kann:
  * hell: zwischen Sonnenaufgang und Sonnenuntergang (Ende des Laufs spätestens zum Sonnenuntergang)
  * trocken: kein Niederschlag, Regenrisiko unter RAIN_PROB
  * erträglich: −3 bis 26 °C, Böen unter GUST_MAX km/h, keine Glätte (glaette.py)
  * frei: kein Termin mit Uhrzeit überschneidet sich mit der Spanne (mit PUFFER davor und danach;
    ganztägige Termine wie Müllabfuhr oder Geburtstage stören nicht, Online-Termine schon)
Gibt es mehrere Spannen, gewinnt die mit der besten Wertung (angenehme Temperatur um 10 °C, wenig Wind,
Sonne; längere Spannen etwas besser). Angezeigt wird die ganze freie Spanne („14–16:30“), nicht nur der
beste Start – man soll sehen, wie viel Spielraum es gibt.

Heute zählt nur, was noch kommt (ab jetzt, auf die nächste Viertelstunde gerundet); läuft die Spanne
schon, heißt es „Laufen jetzt bis 16“. Die Karte verschwindet, wenn keine ganze Runde mehr hineinpasst. Abends nach
dem Wechsel auf „morgen“ (switchHour) gilt die Spanne für morgen.
"""

from datetime import datetime, timedelta

STEP = timedelta(minutes=15)
DAUER = 60              # Minuten (Standard der Einstellung runMinutes)
PUFFER = timedelta(minutes=30)   # vor und nach Terminen (Umziehen, Duschen, Hinweg)
RAIN_PROB = 30          # %
RAIN_MM = 0.1
GUST_MAX = 50           # km/h
T_MIN, T_MAX = -3.0, 26.0
WET = {"rain", "snow", "sleet", "hail", "thunderstorm"}


def hm(dt):
    return f"{dt.hour}:{dt.minute:02d}" if dt.minute else f"{dt.hour}"


def _hour_for(records, t):
    """Stundenwert, der den Zeitpunkt t abdeckt (Bright Sky: Wert gilt für die Stunde VOR dem Zeitstempel)."""
    for r in records:
        if r["dt"] - timedelta(hours=1) <= t < r["dt"]:
            return r
    return None


def hour_ok(r, icy=False):
    """Grund gegen das Laufen in dieser Stunde oder None."""
    if r is None:
        return "keine Vorhersage"
    if (r.get("precipitation") or 0) >= RAIN_MM or r.get("icon") in WET or r.get("condition") in WET:
        return "nass"
    p = r.get("precipitation_probability")
    if p is not None and p >= RAIN_PROB:
        return "Regenrisiko"
    t = r.get("temperature")
    if t is None or not (T_MIN <= t <= T_MAX):
        return "Temperatur"
    if (r.get("wind_gust_speed") or 0) >= GUST_MAX:
        return "Böen"
    if icy:
        return "Glätte"
    return None


def busy(events, a, b):
    """True, wenn ein Termin mit Uhrzeit die Spanne a–b (plus Puffer) berührt."""
    for ev in events:
        if ev.get("all_day"):
            continue
        s, e = ev.get("start"), ev.get("end") or ev.get("start")
        if s is None:
            continue
        if s < b + PUFFER and e > a - PUFFER:
            return True
    return False


def find(records, events, now, d, sun, minutes=DAUER, icy_until=None):
    """Beste freie Spanne am Tag d oder None.
    events: Termine des Tages mit "start"/"end" (aware datetime) und "all_day".
    sun: (Sonnenaufgang, Sonnenuntergang) als datetime.
    icy_until: bis dahin ist es glatt (glaette.check), dann kein Laufen.
    Ergebnis: {"start", "end", "temp", "text", "short", "why"}"""
    if not records or not sun or not sun[0] or not sun[1]:
        return None
    sr, ss = sun
    tz = sr.tzinfo
    dur = timedelta(minutes=minutes)
    begin = sr
    if d == now.date():
        begin = max(begin, now)
    # auf die nächste Viertelstunde
    begin = begin.replace(second=0, microsecond=0)
    if begin.minute % 15:
        begin += timedelta(minutes=15 - begin.minute % 15)
    slots = []
    t = begin
    while t + STEP <= ss:
        r = _hour_for(records, t)
        icy = bool(icy_until and t < icy_until)
        good = hour_ok(r, icy) is None and not busy(events, t, t + STEP)
        slots.append((t, good, r))
        t += STEP
    # zusammenhängende gute Abschnitte
    spans, cur = [], []
    for t, good, r in slots:
        if good:
            cur.append((t, r))
        elif cur:
            spans.append(cur)
            cur = []
    if cur:
        spans.append(cur)
    spans = [s for s in spans if s[-1][0] + STEP - s[0][0] >= dur]
    if not spans:
        return None

    def score(span):
        recs = [r for _, r in span if r]
        temps = [r["temperature"] for r in recs]
        tm = sum(temps) / len(temps)
        wind = sum((r.get("wind_speed") or 0) for r in recs) / len(recs)
        sunny = sum((r.get("sunshine") or 0) for r in recs) / len(recs)
        length = (span[-1][0] + STEP - span[0][0]).total_seconds() / 3600
        return -abs(tm - 10) - wind / 10 + sunny / 30 + min(length, 3) * 0.8

    best = max(spans, key=score)
    a, b = best[0][0], best[-1][0] + STEP
    recs = [r for _, r in best if r]
    tmax = round(max(r["temperature"] for r in recs))
    tmin = round(min(r["temperature"] for r in recs))
    deg = lambda v: f"{v}°".replace("-", "−")  # noqa: E731 – echtes Minuszeichen
    temp = deg(tmin) if tmin == tmax else f"{deg(tmin)} bis {deg(tmax)}" if tmin < 0 else f"{tmin}–{tmax}°"
    sunny = any((r.get("sunshine") or 0) >= 20 for r in recs)
    light = f"hell bis {hm(ss)}" if (ss - b) < timedelta(minutes=60) else ("sonnig" if sunny else "")
    # Hat die Spanne schon begonnen, würde ihr Beginn bei jedem Neuzeichnen um eine Viertelstunde wandern
    # („10–16“, „10:15–16“ …) – dann lieber „jetzt bis 16“, das bleibt stehen.
    started = d == now.date() and a <= now + STEP
    span = f"jetzt bis {hm(b)}" if started else f"{hm(a)}–{hm(b)}"
    why = " · ".join(x for x in (temp, "trocken", light) if x)
    return {"start": a, "end": b, "last_start": b - dur, "span": span, "temp": temp, "why": why, "sunset": hm(ss),
            "text": f"Laufen {span}", "full": f"Laufen {span} · {why}"}
