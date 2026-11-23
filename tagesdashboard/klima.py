"""
Klimaeinordnung und Wetter-Meilensteine (seit 1.41).

Was es zeigt
------------
- **Übliche Temperatur in der Tageskurve** (Leons Wahl „B“): blau gestrichelt der übliche Tagesgang für
  dieses Datum (aus den üblichen Höchst- und Tiefstwerten 1991–2020), dazu in der Kopfzeile der Kurve
  „Tagsüber 4° wärmer als üblich“, wenn kein Regen kommt.
- **Karte bei Ausreißern** (Leons Wahl „C“): nur wenn der Höchstwert so hoch oder so niedrig ist wie an
  höchstens 1 von 20 Tagen um dieses Datum (5 %/95 %) **und** mindestens 3° vom Üblichen abweicht:
  „Ungewöhnlich mild“ / „12° statt 8° · so mild zuletzt 2015“ (Wort nach dem Wert: mild/warm, kühl/kalt).
- **Meilensteine** (Leon wählte die Anlässe, Claude die Zeile unter der Temperatur): erster Frost, erster
  Eistag, erster Schnee, erster Sommertag, erstmals 30°, erste Tropennacht – jeweils „seit <Datum>“, wenn
  es mindestens GAP_DAYS Tage nicht so war –, Sonne nach mindestens 7 grauen Tagen, längste Regen- oder
  Trockenserie des Jahres. Frost und Tropennacht stehen auch in der Himmelszeile des Nachtbilds.

Quelle
------
Deutscher Wetterdienst, Climate Data Center (CDC), Tageswerte „kl“ der Klimastationen, frei und ohne
Schlüssel (Lizenz: Datenlizenz Deutschland – Namensnennung 2.0, Quelle: Deutscher Wetterdienst), unter BASE:
  recent/KL_Tageswerte_Beschreibung_Stationen.txt   Stationsliste (Lage, Höhe, Zeitraum)
  historical/                                        Verzeichnis: tageswerte_KL_<id>_<von>_<bis>_hist.zip
  recent/tageswerte_KL_<id>_akt.zip                  die letzten ~550 Tage bis gestern
In den ZIPs steht `produkt_klima_tag_*.txt`, Semikolon getrennt, Spalten u. a. MESS_DATUM (JJJJMMTT),
RSK (Niederschlag mm), RSKF (Form: 7 Schnee, 8 Regen und Schnee), SDK (Sonnenstunden), SHK_TAG
(Schneehöhe cm), TXK/TNK (Höchst-/Tiefstwert 2 m); -999 = fehlt.

Gewählt wird die nächste Station mit Messreihe ab spätestens 1991, die noch misst; 100 m Höhenunterschied
zählen wie 10 km Entfernung (eine Bergstation wäre kälter). Für Bonn ist das Bonn-Roleber (603) oder
Köln/Bonn (2667). Weiter als MAX_KM → keine Klimadaten.

Was gespeichert wird
--------------------
Eine Datei neben InkyPis device.json (STATE_FILE): Station, die Normalwerte je Kalendertag (Mittel von
Tiefst- und Höchstwert sowie 5-/95-%-Grenze des Höchstwerts, jeweils ±7 Tage um das Datum über 1991–2020)
und je Kalendertag die Höchstwerte aller Jahre (für „so mild zuletzt 2015“). Das baut sich einmal auf
(~1,5 MB Downloads) und erst nach REBUILD_DAYS (neues Jahr in den historischen Daten) oder nach einem
Ortswechsel neu. Dazu die Tageswerte der letzten Monate, neu geladen, sobald der DWD den gestrigen Tag hat
(meist vormittags) – höchstens alle RECENT_RETRY_H Stunden. Fehlt der gestrige Tag noch, kommt er aus den
stündlichen Werten von Bright Sky, die das Dashboard ohnehin lädt. Fehlschläge: neuer Versuch nach
RETRY_MIN Minuten, Statusname „Klimadaten“.
"""

import io
import json
import logging
import math
import os
import re
import tempfile
import time as _time
import zipfile
from datetime import date, datetime, timedelta

import requests

try:
    from . import status
except ImportError:  # Tests importieren die Module ohne Paket
    import status

logger = logging.getLogger(__name__)

BASE = "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/daily/kl/"
STATIONS_URL = BASE + "recent/KL_Tageswerte_Beschreibung_Stationen.txt"
HIST_DIR_URL = BASE + "historical/"
RECENT_URL = BASE + "recent/tageswerte_KL_{id:05d}_akt.zip"
HEADERS = {"User-Agent": "InkyPi-Tagesdashboard/1.41 (privates E-Ink-Display; github.com/leonschwarze/InkyPi_Dashboard)"}
STATUS_NAME = "Klimadaten"
STATE_FILE = "tagesdashboard_klima.json"
STATE_VERSION = 1
TIMEOUT = 30

MAX_KM = 50              # weiter weg ist keine Station „das Klima hier“
HEIGHT_KM_PER_M = 0.1    # 100 m Höhenunterschied zählen wie 10 km
MOVE_KM = 5              # Wetter-Ort weiter verschoben → Station neu wählen
NORMAL_FROM, NORMAL_TO = 1991, 2020
WINDOW = 7               # Normalwerte aus ±7 Tagen um das Datum (glättet, mehr Werte für die Grenzen)
MIN_VALUES = 300         # von höchstens 30 × 15 = 450 Tageswerten
REBUILD_DAYS = 400
RECENT_RETRY_H = 3
RETRY_MIN = 60

# Karte bei Ausreißern
CARD_PCT = 5             # unter 5 % bzw. über 95 % der Höchstwerte um dieses Datum
CARD_MIN_DIFF = 3        # und mindestens so viele Grad vom Üblichen weg
MILD_BELOW = 18          # wärmer als üblich und darunter: „mild“, sonst „warm“
COOL_FROM = 10           # kälter als üblich und ab da: „kühl“, sonst „kalt“

# Meilensteine
GAP_DAYS = 90            # „Erster Frost seit …“ nur nach so vielen Tagen ohne
SUN_MIN_H = 2.0          # „Sonne“: mindestens 2 Stunden …
GREY_MAX_H = 0.5         # … nach Tagen mit jeweils höchstens einer halben Stunde
GREY_MIN_DAYS = 7
WET_MM, DRY_MM = 1.0, 0.1
WET_MIN_DAYS, DRY_MIN_DAYS = 5, 10
SERIES_FROM_DOY = 45     # Mitte Februar: vorher ist fast jede Serie „die längste des Jahres“
MAX_MISSING = 3          # so viele fehlende Tage im Rückblick sind erlaubt

MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober",
          "November", "Dezember"]

_state = {"path": None, "data": None}
_retry = {}              # Schritt -> monotonic des letzten Fehlschlags


# ---------------------------------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------------------------------
def state_path(device_config):
    """Datei neben InkyPis device.json; ohne InkyPi-Konfiguration im Temp-Ordner."""
    cfg = getattr(device_config, "config_file", None)
    base = os.path.dirname(cfg) if isinstance(cfg, str) and cfg else tempfile.gettempdir()
    return os.path.join(base, STATE_FILE)


def km(lat1, lon1, lat2, lon2):
    """Entfernung auf der Kugel in km."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(min(1.0, a)))


def day_key(d):
    """„11-24“; der 29.2. nimmt die Normalwerte des 28.2."""
    return f"{d.month:02d}-{d.day:02d}"


def date_text(d):
    return f"{d.day}. {MONATE[d.month - 1]}"


def date_short(d):
    return f"{d.day}.{d.month}."


def num(v):
    """Ganze Grad, „-0“ wird „0“ (wie dwd_wetter.de_num)."""
    t = str(int(round(v)))
    return "0" if t == "-0" else t


def percentile(sorted_vals, p):
    """Lineare Interpolation wie numpy (p in Prozent)."""
    if not sorted_vals:
        return None
    k = (len(sorted_vals) - 1) * p / 100
    lo = math.floor(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


def _blocked(step):
    t = _retry.get(step)
    return t is not None and _time.monotonic() - t < RETRY_MIN * 60


def _get(session, url):
    r = session.get(url, headers=HEADERS, timeout=TIMEOUT)
    if r.status_code != 200:
        raise RuntimeError(f"DWD: HTTP {r.status_code} für {url.rsplit('/', 1)[-1] or url}")
    return r


# ---------------------------------------------------------------------------------------------------
# Lesen der DWD-Dateien
# ---------------------------------------------------------------------------------------------------
def parse_stations(text):
    """Stationsliste → [{id, von, bis, hoehe, lat, lon, name}]. Zwei Kopfzeilen, dann feste Spalten."""
    out = []
    for line in text.splitlines():
        t = line.split()
        if len(t) < 7 or not t[0].isdigit() or not t[1].isdigit():
            continue
        try:
            st = {"id": int(t[0]), "von": t[1], "bis": t[2], "hoehe": float(t[3]),
                  "lat": float(t[4]), "lon": float(t[5])}
        except ValueError:
            continue
        # Name bis zum Bundesland; Namen haben Leerzeichen, das Bundesland meist nicht
        rest = t[6:]
        if len(rest) >= 2 and rest[-1] in ("Frei", "frei"):
            rest = rest[:-1]
        st["name"] = " ".join(rest[:-1]) if len(rest) > 1 else (rest[0] if rest else str(st["id"]))
        out.append(st)
    return out


def choose_station(stations, lat, lon, today, height=None):
    """Nächste Station mit Messreihe ab spätestens 1991, die noch misst (Ende höchstens 60 Tage her)."""
    recent = (today - timedelta(days=60)).strftime("%Y%m%d")
    best = None
    for st in stations:
        if st["von"] > f"{NORMAL_FROM}0101" or st["bis"] < recent:
            continue
        dist = km(lat, lon, st["lat"], st["lon"])
        if dist > MAX_KM:
            continue
        score = dist + (abs(st["hoehe"] - height) * HEIGHT_KM_PER_M if height is not None else 0)
        if best is None or score < best[0]:
            best = (score, dict(st, km=round(dist, 1)))
    return best[1] if best else None


def hist_names(listing, station_id):
    """Dateinamen der historischen ZIPs dieser Station aus dem Verzeichnis (HTML)."""
    pat = re.compile(r"tageswerte_KL_%05d_(\d{8})_(\d{8})_hist\.zip" % station_id)
    return sorted(set(m.group(0) for m in pat.finditer(listing)))


def parse_product(raw_zip):
    """ZIP → {date: {tn, tx, rsk, rskf, sdk, shk}}; fehlende Werte (-999) als None."""
    zf = zipfile.ZipFile(io.BytesIO(raw_zip))
    name = next((n for n in zf.namelist() if n.startswith("produkt_klima_tag")), None)
    if not name:
        raise RuntimeError("DWD: keine Produktdatei im ZIP")
    text = zf.read(name).decode("latin-1")
    lines = text.splitlines()
    head = [h.strip().upper() for h in lines[0].split(";")]
    col = {h: i for i, h in enumerate(head)}
    need = {"MESS_DATUM", "TXK", "TNK"}
    if not need <= col.keys():
        raise RuntimeError("DWD: unbekanntes Format der Tageswerte")

    def val(t, key):
        i = col.get(key)
        if i is None or i >= len(t):
            return None
        try:
            v = float(t[i])
        except ValueError:
            return None
        return None if v <= -999 else v

    out = {}
    for line in lines[1:]:
        t = [x.strip() for x in line.split(";")]
        if len(t) < 3:
            continue
        try:
            d = datetime.strptime(t[col["MESS_DATUM"]], "%Y%m%d").date()
        except ValueError:
            continue
        out[d] = {"tn": val(t, "TNK"), "tx": val(t, "TXK"), "rsk": val(t, "RSK"), "rskf": val(t, "RSKF"),
                  "sdk": val(t, "SDK"), "shk": val(t, "SHK_TAG")}
    return out


def build_normals(days):
    """Normalwerte je Kalendertag aus 1991–2020: [tn, tx, tx_p05, tx_p95] (±WINDOW Tage)."""
    by_key = {}
    for d, v in days.items():
        if NORMAL_FROM <= d.year <= NORMAL_TO:
            by_key.setdefault(day_key(d), []).append(v)
    ref = date(2001, 1, 1)  # kein Schaltjahr: 365 Kalendertage im Kreis
    keys = [day_key(ref + timedelta(days=i)) for i in range(365)]
    normals = {}
    for i, k in enumerate(keys):
        tn, tx = [], []
        for j in range(-WINDOW, WINDOW + 1):
            kk = keys[(i + j) % 365]
            for v in by_key.get(kk, []) + (by_key.get("02-29", []) if kk == "02-28" else []):
                if v["tn"] is not None:
                    tn.append(v["tn"])
                if v["tx"] is not None:
                    tx.append(v["tx"])
        if len(tx) < MIN_VALUES or len(tn) < MIN_VALUES:
            continue
        tx.sort()
        normals[k] = [round(sum(tn) / len(tn), 2), round(sum(tx) / len(tx), 2),
                      round(percentile(tx, CARD_PCT), 2), round(percentile(tx, 100 - CARD_PCT), 2)]
    return normals


def build_tx_by_day(days):
    """{„11-24“: [[Jahr, Höchstwert], …]} – für „so mild zuletzt 2015“."""
    out = {}
    for d in sorted(days):
        tx = days[d]["tx"]
        if tx is not None:
            out.setdefault(day_key(d), []).append([d.year, tx])
    return out


# ---------------------------------------------------------------------------------------------------
# Laden und speichern
# ---------------------------------------------------------------------------------------------------
def _load_file(path):
    if _state["path"] == path and _state["data"] is not None:
        return _state["data"]
    data = {}
    try:
        with open(path) as f:
            data = json.load(f)
        if data.get("version") != STATE_VERSION:
            data = {}
    except (OSError, ValueError):
        data = {}
    _state.update(path=path, data=data)
    return data


def _save(path, data):
    data["version"] = STATE_VERSION
    tmp = path + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(data, f, separators=(",", ":"))
        os.replace(tmp, path)
    except OSError as exc:
        logger.warning("Klimadaten: Datei nicht geschrieben (%s)", exc)
    _state.update(path=path, data=data)


def _recent_days(data):
    """Gespeicherte Tageswerte der letzten Monate als {date: {…}}."""
    out = {}
    for k, v in (data.get("recent") or {}).get("days", {}).items():
        try:
            out[date.fromisoformat(k)] = dict(zip(("tn", "tx", "rsk", "rskf", "sdk", "shk"), v))
        except ValueError:
            continue
    return out


def ensure(lat, lon, now, path, session=None, height=None):
    """Klimadaten für den Wetter-Ort laden bzw. auffrischen. Gibt ein Klima-Objekt zurück oder None.

    Jeder Schritt kann scheitern, ohne die anderen zu verlieren: ohne historische Daten keine Kurve/Karte,
    aber Meilensteine aus den letzten Monaten; ohne aktuelle Daten nur Kurve/Karte."""
    status.use(STATUS_NAME)
    session = session or requests.Session()
    data = dict(_load_file(path))
    today = now.date()
    failed = None
    changed = False

    # 1. Station (bei erstem Start oder Ortswechsel)
    st = data.get("station")
    pos = data.get("pos")
    if not st or not pos or km(lat, lon, pos[0], pos[1]) > MOVE_KM:
        if not _blocked("station"):
            try:
                text = _get(session, STATIONS_URL).content.decode("latin-1")
                st = choose_station(parse_stations(text), lat, lon, today, height)
                data = {"station": st, "pos": [lat, lon]}
                changed = True
                if st:
                    logger.info("Klimadaten: Station %s (%d, %.1f km, %d m)", st["name"], st["id"], st["km"], st["hoehe"])
                else:
                    logger.info("Klimadaten: keine Station im Umkreis von %d km", MAX_KM)
            except Exception as exc:
                _retry["station"] = _time.monotonic()
                failed = exc
                st = None
        else:
            st = None
    if not st:
        if changed:
            _save(path, data)
        if failed:
            logger.warning("Klimadaten: Stationsliste nicht verfügbar: %s", failed)
            status.fail(STATUS_NAME, failed)
        elif not _blocked("station"):
            status.ok(STATUS_NAME)
        return None

    # 2. Normalwerte (einmal, dann jährlich)
    built = data.get("built")
    stale = not built or (today - date.fromisoformat(built)).days > REBUILD_DAYS
    waiting = False  # ein nötiger Schritt wartet nach einem Fehlschlag: Status so lassen, wie er ist
    if (stale or not data.get("normals")) and _blocked("hist"):
        waiting = True
    elif stale or not data.get("normals"):
        try:
            listing = _get(session, HIST_DIR_URL).text
            names = hist_names(listing, st["id"])
            if not names:
                raise RuntimeError(f"DWD: keine historischen Tageswerte für Station {st['id']}")
            days = {}
            for name in names:
                days.update(parse_product(_get(session, HIST_DIR_URL + name).content))
            data["normals"] = build_normals(days)
            data["tx_by_day"] = build_tx_by_day(days)
            data["first_year"] = min(days).year if days else None
            data["built"] = today.isoformat()
            changed = True
            logger.info("Klimadaten: Normalwerte aus %d Tageswerten (%s–%s), %d Kalendertage",
                        len(days), min(days), max(days), len(data["normals"]))
        except Exception as exc:
            _retry["hist"] = _time.monotonic()
            failed = exc

    # 3. Tageswerte der letzten Monate (sobald gestern dabei ist)
    rec = data.get("recent") or {}
    last = max(rec.get("days", {}) or [""])
    tried = rec.get("tried")
    yesterday = (today - timedelta(days=1)).isoformat()
    due = last < yesterday and (not tried or (now - datetime.fromisoformat(tried)).total_seconds()
                                > RECENT_RETRY_H * 3600)
    if due and _blocked("recent"):
        waiting = True
    elif due:
        try:
            days = parse_product(_get(session, RECENT_URL.format(id=st["id"])).content)
            keep = today - timedelta(days=600)
            data["recent"] = {"tried": now.isoformat(timespec="minutes"),
                              "days": {d.isoformat(): [v["tn"], v["tx"], v["rsk"], v["rskf"], v["sdk"], v["shk"]]
                                       for d, v in sorted(days.items()) if d >= keep}}
            changed = True
            logger.info("Klimadaten: Tageswerte bis %s", max(days) if days else "–")
        except Exception as exc:
            _retry["recent"] = _time.monotonic()
            data.setdefault("recent", {})["tried"] = now.isoformat(timespec="minutes")
            changed = True
            failed = exc
    if changed:
        _save(path, data)
    if failed:
        logger.warning("Klimadaten nicht verfügbar: %s", failed)
        status.fail(STATUS_NAME, failed)
    elif not waiting:
        status.ok(STATUS_NAME)
    return Klima(data)


def reset():
    """Zwischenspeicher leeren (Tests)."""
    _state.update(path=None, data=None)
    _retry.clear()


# ---------------------------------------------------------------------------------------------------
# Auswerten
# ---------------------------------------------------------------------------------------------------
def day_stats(records, d):
    """Tageswerte eines Tages aus Bright Sky (Messungen und Vorhersage) oder None, wenn Stunden fehlen."""
    hours = [r for r in records if r["dt"].date() == d and r.get("temperature") is not None]
    if len(hours) < 18:
        return None
    temps = [r["temperature"] for r in hours]
    snow = any((r.get("precipitation") or 0) > 0 and (r.get("icon") in ("snow", "sleet")
                                                     or r.get("condition") in ("snow", "sleet")) for r in hours)
    return {"tn": min(temps), "tx": max(temps), "rsk": sum(r.get("precipitation") or 0 for r in hours),
            "sdk": sum(r.get("sunshine") or 0 for r in hours) / 60, "snow": snow}


def night_min(records, start, end):
    vals = [r["temperature"] for r in records if start <= r["dt"] < end and r.get("temperature") is not None]
    return min(vals) if vals else None


class Klima:
    def __init__(self, data):
        self.station = data.get("station") or {}
        self.normals = data.get("normals") or {}
        self.tx_by_day = data.get("tx_by_day") or {}
        self.first_year = data.get("first_year")
        self.recent = _recent_days(data)

    # ---- Normalwerte ----
    def normal(self, d):
        """(tn, tx, p05, p95) für diesen Kalendertag oder None."""
        k = day_key(d)
        v = self.normals.get("02-28" if k == "02-29" else k)
        return tuple(v) if v else None

    def last_year_like(self, d, tx, warm):
        """Letztes Jahr vor d.year, in dem am selben Kalendertag der Höchstwert mindestens so hoch
        (warm) bzw. höchstens so niedrig war. None = so noch nie seit Beginn der Reihe."""
        k = day_key(d)
        years = {y: v for y, v in self.tx_by_day.get(k, [])}
        for dd, v in self.recent.items():  # die letzten Monate fehlen in den historischen Daten
            if day_key(dd) == k and v.get("tx") is not None:
                years[dd.year] = v["tx"]
        hits = [y for y, v in years.items() if y < d.year and ((v >= tx - 0.05) if warm else (v <= tx + 0.05))]
        return max(hits) if hits else None

    # ---- Reihe aus DWD-Tageswerten und Bright Sky ----
    def series(self, records, upto):
        """{date: Tageswerte} bis einschließlich upto: DWD, Lücken am Ende aus Bright Sky, upto immer aus
        Bright Sky (Vorhersage)."""
        out = {}
        for d, v in self.recent.items():
            if d < upto:
                snow = (v.get("rskf") in (7, 8) and (v.get("rsk") or 0) > 0) or (v.get("shk") or 0) > 0
                out[d] = {"tn": v.get("tn"), "tx": v.get("tx"), "rsk": v.get("rsk"), "sdk": v.get("sdk"), "snow": snow}
        d = upto - timedelta(days=3)
        while d <= upto:
            if d not in out or d == upto:
                s = day_stats(records, d)
                if s:
                    out[d] = s
            d += timedelta(days=1)
        return out


# ---- Kurve und Karte (Leons Wahl B + C) ----
def curve(k, records, d, rain_text):
    """Normalwerte für die Kurve und der Text für die Kopfzeile (nur statt „Kein Regen …“)."""
    n = k.normal(d) if k else None
    s = day_stats(records, d)
    if not n or not s:
        return None
    diff = round(s["tx"] - n[1])
    if diff == 0:
        text = "Tagsüber so warm wie üblich"
    else:
        text = f"Tagsüber {abs(diff)}° {'wärmer' if diff > 0 else 'kälter'} als üblich"
    head = text if rain_text.startswith("Kein Regen") else None
    return {"tn": n[0], "tx": n[1], "diff": diff, "head": head}


def card(k, records, d, today):
    """Karte bei Ausreißern oder None."""
    n = k.normal(d) if k else None
    s = day_stats(records, d)
    if not n or not s:
        return None
    tn_n, tx_n, p05, p95 = n
    tx = s["tx"]
    warm = tx >= p95 and tx - tx_n >= CARD_MIN_DIFF
    cold = tx <= p05 and tx_n - tx >= CARD_MIN_DIFF
    if not (warm or cold):
        return None
    # nach dem Wert, nicht nach dem Monat: 12° im November sind „mild“, 31° „warm“; 17° im Juli „kühl“
    word = ("mild" if tx < MILD_BELOW else "warm") if warm else ("kühl" if tx >= COOL_FROM else "kalt")
    year = k.last_year_like(d, tx, warm)
    since = f"so {word} zuletzt {year}" if year else (f"Rekord seit {k.first_year}" if k.first_year else "")
    diff = round(tx - tx_n)
    top = f"Ungewöhnlich {word}"
    if d != today:
        top = "Morgen u" + top[1:]
    return {"top": top, "sub": f"{num(tx)}° statt {num(tx_n)}°" + (f" · {since}" if since else ""),
            "badge": f"{'+' if diff > 0 else ''}{diff}°", "dir": "warm" if warm else "kalt",
            "log": f"Höchstwert {tx:.1f}° gegen üblich {tx_n:.1f}° (5 %: {p05:.1f}°, 95 %: {p95:.1f}°)"
                   + (f", zuletzt so {word} {year}" if year else ", Rekord")}


# ---- Meilensteine ----
FIRSTS = [  # Name, Bedingung, Farbe, Text, Kurztext
    ("schnee", lambda v: v.get("snow"), "kalt", "Erster Schnee seit {lang}", "Erster Schnee seit {kurz}"),
    ("eistag", lambda v: v.get("tx") is not None and v["tx"] < 0, "kalt", "Erster Eistag seit {lang}",
     "Erster Eistag seit {kurz}"),
    ("frost", lambda v: v.get("tn") is not None and v["tn"] < 0, "kalt", "Erster Frost seit {lang}",
     "Erster Frost seit {kurz}"),
    ("heiss", lambda v: v.get("tx") is not None and v["tx"] >= 30, "warm", "Erstmals 30° seit {lang}",
     "30° erstmals seit {kurz}"),
    ("sommertag", lambda v: v.get("tx") is not None and v["tx"] >= 25, "warm", "Erster Sommertag seit {lang}",
     "Erster Sommertag seit {kurz}"),
    ("tropennacht", lambda v: v.get("tn") is not None and v["tn"] >= 20, "warm", "Erste Tropennacht seit {lang}",
     "Tropennacht erstmals seit {kurz}"),
]
NIGHT_KINDS = ("frost", "tropennacht")


def _missing(series, start, end):
    n, d = 0, start
    while d < end:
        if d not in series:
            n += 1
        d += timedelta(days=1)
    return n


def _first(series, d, cond, value=None):
    """Letzter Tag vor d, an dem cond galt – wenn d die Bedingung erfüllt und es GAP_DAYS Tage nicht so war."""
    v = value if value is not None else series.get(d)
    if not v or not cond(v):
        return None
    earlier = [dd for dd, vv in series.items() if dd < d and vv and cond(vv)]
    last = max(earlier) if earlier else None
    start = min(series) if series else d
    if last is None:
        # nie in der Reihe: nur melden, wenn die Reihe weit genug zurückreicht
        if (d - start).days < 365 or _missing(series, start, d) > MAX_MISSING * 4:
            return None
        return "lang"
    if (d - last).days <= GAP_DAYS or _missing(series, last, d) > MAX_MISSING:
        return None
    return last


def _streak(series, d, cond):
    """Wie viele Tage bis einschließlich d hintereinander cond erfüllen (fehlender Tag beendet)."""
    n, dd = 0, d
    while dd in series and series[dd] and cond(series[dd]):
        n += 1
        dd -= timedelta(days=1)
    return n


def _year_max_streak(series, d, cond):
    """Längste Serie dieses Kalenderjahres, die vor der heutigen Serie endete."""
    best = run = 0
    dd = date(d.year, 1, 1)
    cur_start = d - timedelta(days=_streak(series, d, cond) - 1)
    while dd < cur_start:
        v = series.get(dd)
        run = run + 1 if v and cond(v) else 0
        best = max(best, run)
        dd += timedelta(days=1)
    return best


def milestone(k, records, d, night=None):
    """Meilenstein für Tag d → {kind, text, short, color} oder None. night=(start, ende) im Nachtbild:
    nur Frost und Tropennacht, und nur wenn die kommende Nacht die Bedingung erfüllt."""
    if not k:
        return None
    series = k.series(records, d)
    today = series.get(d)
    if not today:
        return None
    for kind, cond, color, lang, kurz in FIRSTS:
        if night and kind not in NIGHT_KINDS:
            continue
        val = today
        if kind == "tropennacht" and not night:
            # die kommende Nacht (18–8 Uhr) statt des Tiefstwerts von 0–24 Uhr
            tz = records[0]["dt"].tzinfo if records else None
            start = datetime.combine(d, datetime.min.time(), tz) + timedelta(hours=18)
            m = night_min(records, start, start + timedelta(hours=14))
            val = dict(today, tn=m) if m is not None else None
        if night:
            m = night_min(records, *night)
            if m is None:
                continue
            val = dict(today, tn=min(m, today["tn"]) if kind == "frost" else m)
            if not cond({"tn": m}):
                continue
        last = _first(series, d, cond, val)
        if last:
            if last == "lang":
                text = lang.split(" seit ")[0] + " seit über einem Jahr"
                return {"kind": kind, "text": text, "short": text.replace(" seit über einem Jahr", ""), "color": color}
            return {"kind": kind, "text": lang.format(lang=date_text(last)), "short": kurz.format(kurz=date_short(last)),
                    "color": color}
    if night:
        return None
    # Serien
    if (today.get("sdk") or 0) >= SUN_MIN_H:
        grey = _streak(series, d - timedelta(days=1), lambda v: v.get("sdk") is not None and v["sdk"] <= GREY_MAX_H)
        if grey >= GREY_MIN_DAYS:
            return {"kind": "sonne", "text": f"Erstmals Sonne seit {grey} Tagen", "short": f"Sonne nach {grey} Tagen",
                    "color": "sonne"}
    if d.timetuple().tm_yday >= SERIES_FROM_DOY:
        wet = lambda v: v.get("rsk") is not None and v["rsk"] >= WET_MM  # noqa: E731
        dry = lambda v: v.get("rsk") is not None and v["rsk"] < DRY_MM  # noqa: E731
        n = _streak(series, d, wet)
        if n >= WET_MIN_DAYS and n > _year_max_streak(series, d, wet):
            return {"kind": "regen", "text": f"Längste Regenserie {d.year}: {n} Tage",
                    "short": f"{n} Tage Regen", "color": "regen"}
        n = _streak(series, d, dry)
        if n >= DRY_MIN_DAYS and n > _year_max_streak(series, d, dry):
            return {"kind": "trocken", "text": f"Längste Trockenphase {d.year}: {n} Tage",
                    "short": f"{n} Tage trocken", "color": "sonne"}
    return None


# ---------------------------------------------------------------------------------------------------
# Symbole (48er- bzw. 32er-ViewBox, wie die übrigen Karten)
# ---------------------------------------------------------------------------------------------------
def thermo_svg(direction, cls="lw-svg"):
    """Thermometer mit großem Pfeil daneben: warm = rot bis oben, Pfeil hoch; kalt = blau, wenig gefüllt,
    Pfeil runter (Pfeil groß genug, dass er nach dem Einrasten mehr als ein Pünktchen ist)."""
    c = "#E3001B" if direction == "warm" else "#0082C9"
    level = 10 if direction == "warm" else 24
    arrow = "M27 21 L36.5 7 L46 21 Z" if direction == "warm" else "M27 9 L36.5 23 L46 9 Z"
    return (f'<svg class="{cls}" viewBox="0 0 48 48" aria-hidden="true">'
            '<path d="M10 31 V8 Q10 3 15 3 Q20 3 20 8 V31" fill="#fff" stroke="#000" stroke-width="2.8"/>'
            f'<rect x="12.6" y="{level}" width="4.8" height="{34 - level}" fill="{c}"/>'
            f'<circle cx="15" cy="37" r="8.5" fill="{c}" stroke="#000" stroke-width="2.8"/>'
            f'<path d="{arrow}" fill="{c}" stroke="#000" stroke-width="2.6" stroke-linejoin="round"/></svg>')


FLAG_COLORS = {"kalt": "#0082C9", "regen": "#0082C9", "warm": "#E3001B", "sonne": "#FFC400"}


def flag_svg(color, cls="ml-flag"):
    """Fahne an der Stange; bei Kälte mit Schneeflocke."""
    fill = FLAG_COLORS.get(color, "#0082C9")
    flake = ('<g stroke="#fff" stroke-width="2.6" stroke-linecap="round">'
             '<path d="M24 8.5 V20.5 M18.8 11.5 L29.2 17.5 M18.8 17.5 L29.2 11.5"/></g>') if color == "kalt" else ""
    return (f'<svg class="{cls}" viewBox="0 0 48 48" aria-hidden="true">'
            '<path d="M10 45 V4" stroke="#000" stroke-width="3.4" stroke-linecap="round"/>'
            f'<path d="M11.5 5 H40 L33 14.5 L40 24 H11.5 Z" fill="{fill}" stroke="#000" stroke-width="2.6" '
            'stroke-linejoin="round"/>'
            f'{flake}<path d="M4 45 H17" stroke="#000" stroke-width="3.4" stroke-linecap="round"/></svg>')
