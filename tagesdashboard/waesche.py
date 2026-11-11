"""
Abends: Soll die Wäsche vom Balkon rein?

Geprüft wird die stündliche DWD-Vorhersage von jetzt bis morgen UNTIL_HOUR Uhr
(dann ist die Wäsche normalerweise wieder abgenommen oder trocknet in der Sonne).

Stufen (die erste zutreffende zählt):
  rein     Niederschlag (≥ 0,1 mm oder Wahrscheinlichkeit ≥ 60 %) oder Sturmböen (≥ 50 km/h)
  besser   Regen möglich (30–59 %), Nebel, Tau (Luft fast gesättigt, kaum Wind) oder Frost
  bleiben  nichts davon

Ist der Balkon überdacht, zählt Regen nur bei Wind (Böen ≥ 35 km/h treiben ihn unter das Dach).
"""

from datetime import datetime, time, timedelta

UNTIL_HOUR = 10
RAIN_MM = 0.1
RAIN_PROB_SURE = 60
RAIN_PROB_MAYBE = 30
GUST_STORM = 50       # km/h, ab Bft 7 fliegen Klammern und Wäscheständer
GUST_DRIVING_RAIN = 35
DEW_SPREAD = 1.5      # K: Temperatur kaum über dem Taupunkt -> Tau
DEW_HUMIDITY = 93     # %
DEW_MAX_WIND = 10     # km/h: bei mehr Wind bildet sich kaum Tau
WET = {"rain", "snow", "sleet", "hail"}


def _h(dt):
    return "Mitternacht" if dt.hour == 0 else f"{dt.hour} Uhr"


def _is_wet(r):
    return (r.get("precipitation") or 0) >= RAIN_MM or r.get("condition") in WET


def _kind(rs):
    """Regen, Schnee oder beides – für den Text."""
    icons = {r.get("icon") for r in rs} | {r.get("condition") for r in rs}
    snow = bool(icons & {"snow", "sleet"})
    rain = bool(icons & {"rain", "hail", "thunderstorm"}) or not snow
    return "Schneeregen" if snow and rain and "sleet" in icons else ("Schnee" if snow else "Regen")


def period(now):
    """Zeitraum der Prüfung: jetzt bis morgen 10 Uhr (nach Mitternacht: bis heute 10 Uhr)."""
    day = now.date() + timedelta(days=0 if now.hour < 5 else 1)
    return now.replace(minute=0, second=0, microsecond=0), datetime.combine(day, time(UNTIL_HOUR), tzinfo=now.tzinfo)


def check(records, now, covered=False):
    start, end = period(now)
    hours = [r for r in records if start <= r["dt"] < end]
    if not hours:
        return None

    def at(r, prob):
        return r.get("precipitation_probability") is not None and r["precipitation_probability"] >= prob

    gust = max((r.get("wind_gust_speed") or 0) for r in hours)
    t_min = min((r["temperature"] for r in hours if r.get("temperature") is not None), default=None)

    sure = [r for r in hours if _is_wet(r) or at(r, RAIN_PROB_SURE)]
    maybe = [r for r in hours if at(r, RAIN_PROB_MAYBE)]
    if covered:  # unter dem Dach nur bei Wind nass
        sure = [r for r in sure if (r.get("wind_gust_speed") or 0) >= GUST_DRIVING_RAIN]
        maybe = [r for r in maybe if (r.get("wind_gust_speed") or 0) >= GUST_DRIVING_RAIN]
    storm = [r for r in hours if (r.get("wind_gust_speed") or 0) >= GUST_STORM]
    fog = [r for r in hours if r.get("icon") == "fog" or r.get("condition") == "fog"]
    dew = [r for r in hours
           if not (7 <= r["dt"].hour < 18)  # nachts und am frühen Morgen
           and r.get("temperature") is not None
           and (r.get("wind_speed") or 0) < DEW_MAX_WIND
           and ((r.get("relative_humidity") or 0) >= DEW_HUMIDITY
                or (r.get("dew_point") is not None and r["temperature"] - r["dew_point"] <= DEW_SPREAD))]

    tmin = f"tiefste {round(t_min)}°" if t_min is not None else ""
    until = f"morgen {UNTIL_HOUR} Uhr" if end.date() > now.date() else f"{UNTIL_HOUR} Uhr"

    def res(state, text, *details):
        badge = {"rein": "reinholen", "besser": "besser rein", "bleiben": "kann bleiben"}[state]
        return {"state": state, "badge": badge, "text": text, "details": " · ".join(d for d in details if d)}

    def stop(rs):
        """Ende der ersten zusammenhängenden Niederschlagsphase."""
        last = rs[0]["dt"]
        for r in rs[1:]:
            if r["dt"] - last > timedelta(hours=1):
                break
            last = r["dt"]
        return last + timedelta(hours=1)

    if sure:
        first = sure[0]["dt"]
        when = "jetzt" if first <= now else f"ab {_h(first)}"
        p = max((r.get("precipitation_probability") or 0) for r in sure)
        end_txt = _h(stop(sure))
        return res("rein", f"{_kind(sure)} {when}", f"{p} %" if p else "",
                   f"bis etwa {end_txt}" if end_txt != "Mitternacht" else "bis etwa Mitternacht")
    if storm:
        return res("rein", f"Sturmböen ab {_h(storm[0]['dt'])}", f"bis {round(gust)} km/h")
    if maybe:
        p = max(r["precipitation_probability"] for r in maybe)
        return res("besser", f"Regen möglich ab {_h(maybe[0]['dt'])}", f"bis {p} %", tmin)
    if fog:
        return res("besser", f"Nebel ab {_h(fog[0]['dt'])}", "wird wieder feucht")
    if dew:
        return res("besser", f"Tau ab {_h(dew[0]['dt'])}", "wird wieder feucht")
    if t_min is not None and t_min <= 0:
        return res("besser", f"Frost bis {round(t_min)}°", "Wäsche friert steif")
    return res("bleiben", "bleibt trocken", f"bis {until}")


def in_window(now, start, end):
    t = now.time().replace(second=0, microsecond=0)
    return start <= t < end


def boundaries(now, start, end, days=2):
    out = []
    for offset in range(days + 1):
        d = now.date() + timedelta(days=offset)
        out += [datetime.combine(d, start, tzinfo=now.tzinfo), datetime.combine(d, end, tzinfo=now.tzinfo)]
    return out
