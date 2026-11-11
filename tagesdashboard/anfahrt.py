"""
Anfahrt zu Terminen: Rad oder ÖPNV – je nach Wetter – und wann man los muss.

Regeln
  * Rad nur bei schönem, sicher trockenem Wetter auf JEDEM Weg einer Terminkette
    (siehe bike_problem: kein Niederschlag, Regenrisiko unter der Schwelle, keine Sturmböen,
    keine Glätte; jeweils mit MARGIN Abstand vor und nach der Fahrt).
  * Kette: Termine, zwischen denen die Pause kürzer ist als maxGap. Dann fährt man nicht
    zwischendurch nach Hause. Regnet es auf einem Weg der Kette, gilt ÖPNV für die ganze Kette –
    sonst stünde man mit dem Rad am falschen Ort.
  * Der Heimweg zählt nur mit, wenn das eingestellt ist (Standard: nein).
  * Ankunft `buffer` Minuten vor Terminbeginn.
  * Termine ohne Ort oder mit Online-Stichwort (Video, Zoom …) werden übersprungen;
    sie unterbrechen eine Kette nicht.

Daten: Transitous (https://transitous.org), ein ehrenamtlich betriebener MOTIS-Server für
freie, nicht-kommerzielle Anwendungen. /api/v1/geocode für Orte, /api/v6/plan für Rad
(directModes=BIKE) und ÖPNV (arriveBy=true). Fahrplan: DELFI (deutschlandweit), Echtzeit über
die DELFI-Echtzeitfeeds, soweit der Verkehrsverbund liefert. Antworten werden im Speicher
gehalten (Orte und Radzeiten lange, ÖPNV kurz). Fällt der Dienst aus, wird aus der Luftlinie
geschätzt, wenn der Ort schon bekannt ist (Anzeige mit „ca.“).
"""

import logging
import math
import re
import time as _time
from datetime import datetime, timedelta, timezone

import requests

logger = logging.getLogger(__name__)

API = "https://api.transitous.org"
PLAN_PATHS = ("/api/v6/plan", "/api/v5/plan")  # neuere Version zuerst
TIMEOUT = 12
USER_AGENT = "InkyPi-Tagesdashboard/1.8 (privates E-Ink-Display, nicht-kommerziell)"

RAIN_MM = 0.1
GUST_MAX = 50            # km/h: ab Bft 7 macht Radfahren keinen Spaß mehr
ICE_TEMP = 1.0           # °C: darunter und vorher nass -> Glätte möglich
ICE_LOOKBACK = timedelta(hours=12)       # nach Regen: so lange können Pfützen überfrieren
SNOW_LOOKBACK = timedelta(hours=24)      # nach Schnee: liegt oft noch am nächsten Tag
MARGIN = timedelta(minutes=60)  # "sicher trocken": Vorhersagen verschieben sich gern um eine Stunde
WET = {"rain", "snow", "sleet", "hail"}
WET_ICONS = WET | {"thunderstorm"}
DEFAULT_SKIP = "Video, online, Zoom, Teams, Webex, Jitsi, Telefon"
DAYS = 2                 # heute und morgen
WALK_MAX = 10            # Minuten: kürzere Wege zu Fuß, sonst Bus und Bahn (Fußweg nur als Notlösung)

# Zwischenspeicher (nur im Speicher; ein Neustart des Dienstes leert ihn)
_GEO = {}        # Suchtext -> (lat, lon) oder None
_BIKE = {}       # (von, nach) -> (gültig bis, Minuten)
_TRANSIT = {}    # (von, nach, Ankunft) -> (gültig bis, Ergebnis)
BIKE_TTL = 7 * 24 * 3600
GEO_FAIL_TTL = 3600


def hm(dt):
    return f"{dt.hour}:{dt.minute:02d}"


def _int(text, default):
    text = str(text or "").strip()
    return int(text) if text.isdigit() else default


def parse_coord(text):
    """'50.73, 7.10' -> (50.73, 7.10), sonst None."""
    m = re.fullmatch(r"\s*(-?\d{1,2}(?:\.\d+)?)\s*[,; ]\s*(-?\d{1,3}(?:\.\d+)?)\s*", str(text or ""))
    if not m:
        return None
    lat, lon = float(m.group(1)), float(m.group(2))
    return (lat, lon) if -90 <= lat <= 90 and -180 <= lon <= 180 else None


def parse_places(text):
    """Zeilen 'Name = Adresse oder lat,lon' -> [(name klein, Suchtext)]. Längere Namen zuerst."""
    out = []
    for line in str(text or "").splitlines():
        name, sep, query = line.partition("=")
        if sep and name.strip() and query.strip():
            out.append((name.strip().lower(), query.strip()))
    return sorted(out, key=lambda p: -len(p[0]))


def read_config(opt, flag, home_lat, home_lon):
    if not flag("tripEnabled"):
        return None
    start = (opt("tripStart") or "").strip()
    return {
        "home_check": flag("tripHome"),
        "buffer": _int(opt("tripBuffer"), 5),
        "rain_prob": _int(opt("tripRainProb"), 30),
        "max_gap": _int(opt("tripMaxGap"), 90),
        "lead": _int(opt("tripLead"), 120),
        "start": start,
        "home": (home_lat, home_lon) if home_lat is not None and home_lon is not None else None,
        "places": parse_places(opt("tripPlaces")),
        "skip": [w.strip().lower() for w in (opt("tripSkip") or DEFAULT_SKIP).split(",") if w.strip()],
    }


def skipped(location, skip):
    loc = (location or "").strip().lower()
    if not loc or loc.startswith(("http://", "https://")):
        return True
    return any(re.search(rf"(?<!\w){re.escape(w)}", loc) for w in skip)


# ======================================================================
# Wetter
# ======================================================================
def _hour(dt):
    return "Mitternacht" if dt.hour == 0 else f"{dt.hour} Uhr"


def bike_problem(records, start, end, rain_prob):
    """Grund gegen das Rad für eine Fahrt start–end, sonst None.

    Ein Stundenwert gilt für die Stunde VOR seinem Zeitstempel (Bright Sky). Geprüft werden alle
    Stunden, die das Fenster start - MARGIN … end + MARGIN berühren."""
    a, b = start - MARGIN, end + MARGIN
    hours = [r for r in records if a < r["dt"] and r["dt"] - timedelta(hours=1) < b]
    if not hours:
        return {"kind": "unbekannt", "text": "keine Vorhersage", "dt": start}
    for r in hours:
        p = r.get("precipitation_probability")
        wet = (r.get("precipitation") or 0) >= RAIN_MM or r.get("condition") in WET or r.get("icon") in WET_ICONS
        if wet:
            kind = "Schnee" if (r.get("icon") in ("snow", "sleet") or r.get("condition") in ("snow", "sleet")) else (
                "Gewitter" if r.get("icon") == "thunderstorm" else "Regen")
            return {"kind": "regen", "text": f"{kind} ab {_hour(r['dt'])}", "dt": r["dt"]}
        if p is not None and p >= rain_prob:
            return {"kind": "risiko", "text": f"{round(p)} % Regenrisiko um {_hour(r['dt'])}", "dt": r["dt"]}
    gusts = [r for r in hours if (r.get("wind_gust_speed") or 0) >= GUST_MAX]
    if gusts:
        top = max(r["wind_gust_speed"] for r in gusts)
        return {"kind": "sturm", "text": f"Böen bis {round(top)} km/h", "dt": gusts[0]["dt"]}
    cold = [r for r in hours if r.get("temperature") is not None and r["temperature"] <= ICE_TEMP]
    if cold:
        t0 = cold[0]["dt"]

        def wet(r):
            return (r.get("precipitation") or 0) >= RAIN_MM or r.get("condition") in WET

        def snowy(r):
            return wet(r) and (r.get("condition") in ("snow", "sleet") or r.get("icon") in ("snow", "sleet"))
        if any(wet(r) for r in records if t0 - ICE_LOOKBACK <= r["dt"] <= b + timedelta(hours=1)) or \
                any(snowy(r) for r in records if t0 - SNOW_LOOKBACK <= r["dt"] <= t0):
            return {"kind": "glaette", "text": "Glättegefahr", "dt": t0}
    return None


# ======================================================================
# Transitous
# ======================================================================
def _session(session):
    s = session or requests.Session()
    s.headers.setdefault("User-Agent", USER_AGENT)
    return s


def _get(session, path, params):
    r = session.get(API + path, params=params, timeout=TIMEOUT)
    if r.status_code != 200:
        raise requests.HTTPError(f"HTTP {r.status_code}", response=r)
    return r.json()


def _plan(session, params):
    """Verbindungssuche; probiert die API-Versionen der Reihe nach (404 -> nächste)."""
    last = None
    for path in PLAN_PATHS:
        try:
            return _get(session, path, params)
        except requests.HTTPError as exc:
            last = exc
            if exc.response is None or exc.response.status_code != 404:
                raise
    raise last


def resolve(session, location, cfg):
    """Ort eines Termins -> (lat, lon) oder None. Eigene Ortsliste geht vor."""
    text = (location or "").strip()
    for name, query in cfg["places"]:
        if name in text.lower():
            text = query
            break
    direct = parse_coord(text)
    if direct:
        return direct
    key = text.lower()
    hit = _GEO.get(key)
    if hit is not None and (hit[0] is not None or hit[1] > _time.time()):
        return hit[0]
    params = {"text": text, "language": "de", "numResults": 1}
    if cfg.get("home"):
        params["place"] = f"{cfg['home'][0]},{cfg['home'][1]}"
    try:
        found = _get(session, "/api/v1/geocode", params)
        pos = (float(found[0]["lat"]), float(found[0]["lon"])) if found else None
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError) as exc:
        logger.warning("Anfahrt: Ort %r nicht gefunden: %s", text, exc)
        return None  # beim nächsten Mal wieder versuchen (kein Eintrag)
    _GEO[key] = (pos, _time.time() + GEO_FAIL_TTL)
    return pos


def distance_km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def estimate(a, b, mode):
    """Grobe Schätzung aus der Luftlinie, wenn Transitous nicht antwortet."""
    d = distance_km(a, b)
    if mode == "bike":
        return max(3, math.ceil(d * 1.3 / 15 * 60) + 2)
    return max(8, math.ceil(d * 1.4 / 14 * 60) + 12)


def _key(p):
    return f"{p[0]:.5f},{p[1]:.5f}"


def _utc(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ts(text, tz):
    return datetime.fromisoformat(str(text).replace("Z", "+00:00")).astimezone(tz)


def bike_minutes(session, a, b, arrive, tz):
    """(Minuten, geschätzt?) für eine Radfahrt von a nach b."""
    if distance_km(a, b) < 0.05:
        return 0, False
    k = (_key(a), _key(b))
    hit = _BIKE.get(k)
    if hit and hit[0] > _time.time():
        return hit[1], False
    params = {"fromPlace": _key(a), "toPlace": _key(b), "time": _utc(arrive), "arriveBy": "true",
              "directModes": "BIKE", "transitModes": "", "maxDirectTime": 5400, "detailedLegs": "false"}
    try:
        try:
            data = _plan(session, params)
        except requests.HTTPError as exc:  # falls der Server ein leeres transitModes ablehnt
            if exc.response is None or exc.response.status_code != 400:
                raise
            params.pop("transitModes")
            data = _plan(session, params)
        bikes =[it for it in data.get("direct") or [] if any(l.get("mode") == "BIKE" for l in it.get("legs") or [])]
        if not bikes:
            raise ValueError("keine Radroute")
        minutes = math.ceil(min(int(it["duration"]) for it in bikes) / 60)
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        logger.warning("Anfahrt: Radroute nicht berechnet (%s) – Schätzung", exc)
        return estimate(a, b, "bike"), True
    _BIKE[k] = (_time.time() + BIKE_TTL, minutes)
    return minutes, False


MODE_PREFIX = {"BUS": "Bus", "COACH": "Bus", "TRAM": "Bahn", "SUBWAY": "Bahn", "METRO": "Bahn",
               "SUBURBAN": "S", "FERRY": "Fähre"}
TRANSIT_MODES = set(MODE_PREFIX) | {"RAIL", "REGIONAL_RAIL", "REGIONAL_FAST_RAIL", "HIGHSPEED_RAIL",
                                    "LONG_DISTANCE", "NIGHT_RAIL", "TRANSIT", "FUNICULAR", "AERIAL_LIFT",
                                    "CABLE_CAR", "OTHER", "FLEX", "ODM"}


def line_name(leg):
    """'610' (BUS) -> 'Bus 610', 'S23' -> 'S 23', 'RE5' -> 'RE 5', '66' (TRAM) -> 'Bahn 66'."""
    short = str(leg.get("routeShortName") or leg.get("displayName") or "").strip()
    if not short:
        return MODE_PREFIX.get(leg.get("mode"), "ÖPNV")
    if re.match(r"^[A-Za-zÄÖÜäöü]", short):
        return re.sub(r"^([A-Za-zÄÖÜäöü]+)\s*(\d)", r"\1 \2", short)
    return f"{MODE_PREFIX.get(leg.get('mode'), 'Linie')} {short}"


def _short_stop(name):
    return re.sub(r"^Bonn[ ,-]+", "", str(name or "")).strip() or str(name or "")


def transit(session, a, b, arrive, tz, now):
    """Späteste ÖPNV-Verbindung (oder Fußweg), die bis `arrive` ankommt."""
    k = (_key(a), _key(b), arrive.isoformat())
    hit = _TRANSIT.get(k)
    if hit and hit[0] > _time.time():
        return hit[1]
    params = {"fromPlace": _key(a), "toPlace": _key(b), "time": _utc(arrive), "arriveBy": "true",
              "directModes": "WALK", "maxDirectTime": 1800, "searchWindow": 3600, "detailedLegs": "false"}
    data = _plan(session, params)
    options = []
    for it in (data.get("itineraries") or []):
        try:
            start, end = _ts(it["startTime"], tz), _ts(it["endTime"], tz)
        except (KeyError, ValueError):
            continue
        if end > arrive:
            continue
        legs = it.get("legs") or []
        rides = [l for l in legs if l.get("mode") in TRANSIT_MODES]
        if not rides:
            options.append({"depart": start, "arrive": end, "walk": True, "minutes": (end - start).total_seconds() / 60})
            continue
        first = rides[0]
        try:
            dep, plan_dep = _ts(first["startTime"], tz), _ts(first.get("scheduledStartTime") or first["startTime"], tz)
        except (KeyError, ValueError):
            continue
        if first.get("cancelled"):
            continue
        options.append({
            "depart": start, "arrive": end, "walk": False, "transfers": int(it.get("transfers") or 0),
            "line": line_name(first), "stop": _short_stop((first.get("from") or {}).get("name")),
            "ride_dep": dep, "delay": round((dep - plan_dep).total_seconds() / 60),
            "realtime": bool(first.get("realTime")),
        })
    for it in (data.get("direct") or []):
        if any(l.get("mode") == "WALK" for l in it.get("legs") or []) and it.get("duration") is not None:
            options.append({"depart": arrive - timedelta(seconds=int(it["duration"])), "arrive": arrive, "walk": True,
                            "minutes": int(it["duration"]) / 60})
    # Bei Regen fährt man – zu Fuß nur bei sehr kurzen Wegen oder wenn gar nichts fährt.
    rides = [o for o in options if not o["walk"]]
    options = [o for o in options if not o["walk"] or o["minutes"] <= WALK_MAX] + (
        [] if rides else [o for o in options if o["walk"] and o["minutes"] > WALK_MAX])
    options = [o for o in options if o["depart"] >= now - timedelta(minutes=10)] or options
    best = max(options, key=lambda o: (o["depart"], -o.get("transfers", 0))) if options else None
    soon = arrive - now < timedelta(hours=3)
    _TRANSIT[k] = (_time.time() + (600 if soon else 3 * 3600), best)
    return best


# ======================================================================
# Ketten und Entscheidung
# ======================================================================
def build_chains(events, now, cfg, tz):
    """Termine von heute und morgen -> Ketten [[ev, ev, …], …] (nur Termine mit echtem Ort)."""
    end_day = datetime.combine(now.date() + timedelta(days=DAYS), datetime.min.time(), tz)
    evs = [e for e in events
           if not e.get("all_day") and e["start"] < end_day and e["end"] > now - timedelta(hours=12)
           and not skipped(e.get("location"), cfg["skip"])]
    evs.sort(key=lambda e: e["start"])
    chains, gap = [], timedelta(minutes=cfg["max_gap"])
    for e in evs:
        last = chains[-1][-1] if chains else None
        if last and e["start"].date() == last["start"].date() and e["start"] - max(last["end"], last["start"]) < gap:
            chains[-1].append(e)
        else:
            chains.append([e])
    return chains


def plan(events, records, now, tz, cfg, session=None):
    """Ergebnis: {"by_event": {id(Rohtermin): Zeile}, "card": Karte oder None, "edges": [...]}"""
    out = {"by_event": {}, "card": None, "edges": []}
    if not cfg or not events:
        return out
    session = _session(session)
    home = parse_coord(cfg["start"]) or (resolve(session, cfg["start"], cfg) if cfg["start"] else cfg["home"])
    if not home:
        logger.warning("Anfahrt: kein Startort")
        return out
    buffer = timedelta(minutes=cfg["buffer"])
    cards = []
    for chain in build_chains(events, now, cfg, tz):
        stops = [(e, resolve(session, e["location"], cfg)) for e in chain]
        stops = [(e, p) for e, p in stops if p]
        if not stops or stops[-1][0]["end"] <= now:
            continue
        # Wege der Kette mit Radzeiten: Zuhause -> A -> B …
        legs, prev_pos, prev_ev = [], home, None
        for e, pos in stops:
            arrive = e["start"] - buffer
            minutes, est = bike_minutes(session, prev_pos, pos, arrive, tz)
            legs.append({"ev": e, "from": prev_pos, "to": pos, "prev": prev_ev, "arrive": arrive,
                         "bike_min": minutes, "bike_est": est, "bike_dep": arrive - timedelta(minutes=minutes)})
            prev_pos, prev_ev = pos, e
        last = stops[-1][0]
        home_min, _ = bike_minutes(session, prev_pos, home, last["end"], tz)
        home_leg = (last["end"], last["end"] + timedelta(minutes=home_min))

        # Wetter: ein Grund auf irgendeinem Weg -> ÖPNV für die ganze Kette.
        # Wege, die schon hinter einem liegen, zählen nicht mehr (man ist ja schon unterwegs).
        reason = None
        for leg in legs:
            if leg["arrive"] < now or leg["bike_min"] == 0:
                continue
            p = bike_problem(records, leg["bike_dep"], leg["arrive"], cfg["rain_prob"])
            if p:
                reason = dict(p, where=leg["ev"]["title"], first=leg is legs[0])
                break
        if reason is None and cfg["home_check"]:
            p = bike_problem(records, *home_leg, cfg["rain_prob"])
            if p:
                reason = dict(p, where=None, first=False, home=True)
        mode = "transit" if reason else "bike"

        for i, leg in enumerate(legs):
            e = leg["ev"]
            word = "Los" if i == 0 else "weiter"
            if leg["bike_min"] == 0 or leg["arrive"] < now:
                continue  # gleicher Ort wie der Termin davor bzw. Weg liegt schon hinter einem
            if mode == "bike":
                leg.update(depart=leg["bike_dep"], how="Rad", approx=leg["bike_est"])
            else:
                res = None
                try:
                    res = transit(session, leg["from"], leg["to"], leg["arrive"], tz, now)
                except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
                    logger.warning("Anfahrt: ÖPNV-Verbindung nicht abrufbar (%s) – Schätzung", exc)
                if res:
                    leg.update(depart=res["depart"], how="zu Fuß" if res["walk"] else res["line"], approx=False, ride=res)
                else:
                    leg.update(depart=leg["arrive"] - timedelta(minutes=estimate(leg["from"], leg["to"], "transit")),
                               how="ÖPNV", approx=True)
            ca = "ca. " if leg["approx"] else ""
            out["by_event"][id(e)] = f"{word} {ca}{hm(leg['depart'])} · {leg['how']}"

        first = legs[0]
        if "depart" not in first:
            continue
        out["edges"] += [first["depart"] - timedelta(minutes=cfg["lead"]), first["depart"] + timedelta(minutes=10)]
        if first["depart"] - timedelta(minutes=cfg["lead"]) <= now <= first["depart"] + timedelta(minutes=5):
            cards.append(card(first, legs, mode, reason, now, home_leg, cfg))
    out["card"] = cards[0] if cards else None
    return out


def card(first, legs, mode, reason, now, home_leg, cfg):
    """Aufbruch-Karte für den ersten Weg einer Kette."""
    e = first["ev"]
    ca = "ca. " if first.get("approx") else ""
    soon = now >= first["depart"] - timedelta(minutes=2)
    top = f"Jetzt los · {e['title']}" if soon else f"Los um {ca}{hm(first['depart'])} · {e['title']}"
    ride = first.get("ride")
    res = {"top": top, "delay": 0, "how_after": "", "why": why(legs, mode, reason, home_leg, cfg)}
    if mode == "bike":
        res.update(state="bike", icon="bike", badge="Rad",
                   how=f"{first['bike_min']} min mit dem Rad · an {hm(first['arrive'])}")
    elif ride and not ride["walk"]:
        delay = ride["delay"] if ride["realtime"] else 0
        res.update(state="transit", icon="bus", badge="Bus" if ride["line"].startswith("Bus") else "Bahn",
                   how=f"{ride['line']} ab {ride['stop']} {hm(ride['ride_dep'] - timedelta(minutes=delay))}",
                   delay=delay, how_after=f" · an {hm(ride['arrive'])}")
    elif ride:
        res.update(state="transit", icon="walk", badge="zu Fuß", how=f"zu Fuß · an {hm(ride['arrive'])}")
    else:
        res.update(state="transit", icon="bus", badge="ÖPNV", how="Verbindung gerade nicht abrufbar")
    return res


def why(legs, mode, reason, home_leg, cfg):
    """Dritte Zeile: die weiteren Termine der Kette und der Grund für die Wahl."""
    nxt = [f"{l['ev']['title']} {hm(l['ev']['start'])}" for l in legs[1:3]]
    if mode == "bike":
        parts = ["trocken auf allen Wegen" if (nxt or cfg["home_check"]) else "trocken"]
    else:
        parts = [reason["text"] + (" (Heimweg)" if reason.get("home") else "")]
    if nxt:  # Grund zuerst: Er erklärt die Wahl und darf nicht abgeschnitten werden
        parts.append("danach " + ", ".join(nxt))
    return " · ".join(parts)
