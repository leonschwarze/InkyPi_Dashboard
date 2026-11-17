"""Wetter am Zielort: Liegt ein Termin außerhalb des Wetter-Orts (z. B. in Düsseldorf), steht das
Wetter dort mit dabei.

Erkennen (`place_of`): Aus dem Ort des Termins werden Ortsnamen herausgesucht (`candidates`):
PLZ + Ort zuerst, sonst die Teile zwischen den Kommas von hinten; Straßen, Hausnummern und Links
fallen weg, „Köln Hbf“ wird zu „Köln“, „Köln-Mülheim“ wird auch als „Köln“ versucht. Jeder Kandidat
geht an die Geokodierung von Open-Meteo (wie beim Urlaubsbild); vorher gelten die „Eigenen Orte“ der
Anfahrt (`tripPlaces`, z. B. „Landtag = 51.2259, 6.7730“), auch wenn die Anfahrt aus ist. Angenommen wird nur ein bewohnter
Ort (GeoNames-Klasse PPL…), in Deutschland jeder, im Ausland nur ab `ABROAD_MIN_POP` Einwohnern –
sonst fände „Post Tower“ das texanische Städtchen Post. Liegt der Ort mindestens `min_km` vom
Wetter-Ort entfernt, gilt der Termin als auswärts.

Wetter (`summary`): Bright Sky am Zielort (dieselbe Abfrage wie beim Urlaubsbild, eine Stunde
gehalten), ausgewertet für die Dauer des Termins (mindestens eine Stunde, Zeitstempel wie in der
Tageskurve): Symbol, Temperatur, Regen (Wahrscheinlichkeit ab 50 % wie der Regenhinweis am Termin
oder ≥ 0,1 mm; „Regen ab 14 Uhr“, wenn er erst während des Termins beginnt).

Anzeige (`annotate`, Variante A): eine Zeile unter dem Termin, „Düsseldorf 10° · Regen ab 14 Uhr“.
Die Kleidungsempfehlung bleibt beim Wetter-Ort (Leons Wahl).
"""
import logging
import math
import re
import time as _time
from datetime import timedelta

import requests

try:
    from . import anfahrt, status, urlaub
except ImportError:  # Tests importieren die Module ohne Paket
    import anfahrt
    import status
    import urlaub

logger = logging.getLogger(__name__)

NAME = "Zielort"          # so heißt die Quelle in der Statusanzeige
MIN_KM = 30               # Leons Wahl: Köln (25 km) zählt noch als zu Hause, Düsseldorf (60 km) nicht
ABROAD_MIN_POP = 100_000  # im Ausland nur Großstädte (Paris, Brüssel, Straßburg), keine Namensvettern
RAIN_PROB = 50            # wie rain_during() am Termin
RAIN_MM = 0.1
GEO_RETRY_MIN = 60        # Dienst gestört: nach einer Stunde wieder fragen
NOT_FOUND_RETRY_H = 24    # kein Ort im Text („Café Müller“): erst morgen wieder fragen

STREET = re.compile(r"(stra(ß|ss)e|str\.|allee|platz|weg|ring|gasse|ufer|damm|markt|chaussee)\b", re.I)
# Zusätze, die keinen eigenen Ort meinen: „Köln Hbf“, „Düsseldorf Flughafen“, „Essen Mitte“
SUFFIX = {"hbf", "hbf.", "hauptbahnhof", "bahnhof", "bf", "bf.", "flughafen", "airport", "messe", "zentrum",
          "innenstadt", "altstadt", "mitte", "süd", "nord", "ost", "west", "city"}
LINK = re.compile(r"(https?://|www\.|\.[a-z]{2,3}/)", re.I)

_geo = {}   # kleingeschriebener Name -> (monotonic, Treffer | None)


def candidates(location):
    """Mögliche Ortsnamen in einer Ortsangabe, wahrscheinlichste zuerst."""
    loc = (location or "").strip()
    if not loc or LINK.search(loc):
        return []
    out = []
    for m in re.finditer(r"\b\d{5}\s+([A-ZÄÖÜ][^,;\n]*)", loc):  # „40221 Düsseldorf“
        out.append(m.group(1).strip())
    for p in reversed([p.strip() for p in re.split(r"[,;\n]", loc) if p.strip()]):
        p = re.sub(r"^\d{5}\s+", "", p)
        if any(c.isdigit() for c in p) or STREET.search(p):
            continue
        words = p.split()
        while len(words) > 1 and words[-1].lower() in SUFFIX:  # „Köln Hbf“ → „Köln“
            words.pop()
        name = " ".join(words)
        out.append(name)
        if "-" in name and " " not in name:                     # „Köln-Mülheim“ → auch „Köln“
            out.append(name.split("-")[0])
    seen, res = set(), []
    for c in out:
        c = c.strip(" .")
        if len(c) >= 3 and c.lower() not in seen:
            seen.add(c.lower())
            res.append(c)
    return res


def acceptable(res):
    """Nur bewohnte Orte; im Ausland nur große (Namensvettern wie Post/Texas fallen weg)."""
    if not str(res.get("feature_code") or "").startswith("PPL"):
        return False
    if (res.get("country_code") or "").upper() == "DE":
        return True
    return (res.get("population") or 0) >= ABROAD_MIN_POP


def geocode(name, session=None):
    """{name, pos, country} für einen Ortsnamen oder None. Treffer bleiben im Speicher."""
    key = name.strip().lower()
    hit = _geo.get(key)
    if hit and (hit[1] is not None or _time.monotonic() - hit[0] < hit[2]):
        return hit[1]
    status.use(NAME)
    found = None
    try:
        r = (session or requests.Session()).get(urlaub.GEOCODE_URL, params={
            "name": name, "count": 5, "language": "de", "format": "json"}, timeout=urlaub.TIMEOUT)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}")
        for res in r.json().get("results") or []:
            if acceptable(res):
                found = {"name": res.get("name") or name, "country": res.get("country_code") or "",
                         "pos": (float(res["latitude"]), float(res["longitude"]))}
                break
        status.ok(NAME)
    except Exception as exc:  # Zusatz: nie das Bild verlieren
        logger.warning("Zielort %s nicht auffindbar: %s", name, exc)
        status.fail(NAME, exc)
        _geo[key] = (_time.monotonic(), None, GEO_RETRY_MIN * 60)
        return None
    if not found:
        logger.info("Zielort: „%s“ ist kein bekannter Ort", name)
    _geo[key] = (_time.monotonic(), found, NOT_FOUND_RETRY_H * 3600)
    return found


def km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def own_place(location, places):
    """Eigene Orte der Anfahrt („Landtag = 51.2259, 6.7730“ oder „= Adresse“): (Name, Position, Adresse).

    Wie bei der Anfahrt genügt es, wenn der Name im Ortsfeld vorkommt; längere Namen zuerst
    (`anfahrt.parse_places`). Bei einer Koordinate fehlt ein Ortsname – dann steht der eigene Name
    so in der Zeile, wie er im Termin geschrieben ist.
    """
    text = location or ""
    low = text.lower()
    for name, query in places or ():
        i = low.find(name)
        if i < 0:
            continue
        coord = anfahrt.parse_coord(query)
        return (text[i:i + len(name)], coord, None if coord else query)
    return None


def place_of(location, home, min_km=MIN_KM, session=None, places=()):
    """(Treffer, km) für einen auswärtigen Ort, sonst None. Der erste gefundene Kandidat entscheidet."""
    own = own_place(location, places)
    if own and own[1]:
        dist = km(home, own[1])
        return ({"name": own[0], "pos": own[1], "country": ""}, dist) if dist >= min_km else None
    for cand in candidates(own[2] if own else location):
        hit = geocode(cand, session)
        if hit:
            dist = km(home, hit["pos"])
            return (hit, dist) if dist >= min_km else None
    return None


def window(records, start, end):
    """Stundenwerte, die den Termin berühren (Zeitstempel = Ende der Stunde, wie die Tageskurve)."""
    end = max(end, start + timedelta(hours=1))
    return [r for r in records if start < r["dt"] < end + timedelta(hours=1) and r.get("temperature") is not None]


def hm(dt):
    return f"{dt.hour}:{dt.minute:02d}"


def summary(recs, start, w, dwd, icons):
    """Wetter am Ziel während des Termins oder None (keine Daten).

    `rain`: „Regen ab 14 Uhr“, wenn es erst während des Termins nass wird, sonst „Regen 80 %“
    (bzw. „Schnee …“); None, wenn es trocken bleibt – dann steht `text` („Bewölkt“) in der Zeile.
    """
    if not recs:
        return None
    temps = [r["temperature"] for r in recs]
    probs = [r["precipitation_probability"] for r in recs if r.get("precipitation_probability") is not None]
    clouds = [r["cloud_cover"] for r in recs if r.get("cloud_cover") is not None]
    precip = sum(r.get("precipitation") or 0 for r in recs)
    wet = [r for r in recs if (r.get("precipitation_probability") or 0) >= RAIN_PROB
           or (r.get("precipitation") or 0) >= RAIN_MM]
    is_day = any(7 <= r["dt"].hour <= 19 for r in recs)
    icon = w.day_icon(recs)
    if wet and icon in ("clear-day", "clear-night", "partly-cloudy-day", "partly-cloudy-night", "cloudy"):
        icon = "showers-day"  # day_icon braucht zwei nasse Stunden, hier zählt schon eine
    if not is_day:  # day_icon kennt nur Tagessymbole; abends Mond statt Sonne
        icon = {"clear-day": "clear-night", "partly-cloudy-day": "partly-cloudy-night",
                "showers-day": "showers-night"}.get(icon, icon)
    lo, hi = round(min(temps)), round(max(temps))
    prob = round(max(probs)) if probs else None
    rain = None
    if wet:
        first = wet[0]["dt"] - timedelta(hours=1)  # Datensatz 15:00 = Regen 14–15 Uhr
        word = "Schnee" if any(r.get("icon") in ("snow", "sleet") for r in wet) else "Regen"
        if first > start:
            rain = f"{word} ab {first.hour} Uhr"
        else:
            rain = f"{word} {prob} %" if prob and prob >= RAIN_PROB else word
    return {
        "icon_name": icon,
        "icon": icons.weather_icon(icon, "zo-icon"),
        # kleine Spannen sind Rauschen: dann nur der Höchstwert („10°“ statt „9–10°“)
        "temp": f"{dwd.de_num(hi)}°" if hi - lo < 3 else f"{dwd.de_num(lo)}–{dwd.de_num(hi)}°",
        "text": dwd.condition_text(icon, precip / len(recs), sum(clouds) / len(clouds) if clouds else None, is_day),
        "rain": rain,
    }


def annotate(it):
    """Eintrag fürs Template: Zeile „Düsseldorf 10° · Regen ab 14 Uhr“, Ort gekürzt, kein Regenhinweis.

    Der Regenhinweis am Termin („85 % Regen“) galt dem Wetter-Ort – am Ziel steht der Regen jetzt in
    der eigenen Zeile. Der Ort wird auf den ersten Teil gekürzt („Landtag NRW“); ist das schon der
    Ortsname, fällt er weg (sonst stünde „Düsseldorf“ zweimal da).
    """
    x = it["away"]
    it["rain"] = None
    first = (it.get("location") or "").split(",")[0].strip()
    it["location"] = "" if first.lower() == x["place"].lower() else first
    it["away_line"] = f"{x['place']} {x['temp']} · {x['rain'] or x['text']}"
    return it


def find(calendar, home, tz, now, last_day, w, dwd, icons, parse_ts,
         min_km=MIN_KM, session=None, places=()):
    """Hängt an jeden auswärtigen Termin bis einschließlich `last_day` `away` = Ort + Wetter.

    `calendar` = Tage aus calendar_days(). Gibt die betroffenen Einträge zurück (zeitlich sortiert).
    Ganztägige, beendete und Termine ohne Ort bleiben unberührt.
    """
    found = []
    if not home or home[0] is None:
        return found
    for day in calendar:
        for it in day["events"]:
            ev = it.get("source") or {}
            if it.get("all_day") or not it.get("location") or not ev:
                continue
            if ev["end"] <= now or ev["start"].date() > last_day:
                continue
            hit = place_of(it["location"], home, min_km, session, places)
            if not hit:
                continue
            place, dist = hit
            recs = urlaub.fetch_records(place["pos"], tz, now, parse_ts, session, source=NAME)
            begin = max(ev["start"], now)  # läuft der Termin schon, zählt nur der Rest („Regen ab 14 Uhr“ um 15 Uhr wäre alt)
            wx = summary(window(recs, begin, ev["end"]), begin, w, dwd, icons)
            if not wx:
                continue
            it["away"] = dict(wx, place=place["name"], km=round(dist))
            logger.info("Zielort: %s → %s (%d km): %s · %s", it["title"], place["name"], dist, wx["temp"],
                        wx["rain"] or wx["text"])
            found.append(it)
    return found
