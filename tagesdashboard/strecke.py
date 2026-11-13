"""
Streckenmeldungen aus der Fahrplanauskunft des VRR (EFA, „AddInfo“) – Vorwarnung für den Pendelzug.

Warum zusätzlich zu IRIS (bahn.py): IRIS hängt Meldungen an die einzelne Fahrt. Solange der Zug
noch gar nicht losgefahren ist (die RE 5 um 8:04 startet erst gegen 7 Uhr in Koblenz), steht dort
„pünktlich“, auch wenn zwischen Köln und Düsseldorf schon seit 6:40 ein Signal gestört ist. Die
Verbundauskunft kennt solche Streckenstörungen sofort („Strecke zw. A und B beeinträchtigt“).

Abruf: XML_ADDINFO_REQUEST, rapidJSON, nur aktuelle Meldungen. Antwort {"infos": {"current": [...]}},
je Meldung: id, type, priority, timestamps (creation, validity[{from, to}] in UTC),
infoLinks[0] (title, subtitle, content als HTML), properties.providerCode, affected.lines
[{id, number, name, operator, destination}]. Zugmeldungen haben keine affected.stops – die Orte
stehen nur im Text. Ganz NRW, etwa 1100 Meldungen und 4 MB; deshalb 10 Minuten im Speicher.

Filter (geprüft an echten Daten vom 13.11.2026):
  * Linie: Die Meldung nennt die eingestellte Linie (Nummer „RE5“). Dieselbe Nummer gibt es auch
    anderswo (RE 5 in Hessen, in Hamburg) – die fallen über den Ort heraus.
  * Ort: Die Meldung muss einen Bahnhof oder eine Stadt auf dem Weg des Zuges bis zum Ausstieg
    nennen (Laufweg aus IRIS: Halte vor Bonn, Bonn, Halte bis Düsseldorf). Bahnhöfe hinter dem
    Ausstieg (Duisburg, Oberhausen …) zählen nicht. Steht ein Ort im Titel, entscheidet der Titel.
  * Quelle: nicht „DBProd“ – die Meldungen der Bahn selbst zeigt der Störungsmonitor schon aus IRIS.
  * Zeit: gültig zwischen jetzt und der Ankunft am Ausstieg. „… beendet“ nur eine Stunde lang.

Anzeige: immer gelb („Vorwarnung“) – rot wird es erst, wenn IRIS den Zug selbst betroffen meldet.

Datenquelle: VRR Open Service (opendata-oepnv.de), Nutzung für private/Test-Zwecke ohne Anmeldung.
Der Open Service ist eine Testkopie; Ausfälle oder unplausible Antworten sind möglich. Fehler
führen nur zu einer Logzeile, die Zugkarte erscheint wie bisher.
"""

import html
import logging
import re
import time as _time
from datetime import datetime, timedelta, timezone

import requests

logger = logging.getLogger(__name__)

URL = "https://openservice-test.vrr.de/static03/XML_ADDINFO_REQUEST"
PARAMS = {"outputFormat": "rapidJSON", "filterPublicationStatus": "current"}
HEADERS = {"User-Agent": "InkyPi-Tagesdashboard/1.13 (privates E-Ink-Display; github.com/leonschwarze/InkyPi_Dashboard)"}
TIMEOUT = 20
CACHE_SECONDS = 600          # Liste 10 Minuten halten (auch Fehlschläge, damit nicht jede Runde 20 s wartet)
DONE_MINUTES = 60            # „Störung beendet“ so lange nach dem Eintragen zeigen
SKIP_PROVIDERS = {"DBProd"}  # kennt der Störungsmonitor schon aus IRIS
MAX_TEXT = 140
NB = "\u00a0"                # geschütztes Leerzeichen: „seit 6:40“ und „bis 4.12.“ nie trennen

_cache = {}                  # Linienschlüssel -> (Zeitpunkt, Liste oder None)

_LETTER = "A-Za-zÄÖÜäöüß"


# ----------------------------------------------------------------------
# Abruf
# ----------------------------------------------------------------------
def line_key(cat, num):
    """("RE", "5") -> "RE5" – so steht die Nummer in der VRR-Auskunft."""
    return f"{cat}{num}".upper().replace(" ", "")


def _utc(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def slim(info):
    """Nur das, was die Auswertung braucht (die volle Liste ist mehrere MB groß)."""
    link = (info.get("infoLinks") or [{}])[0]
    ts = info.get("timestamps") or {}
    return {
        "id": info.get("id", ""),
        "provider": (info.get("properties") or {}).get("providerCode", ""),
        "title": link.get("title") or link.get("subtitle") or "",
        "text": link.get("content") or "",
        "created": _utc(ts.get("creation")),
        "validity": [(_utc(v.get("from")), _utc(v.get("to"))) for v in ts.get("validity") or []],
        "lines": sorted({(ln.get("number") or "").replace(" ", "").upper()
                         for ln in (info.get("affected") or {}).get("lines") or []}),
    }


def select(data, key):
    """Aus der Antwort der Auskunft die Meldungen, die die Linie nennen (ohne Bahn-eigene)."""
    out = []
    for info in ((data or {}).get("infos") or {}).get("current") or []:
        if not isinstance(info, dict):
            continue
        m = slim(info)
        if key in m["lines"] and m["provider"] not in SKIP_PROVIDERS:
            out.append(m)
    return out


def fetch(session, key):
    """Meldungen zur Linie, 10 Minuten zwischengespeichert. None, wenn die Auskunft nicht antwortet."""
    hit = _cache.get(key)
    if hit and _time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    result = None
    try:
        r = session.get(URL, params=PARAMS, headers=HEADERS, timeout=TIMEOUT)
        if r.status_code == 200:
            result = select(r.json(), key)
            logger.info("Strecke: %d Meldungen zur %s aus der VRR-Auskunft (%d kB)",
                        len(result), key, len(r.content) // 1024)
        else:
            logger.warning("Strecke: VRR-Auskunft antwortet mit HTTP %s", r.status_code)
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Strecke: VRR-Auskunft nicht erreichbar (%s)", type(exc).__name__)
    _cache[key] = (_time.monotonic(), result)
    return result


# ----------------------------------------------------------------------
# Orte: liegt die Meldung auf dem Weg des Zuges?
# ----------------------------------------------------------------------
def norm(text):
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    text = text.replace("Hauptbahnhof", "Hbf")
    return re.sub(r"\s+", " ", text).strip()


def city(name):
    """ "Bonn-Bad Godesberg" -> "Bonn", "Köln Messe/Deutz" -> "Köln"."""
    return re.split(r"[ \-(/]", name.strip(), maxsplit=1)[0]


def _pattern(name):
    return re.compile(rf"(?<![{_LETTER}]){re.escape(name)}(?![{_LETTER}])")


def places(text, route, target_index):
    """Welche Orte nennt `text`? -> (Treffer-Indizes im Laufweg, Städte auf dem Abschnitt) oder None,
    wenn gar kein bekannter Ort vorkommt. Bahnhöfe werden zuerst gesucht (längste Namen zuerst,
    damit „Düsseldorf Flughafen“ nicht als „Düsseldorf“ zählt) und aus dem Text entfernt; im Rest
    zählen die Städte des Abschnitts bis zum Ausstieg (z. B. „Köln-Mülheim“ -> Köln)."""
    hits, rest = set(), text
    for i, name in sorted(enumerate(route), key=lambda x: -len(x[1])):
        pat = _pattern(norm(name))
        if pat.search(rest):
            hits.add(i)
            rest = pat.sub(" ", rest)
    section = {city(n) for n in route[:target_index + 1]}
    cities = {c for c in section if _pattern(c).search(rest)}
    return (hits, cities) if hits or cities else None


def on_route(msg, route, target_index):
    """Betrifft die Meldung den Abschnitt bis zum Ausstieg? `route` = Laufweg des Zuges (Halte vor
    dem Einstieg, Einstieg, Halte danach), `target_index` = Position des Ausstiegs darin."""
    title, body = norm(msg["title"]), norm(msg["text"])
    found = places(title, route, target_index) or places(f"{title} {body}", route, target_index)
    if not found:
        return False
    hits, cities = found
    if any(i < target_index for i in hits):
        return True                                   # ein Bahnhof vor dem Ausstieg
    beyond = any(i > target_index for i in hits)
    if target_index in hits and not beyond:
        return True                                   # nur der Ausstieg selbst („Region Düsseldorf Hbf“)
    target_city = city(route[target_index])
    # sonst über die Stadt; hinter dem Ausstieg zählt dessen eigene Stadt nicht (Düsseldorf-Derendorf …)
    return any(not (beyond and c == target_city) for c in cities)


# ----------------------------------------------------------------------
# Zeit und Text
# ----------------------------------------------------------------------
def active_window(msg, now, until):
    """Gültigkeitsabschnitt, der [now, until] berührt, oder None."""
    for start, end in msg["validity"] or [(None, None)]:
        if (start is None or start <= until) and (end is None or end >= now):
            return start, end
    return None


def short(name):
    return re.sub(r"\s+Hbf\b", "", name or "").strip()


def hm(dt):
    return f"{dt.hour}:{dt.minute:02d}"


def _clip(text):
    if len(text) > MAX_TEXT:
        text = text[:MAX_TEXT].rsplit(" ", 1)[0].rstrip(",;:–- ") + " …"
    return text


ACUTE = re.compile(r"^(?:Strecke zw\. (?P<a>.+?) und (?P<b>.+?)|Region (?P<r>.+?))\s+(?:aktuell\s+)?"
                   r"(?P<state>beeinträchtigt|gesperrt|nicht befahrbar)(?:\s+-\s+(?P<why>.+))?$")
# andere Titel, die nach Störung klingen („Beeinträchtigungen auf der Linie RE 18 - …“)
TROUBLE = re.compile(r"beeinträchtig|Störung|gestört|gesperrt|Sperrung|nicht befahrbar", re.I)
# Hinweise ohne Folgen für die Fahrzeit und Ankündigungen, die noch nicht gelten
SKIP_TITLE = re.compile(r"^(Vorankündigung|Bitte beachten|Keine/Eingeschränkte Nutzung|Achtung: Haltestelle)", re.I)
# „Reparatur am Signal zw. Köln Hbf und Köln Messe/Deutz beendet“, „Reparatur an der Oberleitung in der Region X beendet“
DONE = re.compile(r"^(?:Reparatur (?:am|an der|an dem|an einem|an einer|an den|an mehreren)\s+)?(?P<what>.+?)"
                  r"(?:\s+zw\. (?P<a>.+?) und (?P<b>.+?)|\s+(?:in der Region|bei|in) (?P<r>.+?))?\s+beendet\.?$")
SPAN = re.compile(r"zu (?P<what>[^.]+?) zwischen (?P<a>[^.]+?) und (?P<b>[^.(]+?)\s*\.")


def describe(msg, now, tz, window):
    """Meldung -> (Text, Art) für die Zugkarte. Art: "acute" (Störung jetzt), "done" (behoben),
    "build" (Baustelle). None, wenn nichts Sinnvolles daraus wird."""
    title, body = norm(msg["title"]), norm(msg["text"])
    if SKIP_TITLE.match(title):
        return None
    start = window[0] if window and window[0] and window[0] <= now else msg["created"]

    m = ACUTE.match(title)
    if m:
        where = f"{short(m['a'])}–{short(m['b'])}" if m["a"] else f"bei {short(m['r'])}"
        why = m["why"]
        if not why:
            g = re.search(r"Grund: ([^.]+)\.", body)
            why = g.group(1) if g else ""
        head = f"Strecke {where}" + (" gesperrt" if m["state"] != "beeinträchtigt" else "")
        text = f"{head}: {why}" if why else head + ("" if m["state"] == "gesperrt" else " gestört")
        if start:
            text += f"{NB}·{NB}seit{NB}{hm(start.astimezone(tz))}"
        return _clip(text), "acute"

    if TROUBLE.search(title) and not re.search(r"\bbeendet\b", title):
        text = re.sub(r"\s+-\s+", ": ", title, count=1)
        if start:
            text += f"{NB}·{NB}seit{NB}{hm(start.astimezone(tz))}"
        return _clip(text), "acute"

    if re.search(r"\bbeendet\b", title):
        if not msg["created"] or now - msg["created"] > timedelta(minutes=DONE_MINUTES):
            return None
        d = DONE.match(title)
        if d:
            thing = d["what"][:1].upper() + d["what"][1:]
            where = (f" {short(d['a'])}–{short(d['b'])}" if d["a"] else f" bei {short(d['r'])}" if d["r"] else "")
            return _clip(f"Behoben: {thing}{where}{NB}·{NB}Verspätungen möglich"), "done"
        return _clip(f"{title}{NB}·{NB}Verspätungen möglich"), "done"

    end = window[1] if window else None
    until = f"{NB}bis{NB}{end.astimezone(tz).day}.{end.astimezone(tz).month}." if end and end - now < timedelta(days=60) else ""
    s = SPAN.search(body)
    if s:
        what = re.sub(r"ausfällen\b", "ausfälle", s["what"])          # „zu Teilausfällen“ -> „Teilausfälle“
        b = re.sub(r"\s+(bzw|sowie)\b.*$", "", s["b"])                 # „… und Höxter-Ottbergen bzw. …“
        return _clip(f"Baustelle {short(s['a'])}–{short(b)}: {what}{until}"), "build"
    if title and not re.match(r"^(Maßnahmen und Fahrpläne|Information|Hinweis)\b", title):
        return _clip(f"{title}{until}"), "build"
    if body:
        return _clip(body), "build"
    return None


# ----------------------------------------------------------------------
# Zusammenführen
# ----------------------------------------------------------------------
def route_of(plan, station, target):
    """Laufweg des Zuges bis hinter den Ausstieg und Position des Ausstiegs darin (oder None)."""
    route = list(plan.get("before") or []) + [station] + list(plan.get("path") or [])
    want = short(target).lower()
    for i, name in enumerate(route):
        if i > len(plan.get("before") or []) and short(name).lower() == want:
            return route, i
    return None


def alerts(msgs, route, target_index, now, until, tz):
    """Meldungen der Auskunft -> Hinweise [{text, level, kind}] für die Zugkarte."""
    out, seen = [], set()
    for msg in msgs or []:
        window = active_window(msg, now, until)
        if not window or not on_route(msg, route, target_index):
            continue
        res = describe(msg, now, tz, window)
        if res and res[0].lower() not in seen:
            seen.add(res[0].lower())
            out.append({"text": res[0], "level": "info", "kind": res[1]})
    order = {"acute": 0, "done": 1, "build": 2}
    return sorted(out, key=lambda a: order[a["kind"]])


def load(cfg, plan, now, until, tz, session=None):
    """Hinweise zur Strecke für die Zugkarte. Wirft keine Fehler (leere Liste)."""
    try:
        target = cfg.get("target") or ""
        found = route_of(plan, cfg["station"], target) if target else None
        if not found:
            logger.info("Strecke: Ausstieg %r nicht im Laufweg – keine Streckenmeldungen", target)
            return []
        msgs = fetch(session or requests.Session(), line_key(cfg["cat"], cfg["num"]))
        return alerts(msgs, found[0], found[1], now.astimezone(timezone.utc), until.astimezone(timezone.utc), tz)
    except Exception:  # Vorwarnung ist ein Zusatz: nie die Zugkarte gefährden
        logger.exception("Strecke: Auswertung fehlgeschlagen")
        return []
