"""
Morgendliche Schlagzeilen für Bonn, NRW und Bund aus RSS-Feeds.

Standardquellen (in den Einstellungen änderbar):
  Bonn  General-Anzeiger  https://ga.de/feed.rss       nur Artikel mit "/bonn/" im Link
  NRW   WDR               https://www1.wdr.de/uebersicht-100.feed
  Bund  tagesschau (ARD)  https://www.tagesschau.de/index~rss2.xml

RSS kennt keine "Wichtigkeit", nur eine Reihenfolge. Genommen werden deshalb die
ersten passenden Einträge in Feed-Reihenfolge, nach diesen Regeln:
  * höchstens MAX_AGE_H Stunden alt (wenn der Feed ein Datum mitliefert)
  * keine Liveblogs, Ticker, Podcasts, Videos
  * keine Dubletten: dasselbe Thema erscheint nur auf einer Ebene (Bonn vor NRW vor Bund)
  * Bonn: liefert der GA zu wenig, werden WDR-Meldungen mit "Bonn" ergänzt
Fällt ein Feed aus, fehlt nur diese Ebene. Abgerufene Feeds werden CACHE_MIN Minuten
zwischengespeichert, damit das Dashboard im 5-Minuten-Takt die Server nicht belastet.
"""

import html
import logging
import re
import time as _time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime

import requests

logger = logging.getLogger(__name__)

DEFAULT_FEEDS = {
    "bonn": ("Bonn", "GA", "https://ga.de/feed.rss"),
    "nrw": ("NRW", "WDR", "https://www1.wdr.de/uebersicht-100.feed"),
    "bund": ("Bund", "tagesschau", "https://www.tagesschau.de/index~rss2.xml"),
    "fr": ("France", "franceinfo", "https://www.francetvinfo.fr/titres.rss"),
}
PER_LEVEL = 3  # geladen; angezeigt werden quer bis zu 2, hochkant bis zu 3 (je nach Platz)
MAX_AGE_H = 24
CACHE_MIN = 15
TIMEOUT = 10
HEADERS = {"User-Agent": "InkyPi-Tagesdashboard/1.3 (privates E-Ink-Display)",
           "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.5"}

# Liveblogs, Ticker und Medienbeiträge ergeben als Schlagzeile keinen Sinn
SKIP_TITLE = re.compile(r"liveblog|live-blog|newsblog|ticker|\+\+|podcast|^video:|^audio:|^live:|im livestream",
                        re.IGNORECASE)
SKIP_LINK = re.compile(r"/(video|videos|audio|podcast|podcasts|livestream)s?/", re.IGNORECASE)
STOPWORDS = set("""aber alle als also auch auf aus bei beim bis das dass dem den der des die dies diese doch
durch ein eine einem einen einer eines für gegen hat haben ihre im in ins ist jetzt kann mehr mit nach nicht
noch nun oder sich sie sind so soll über um und uns unter vom von vor war was weil wie will wird wo zu zum zur""".split())

# Französische Feeds: Liveticker und Videos überspringen, Gattungsetiketten vorn abschneiden
SKIP_TITLE_FR = re.compile(r"^(en )?direct\b|^vid[ée]o\b|^podcast\b|^replay\b|^live\b|^carte\b|^grand format\b",
                           re.IGNORECASE)
LABEL_FR = re.compile(r"^(?:info franceinfo|enqu[êe]te|r[ée]cit|t[ée]moignages?|reportage|entretien|interview|"
                      r"d[ée]cryptage|analyse|tribune|chronique|portrait|vrai ou fake|infographie|exclusif)\s*[.:]\s+",
                      re.IGNORECASE)

_cache = {}  # url -> (zeitpunkt, liste)


def fr_typo(title):
    """Französische Typografie: vor : ; ? ! und in « » ein geschütztes Leerzeichen,
    damit das Satzzeichen nie allein am Zeilenanfang steht."""
    title = re.sub(r"\s+([:;?!»])", "\u00a0\\1", title)
    return re.sub(r"«\s+", "«\u00a0", title)


# ----------------------------------------------------------------------
# Zeitfenster
# ----------------------------------------------------------------------
def window_for(day, cfg):
    """(Beginn, Ende) als time für diesen Tag; Wochenende hat eigene Zeiten."""
    return cfg["weekend"] if day.weekday() >= 5 else cfg["weekday"]


def in_window(now, cfg):
    start, end = window_for(now.date(), cfg)
    t = now.time().replace(second=0, microsecond=0)
    return start <= t < end


def boundaries(now, cfg, days=2):
    """Alle Fensteranfänge und -enden der nächsten Tage (für den Bild-Cache)."""
    out = []
    for offset in range(days + 1):
        day = now.date() + timedelta(days=offset)
        for t in window_for(day, cfg):
            out.append(datetime.combine(day, t, tzinfo=now.tzinfo))
    return out


# ----------------------------------------------------------------------
# Feeds lesen
# ----------------------------------------------------------------------
def _text(el, *names):
    for n in names:
        child = el.find(n)
        if child is not None:
            if child.text and child.text.strip():
                return child.text.strip()
            if child.get("href"):
                return child.get("href").strip()
    return ""


def _clean(text):
    text = re.sub(r"<[^>]+>", " ", html.unescape(text or ""))
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _date(value):
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        pass
    try:  # Atom: 2026-11-11T06:10:00+01:00
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_feed(xml_bytes):
    """RSS 2.0 oder Atom -> Liste von dicts (title, link, summary, date), Reihenfolge wie im Feed."""
    root = ET.fromstring(xml_bytes)
    atom = "{http://www.w3.org/2005/Atom}"
    entries = root.findall("./channel/item") or root.findall(f"{atom}entry") or root.findall(".//item")
    out = []
    for e in entries:
        title = _clean(_text(e, "title", f"{atom}title"))
        if not title:
            continue
        out.append({
            "title": title,
            "link": _text(e, "link", f"{atom}link"),
            "summary": _clean(_text(e, "description", f"{atom}summary", f"{atom}content")),
            "date": _date(_text(e, "pubDate", f"{atom}updated", f"{atom}published",
                                "{http://purl.org/dc/elements/1.1/}date")),
        })
    return out


def fetch(url, session=None):
    hit = _cache.get(url)
    if hit and _time.monotonic() - hit[0] < CACHE_MIN * 60:
        return hit[1]
    session = session or requests.Session()
    r = session.get(url, headers=HEADERS, timeout=TIMEOUT)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    items = parse_feed(r.content)
    _cache[url] = (_time.monotonic(), items)
    return items


# ----------------------------------------------------------------------
# Auswahl
# ----------------------------------------------------------------------
def _words(title):
    return {w for w in re.findall(r"[a-zäöüß0-9]+", title.lower()) if len(w) >= 4 and w not in STOPWORDS}


def same_topic(a, b):
    """Grobe Dublettenprüfung über gemeinsame Wörter (Jaccard)."""
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return False
    return len(wa & wb) / len(wa | wb) >= 0.4


def usable(item, now, link_filter=""):
    if SKIP_TITLE.search(item["title"]) or SKIP_LINK.search(item["link"] or ""):
        return False
    if link_filter and link_filter not in (item["link"] or ""):
        return False
    date = item["date"]
    if date is not None:
        if date.tzinfo is None:  # Datum ohne Zeitzone: deutsche Ortszeit annehmen
            date = date.replace(tzinfo=now.tzinfo)
        if now - date > timedelta(hours=MAX_AGE_H):
            return False
    return True


def pick(candidates, chosen, now, n, link_filter="", must_contain=""):
    out = []
    for it in candidates:
        if len(out) >= n:
            break
        if not usable(it, now, link_filter):
            continue
        if must_contain and must_contain.lower() not in f"{it['title']} {it['summary']}".lower():
            continue
        if any(same_topic(it["title"], c) for c in chosen):
            continue
        out.append(it)
        chosen.append(it["title"])
    return out


def load(cfg, now, session=None):
    """Liefert [{"label", "source", "items": [{"title", "source"}]}] für die gefundenen Ebenen."""
    session = session or requests.Session()
    feeds = {}
    for key, (_, _, url) in cfg["feeds"].items():
        try:
            feeds[key] = fetch(url, session)
        except (requests.RequestException, RuntimeError, ET.ParseError) as exc:
            logger.warning("Nachrichten-Feed %s nicht verfügbar: %s", url, exc)
            feeds[key] = None

    # Auswahlreihenfolge Bonn, Bund, NRW: Ein bundesweites Thema bleibt bei der tagesschau,
    # auch wenn der WDR es mit NRW-Bezug ebenfalls bringt. Angezeigt wird Bonn, NRW, Bund.
    chosen, picked = [], {}
    for key in ("bonn", "bund", "nrw"):
        label, source, _ = cfg["feeds"][key]
        items = []
        if feeds.get(key):
            if key == "nrw":
                # Bonner Meldungen im WDR-Feed nur, wenn sonst nichts Landesweites da ist
                items = pick([it for it in feeds[key] if "bonn" not in it["title"].lower()], chosen, now, PER_LEVEL)
                items += pick(feeds[key], chosen, now, PER_LEVEL - len(items))
            else:
                items = pick(feeds[key], chosen, now, PER_LEVEL, cfg["bonn_filter"] if key == "bonn" else "")
            items = [dict(it, source=source) for it in items]
        if key == "bonn" and len(items) < PER_LEVEL and feeds.get("nrw"):
            # Ersatz: WDR-Meldungen, in denen Bonn vorkommt
            extra = pick(feeds["nrw"], chosen, now, PER_LEVEL - len(items), must_contain="Bonn")
            items += [dict(it, source=cfg["feeds"]["nrw"][1]) for it in extra]
        picked[key] = {"label": label, "items": items}
    out = [picked[k] for k in ("bonn", "nrw", "bund") if picked[k]["items"]]
    if "fr" in cfg["feeds"] and feeds.get("fr"):
        # Frankreich: eigene Dublettenprüfung (Wortvergleich geht nicht über Sprachgrenzen)
        label, source, _ = cfg["feeds"]["fr"]
        items = [dict(it, title=fr_typo(LABEL_FR.sub("", it["title"]))) for it in feeds["fr"]
                 if not SKIP_TITLE_FR.search(it["title"])]
        items = [dict(it, source=source) for it in pick(items, [], now, PER_LEVEL)]
        if items:
            out.append({"label": label, "items": items, "lang": "fr"})
    return out


# ----------------------------------------------------------------------
# Einstellungen
# ----------------------------------------------------------------------
def read_config(opt, flag, parse_hhmm):
    if not flag("newsEnabled"):
        return None
    wd = parse_hhmm(opt("newsFrom")), parse_hhmm(opt("newsTo"))
    we = parse_hhmm(opt("newsWeekendFrom")), parse_hhmm(opt("newsWeekendTo"))
    if None in wd or None in we:
        logger.warning("Nachrichten: Zeitfenster unvollständig")
        return None
    feeds = {}
    keys = [("bonn", "newsBonnUrl"), ("nrw", "newsNrwUrl"), ("bund", "newsBundUrl")]
    if flag("newsFrEnabled"):
        keys.append(("fr", "newsFrUrl"))
    for key, setting in keys:
        label, source, url = DEFAULT_FEEDS[key]
        custom = (opt(setting) or "").strip()
        if custom and custom != url:
            source = re.sub(r"^www\.", "", re.sub(r"^https?://([^/]+).*$", r"\1", custom))
        feeds[key] = (label, source, custom or url)
    return {"weekday": wd, "weekend": we, "feeds": feeds, "bonn_filter": (opt("newsBonnFilter") or "").strip()}
