"""
Glätte-Hinweis fürs Rad (seit 1.37): Ist es morgens glatt, steht eine Karte „Glatt bis etwa 8 Uhr · lieber Bahn“ im Bild.

Der DWD warnt selbst vor Glätte (dann steht seine Warnung im Kopf, und dieser Hinweis entfällt). Seine
Warnungen kommen aber erst bei verbreiteter Gefahr. Für das Rad zählen schon einzelne glatte Stellen,
deshalb eine eigene, vorsichtige Schätzung aus der Stundenvorhersage:

  * überfrierende Nässe: Luft ≤ ICE_TEMP °C, und in den ICE_LOOKBACK Stunden davor war es nass
  * Schneeglätte: in den letzten SNOW_LOOKBACK Stunden hat es geschneit, und es ist ≤ ICE_TEMP °C
  * Reif: Luft ≤ 0 °C, Luftfeuchte ≥ REIF_RH % oder Taupunkt höchstens 1 Grad unter der Temperatur,
    in einer klaren Nacht (Bewölkung < REIF_CLOUD % in mindestens einer Stunde der Nacht davor)

Die Straße ist morgens oft kälter als die Luft in 2 m Höhe (Bright Sky liefert keine Bodentemperatur);
deshalb gilt schon +1 °C als kritisch. Geprüft werden die Stunden von FROM bis UNTIL Uhr am Fokustag
(Standard 5–10 Uhr, die Zeit, in der Leon aufs Rad steigt), heute nur die noch kommenden.

Ergebnis: {"until": datetime, "until_text": "9 Uhr", "reason": "Reif" | "überfrierende Nässe" | "Schnee",
"text": "Glatt bis etwa 9 Uhr", "sub": "Reif nach klarer Nacht", "advice": "lieber Bahn"} oder None.
Die Karte zeigt „Glatt bis etwa 9 Uhr“ / „Reif nach klarer Nacht · lieber Bahn“ (abends für morgen: „Morgen glatt …“).
"""

from datetime import datetime, timedelta

ICE_TEMP = 1.0
ICE_LOOKBACK = timedelta(hours=12)
SNOW_LOOKBACK = timedelta(hours=24)
REIF_RH = 92
REIF_CLOUD = 40
RAIN_MM = 0.1
FROM, UNTIL = 5, 10
WET = {"rain", "snow", "sleet", "hail"}
SNOW = {"snow", "sleet"}
DWD_WORDS = ("GLÄTTE", "GLATTEIS", "GLAETTE")


def _wet(r):
    return (r.get("precipitation") or 0) >= RAIN_MM or r.get("condition") in WET


def _snow(r):
    return _wet(r) and (r.get("condition") in SNOW or r.get("icon") in SNOW)


def reason_at(records, r):
    """Grund für Glätte in der Stunde von r oder None."""
    t = r.get("temperature")
    if t is None or t > ICE_TEMP:
        return None
    before = [x for x in records if r["dt"] - SNOW_LOOKBACK <= x["dt"] <= r["dt"]]
    if any(_snow(x) for x in before):
        return "Schnee"
    if any(_wet(x) for x in before if x["dt"] >= r["dt"] - ICE_LOOKBACK):
        return "überfrierende Nässe"
    if t <= 0:
        rh, dew = r.get("relative_humidity"), r.get("dew_point")
        humid = (rh is not None and rh >= REIF_RH) or (dew is not None and t - dew <= 1.0)
        night = [x for x in records if r["dt"] - timedelta(hours=10) <= x["dt"] <= r["dt"]]
        clear = any((x.get("cloud_cover") if x.get("cloud_cover") is not None else 100) < REIF_CLOUD for x in night)
        if humid and clear:
            return "Reif"
    return None


def dwd_warns(alert):
    """True, wenn die DWD-Warnung im Kopf schon von Glätte spricht."""
    text = " ".join(str((alert or {}).get(k) or "") for k in ("event", "level", "headline")).upper()
    return any(w in text for w in DWD_WORDS)


SUB = {"Reif": "Reif nach klarer Nacht", "überfrierende Nässe": "überfrierende Nässe", "Schnee": "Schnee und Frost"}


def check(records, now, d, alert=None, hours=(FROM, UNTIL)):
    """Glätte am Morgen des Tages d (siehe oben) oder None."""
    if not records or dwd_warns(alert):
        return None
    tz = now.tzinfo
    a = datetime.combine(d, datetime.min.time(), tz) + timedelta(hours=hours[0])
    b = datetime.combine(d, datetime.min.time(), tz) + timedelta(hours=hours[1])
    if d == now.date():
        a = max(a, now)
    if a >= b:
        return None
    window = [r for r in records if a < r["dt"] and r["dt"] - timedelta(hours=1) < b]
    found = [(r, reason_at(records, r)) for r in window]
    found = [(r, why) for r, why in found if why]
    if not found:
        return None
    last = found[-1][0]["dt"]   # Ende der letzten glatten Stunde
    # Nach Bright-Sky-Zählung gilt der Wert für die Stunde VOR dem Zeitstempel → „bis etwa 9 Uhr“
    if last >= b:
        until_text = f"nach {hours[1]} Uhr"
    else:
        until_text = f"{last.hour} Uhr"
    # wichtigster Grund: Schnee > überfrierende Nässe > Reif
    order = ("Schnee", "überfrierende Nässe", "Reif")
    why = min((w for _, w in found), key=order.index)
    text = f"Glatt bis {until_text}" if last >= b else f"Glatt bis etwa {until_text}"
    return {"until": last, "until_text": until_text, "reason": why, "text": text,
            "sub": SUB[why], "advice": "lieber Bahn"}
