"""Wahlkampf-Modus (seit 1.23): Karte oben in der Terminspalte an Tagen, an denen ein Wahlkampftermin
ansteht, mit Wetter am Termin und dem Countdown bis zum Wahltag. Am Wahltag und am Tag davor
erscheint die Karte immer („Heute Landtagswahl · Wahllokale 8–18 Uhr“).

Einstellungen: Art der Wahl (Landtags-, Bundestags-, Europa- oder Kommunalwahl – bestimmt nur die
Bezeichnung), Wahltag und Stichwörter für Wahlkampftermine im Kalender (Standard „Haustür,
Infostand, Wahlkampf, Plakat, Verteilaktion“). Nur für die Landtagswahl NRW ist der Wahltag
(25.04.2027) fest eingebaut; bei den anderen Wahlarten muss er eingetragen werden – ohne Datum
bleibt der Modus stumm, statt ein erfundenes Datum zu zeigen. Nach dem Wahltag verschwindet die Karte.

Wetter am Termin: Draußen zählen Regen, gefühlte Kälte und – im Winter entscheidend für
Haustürbesuche – wann es dunkel wird.
"""
from datetime import date, datetime, timedelta

ARTEN = {"landtag": "Landtagswahl", "bundestag": "Bundestagswahl", "europa": "Europawahl",
         "kommunal": "Kommunalwahl"}
DEFAULT_ART = "landtag"
DEFAULT_DAYS = {"landtag": "2027-04-25"}      # Landtagswahl Nordrhein-Westfalen
DEFAULT_WORDS = "Haustür, Infostand, Wahlkampf, Plakat, Verteilaktion"
RAIN_MM = 0.1


def read_day(text, art=DEFAULT_ART):
    """Wahltag aus der Einstellung (JJJJ-MM-TT) oder der eingebaute Termin der Wahlart; sonst None."""
    raw = (text or "").strip() or DEFAULT_DAYS.get(art)
    try:
        return date.fromisoformat(raw) if raw else None
    except ValueError:
        return None


def read_config(opt, flag, today):
    """Einstellungen als dict (day, label, words) oder None: ausgeschaltet, kein Wahltag, vorbei."""
    if not flag("wahlEnabled"):
        return None
    art = (opt("wahlArt") or DEFAULT_ART).strip().lower()
    art = art if art in ARTEN else DEFAULT_ART
    day = read_day(opt("wahlTag"), art)
    if not day or today > day:
        return None
    return {"day": day, "label": ARTEN[art], "words": opt("wahlWords") or DEFAULT_WORDS}


def countdown(today, day, label=ARTEN[DEFAULT_ART]):
    """Kurztext und Zahl. None nach dem Wahltag."""
    if not day or today > day:
        return None
    n = (day - today).days
    if n == 0:
        return {"n": 0, "text": f"Heute ist {label}", "badge": ("Heute", "")}
    if n == 1:
        return {"n": 1, "text": f"Morgen ist {label}", "badge": ("Morgen", "")}
    return {"n": n, "text": f"{label} in {n} Tagen", "badge": (str(n), "Tage")}


def is_campaign(title, words):
    t = (title or "").lower()
    return any(w.strip().lower() in t for w in words.split(",") if w.strip())


def _hm(dt):
    return f"{dt.hour}:{dt.minute:02d}"


def weather_at(ev_source, records, sunset, feels_like):
    """Wetter während eines Wahlkampftermins: (Text kurz, Text lang, Stufe ok/achtung)."""
    s, e = ev_source["start"], ev_source["end"]
    hours = [r for r in records if s < r["dt"] <= e + timedelta(minutes=59)]
    if not hours:
        return None
    wet = [r for r in hours if (r.get("precipitation") or 0) >= RAIN_MM]
    feels = [feels_like(r.get("temperature"), r.get("wind_speed"), r.get("relative_humidity")) for r in hours]
    feels = [f for f in feels if f is not None]
    level = "ok"
    if not wet:
        rain = "trocken"
    elif len(wet) == len(hours):
        rain, level = "Regen", "achtung"
    else:
        # Wie die Tageskurve: Datensatz 17:00 = „Regen 17 Uhr“ (Handbuch, Bright Sky)
        first = wet[0]["dt"]
        rain = f"Regen ab {first.hour} Uhr" if first > s + timedelta(hours=1) else f"Regen bis {wet[-1]['dt'].hour} Uhr"
        level = "achtung"
    dark = f"dunkel ab {_hm(sunset)}" if sunset and s.date() == sunset.date() and sunset < e else None
    felt = f"gefühlt {round(min(feels))}°" if feels else None
    # Reihenfolge nach Wichtigkeit: Was abgeschnitten wird, steht hinten
    short = " · ".join(x for x in (rain, dark, felt) if x)
    return {"short": short, "level": level, "rain": rain, "dark": dark, "felt": felt,
            "time": f"{s.hour}–{e.hour} Uhr" if e.minute == 0 and s.minute == 0 else f"{_hm(s)}–{_hm(e)}"}
