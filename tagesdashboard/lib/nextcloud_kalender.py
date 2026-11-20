"""
Nextcloud Kalender – InkyPi-Plugin

Liest Termine per CalDAV direkt aus Nextcloud (auch private Kalender, mit
App-Passwort) und zeigt sie auf Deutsch als Terminliste oder Wochenansicht an.

Ablauf (RFC 4791 / RFC 6764):
  1. PROPFIND auf /remote.php/dav/            -> current-user-principal
  2. PROPFIND auf den Principal               -> calendar-home-set und calendar-user-address-set
                                                 (eigene Adressen, RFC 6638)
  3. PROPFIND (Depth 1) auf das Kalender-Home -> alle Kalender mit Name und Farbe
  4. REPORT calendar-query je Kalender         -> Termine im Zeitraum
  5. Serientermine löst recurring_ical_events auf (ist bei InkyPi schon installiert)
  6. Abgesagte Termine (STATUS:CANCELLED) und Einladungen, die man selbst abgelehnt hat
     (eigener ATTENDEE mit PARTSTAT=DECLINED), fallen weg
"""

import calendar as pycal
import ipaddress
import json
import logging
import os
import re
import socket
import xml.etree.ElementTree as ET
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import urljoin, unquote, urlsplit
from zoneinfo import ZoneInfo

import icalendar
import recurring_ical_events
import requests

from plugins.base_plugin.base_plugin import BasePlugin

try:  # Schärfere Darstellung auf Inky-Displays (Kopie von shared/eink.py)
    from . import eink
except ImportError:  # pragma: no cover
    eink = None

try:  # Seite immer als UTF-8 rendern (Kopie von shared/zeichensatz.py)
    from . import zeichensatz
except ImportError:  # pragma: no cover
    zeichensatz = None

logger = logging.getLogger(__name__)

NS = {
    "d": "DAV:",
    "c": "urn:ietf:params:xml:ns:caldav",
    "a": "http://apple.com/ns/ical/",
    "cs": "http://calendarserver.org/ns/",
}
HTTP_TIMEOUT = 25
USER_AGENT = "InkyPi-Nextcloud-Kalender/1.0"
DEFAULT_PASSWORD_KEY = "NEXTCLOUD_APP_PASSWORD"

WOCHENTAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
WOCHENTAGE_KURZ = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
          "August", "September", "Oktober", "November", "Dezember"]

DEFAULTS = {
    "layout": "agenda",
    "days": "14",
    "weekStart": "today",
    "verifySSL": "true",
    "showPast": "false",
    "showLocation": "true",
    "useColors": "true",
    "showMonth": "true",
    "showEmptyToday": "true",
    "showFooter": "true",
    "einkSnap": "true",
}

# Format der gespeicherten Einstellungen (verstecktes Feld cfgVersion in settings.html).
# 0 = ohne cfgVersion (fehlender Schlüssel = Standard), 1 = aktuell. Seit 1.10 neu gegliederte
# Einstellungsseite, aber dieselben Schlüssel – deshalb keine Migration nötig.
CFG_VERSION = 1
# Ab welcher cfgVersion es eine Checkbox gibt (Gegenstück in settings.html: data-since). Bisher keine.
SINCE_VERSION = {}


def cfg_version(settings):
    raw = settings.get("cfgVersion")
    if raw is None:
        return 0
    try:
        return max(int(str(raw).strip()), 1)
    except ValueError:
        return 1


# --------------------------------------------------------------------------
# CalDAV-Client
# --------------------------------------------------------------------------

def dav_root(url):
    """Nextcloud-Adresse in die CalDAV-Wurzel umwandeln.

    Akzeptiert z. B. 'cloud.example.de', 'https://example.de/nextcloud' oder eine
    aus Nextcloud kopierte Kalenderadresse '.../remote.php/dav/calendars/leon/personal/'.
    """
    url = (url or "").strip()
    if not url:
        raise RuntimeError("Bitte die Adresse der Nextcloud angeben.")
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    idx = url.find("/remote.php/dav")
    if idx >= 0:
        return url[:idx] + "/remote.php/dav/"
    return url.rstrip("/") + "/remote.php/dav/"


# --------------------------------------------------------------------------
# Schutz des App-Passworts (seit 1.33)
# --------------------------------------------------------------------------
# Adresse und Schlüsselname stehen in den Plugin-Einstellungen, das Passwort in der .env.
# Damit das Passwort nur bei der eigenen Nextcloud ankommt, gelten drei Regeln:
#   1. Nur Schlüssel, die nach Nextcloud heißen (NEXTCLOUD_… oder NC_…).
#   2. Unverschlüsselt (http) oder ohne Zertifikatsprüfung nur zu Servern im Heimnetz.
#   3. Ein Schlüssel gehört zu genau einer Nextcloud: beim ersten erfolgreichen Abruf gemerkt
#      (Datei neben InkyPis device.json). Ist noch nichts gemerkt, nur eine Adresse, die in
#      einer gespeicherten Instanz steht.
KEY_RE = re.compile(r"^(NEXTCLOUD|NC)_[A-Z0-9_]{1,40}$")
PIN_FILE = "nextcloud_pin.json"


def checked_key(name):
    """Name des Schlüssels für das App-Passwort, nur NEXTCLOUD_… oder NC_… (sonst RuntimeError)."""
    name = (name or DEFAULT_PASSWORD_KEY).strip()
    if not KEY_RE.match(name):
        raise RuntimeError(f"Der Name des Schlüssels („{name[:40]}“) muss mit NEXTCLOUD_ oder NC_ beginnen "
                           "(Großbuchstaben, z. B. NEXTCLOUD_APP_PASSWORD).")
    return name


def is_home(host):
    """Liegt der Server im Heimnetz? Ja, wenn alle Adressen privat, Loopback oder link-local sind
    (192.168.…, 10.…, fd…, nextcloud.local, fritz.box …). Unbekannte Namen gelten als fremd."""
    host = (host or "").strip("[]").lower()
    if not host:
        return False
    if host == "localhost":
        return True
    try:
        ips = {ipaddress.ip_address(host)}
    except ValueError:
        try:
            ips = {ipaddress.ip_address(info[4][0].split("%")[0]) for info in socket.getaddrinfo(host, None)}
        except (OSError, ValueError):
            return False
    return bool(ips) and all(ip.is_private or ip.is_loopback or ip.is_link_local for ip in ips)


def origin_of(root):
    """'https://host:port' der CalDAV-Wurzel. http nur für Server im Heimnetz."""
    parts = urlsplit(root)
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https") or not host:
        raise RuntimeError("Die Nextcloud-Adresse ist ungültig.")
    if parts.scheme == "http" and not is_home(host):
        raise RuntimeError("Nextcloud außerhalb des Heimnetzes bitte mit https:// angeben – "
                           "sonst ginge das App-Passwort unverschlüsselt durchs Internet.")
    return f"{parts.scheme}://{host}:{parts.port or (443 if parts.scheme == 'https' else 80)}"


def tls_verify(root, wanted):
    """Zertifikatsprüfung abschalten geht nur bei Servern im Heimnetz (selbst signiert)."""
    if wanted:
        return True
    host = urlsplit(root).hostname or ""
    if is_home(host):
        return False
    logger.warning("Kalender: %s liegt nicht im Heimnetz – Zertifikat wird trotz Einstellung geprüft", host)
    return True


class OriginPin:
    """Merkt sich, zu welcher Nextcloud ein Schlüssel gehört, und schickt das Passwort nur dorthin."""

    def __init__(self, device_config, key):
        cfg = getattr(device_config, "config_file", None)
        self.path = os.path.join(os.path.dirname(cfg), PIN_FILE) if isinstance(cfg, str) and cfg else None
        self.key = key
        self.pins = {}
        if self.path and os.path.exists(self.path):
            try:
                with open(self.path, encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, ValueError):
                data = None
            if not isinstance(data, dict):
                raise RuntimeError(f"{self.path} ist beschädigt – App-Passwort wird nicht gesendet "
                                   "(Datei auf dem Pi löschen, dann wird neu gemerkt).")
            self.pins = data

    def check(self, origin):
        known = self.pins.get(self.key)
        if known and known != origin:
            logger.warning("Kalender: %s gehört zu %s, die Einstellungen nennen %s – App-Passwort nicht gesendet",
                           self.key, known, origin)
            raise RuntimeError(f"Die Nextcloud-Adresse weicht von {known} ab – App-Passwort wird nicht gesendet. "
                               f"Absichtlich umgezogen? Auf dem Pi {self.path} löschen.")

    def commit(self, origin):
        if not self.path or self.pins.get(self.key) == origin:
            return
        self.pins[self.key] = origin
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.pins, f, indent=1)
            os.replace(tmp, self.path)  # nie eine halb geschriebene Datei
            logger.info("Kalender: %s an %s gebunden (%s)", self.key, origin, self.path)
        except OSError as exc:
            logger.warning("Kalender: Bindung an %s nicht gespeichert: %s", origin, exc)


CALENDAR_PLUGINS = ("tagesdashboard", "nextcloud_kalender")


def saved_origins(device_config):
    """Nextcloud-Adressen aus den gespeicherten Instanzen beider Plugins (InkyPis Playlists)."""
    try:
        get_pm = getattr(device_config, "get_playlist_manager", None)
        data = get_pm().to_dict() if get_pm else device_config.get_config("playlist_config", {})
        found = set()
        for playlist in (data or {}).get("playlists") or []:
            for inst in playlist.get("plugins") or []:
                url = ((inst.get("plugin_settings") or {}).get("nextcloudUrl") or "").strip()
                if inst.get("plugin_id") in CALENDAR_PLUGINS and url:
                    try:
                        found.add(origin_of(dav_root(url)))
                    except RuntimeError:
                        pass
        return found
    except Exception as exc:  # Aufbau von InkyPi geändert: lieber nichts senden als raten
        logger.warning("Kalender: gespeicherte Instanzen nicht lesbar: %s", exc)
        return set()


def open_client(settings, device_config, user, verify_wanted):
    """CalDavClient nur nach den drei Regeln oben. Gibt (client, confirm) zurück;
    confirm() nach dem ersten erfolgreichen Abruf aufrufen (merkt die Nextcloud)."""
    key = checked_key(settings.get("passwordKey"))
    root = dav_root(settings.get("nextcloudUrl"))
    origin = origin_of(root)
    pin = OriginPin(device_config, key)
    pin.check(origin)  # abweichende Adresse → Passwort gar nicht erst lesen
    if pin.path and not pin.pins.get(key) and origin not in saved_origins(device_config):
        logger.warning("Kalender: %s steht in keiner gespeicherten Instanz – App-Passwort nicht gesendet", origin)
        raise RuntimeError("Neue Nextcloud-Adresse: bitte die Einstellungen erst speichern, dann aktualisieren.")
    password = device_config.load_env_key(key)
    if not password:
        raise RuntimeError(f"App-Passwort fehlt: Unter „API Keys“ den Schlüssel {key} anlegen.")
    client = CalDavClient(root, user, password, verify=tls_verify(root, verify_wanted))
    return client, (lambda: pin.commit(origin))


class CalDavClient:
    def __init__(self, root, user, password, verify=True):
        self.root = root
        self.user = user
        self.own_addresses = set()  # füllt calendars(); siehe _principal()
        self.session = requests.Session()
        self.session.auth = (user, password)
        self.session.verify = verify
        self.session.headers.update({"User-Agent": USER_AGENT})

    def _request(self, method, url, body, depth):
        try:
            resp = self.session.request(
                method, url, data=body.encode("utf-8"), timeout=HTTP_TIMEOUT,
                headers={"Depth": str(depth), "Content-Type": "application/xml; charset=utf-8"},
            )
        except requests.exceptions.SSLError as exc:
            raise RuntimeError("SSL-Fehler – Zertifikat der Nextcloud prüfen (eigener Server im Heimnetz "
                               "mit selbst signiertem Zertifikat: unter „Erweitert“ die Prüfung abschalten).") from exc
        except requests.exceptions.RequestException as exc:
            raise RuntimeError(f"Nextcloud nicht erreichbar: {exc.__class__.__name__}") from exc

        if resp.status_code == 401:
            raise RuntimeError("Anmeldung fehlgeschlagen – Benutzername oder App-Passwort prüfen.")
        if resp.status_code == 404:
            raise RuntimeError(f"CalDAV-Adresse nicht gefunden ({url}).")
        if resp.status_code not in (200, 207):
            logger.error("CalDAV %s %s -> %s: %s", method, url, resp.status_code, resp.text[:300])
            raise RuntimeError(f"Nextcloud antwortete mit HTTP {resp.status_code}.")
        try:
            return ET.fromstring(resp.content)
        except ET.ParseError as exc:
            raise RuntimeError("Unerwartete Antwort – ist das wirklich eine Nextcloud-Adresse?") from exc

    @staticmethod
    def _ok_props(response):
        """Alle <prop>-Elemente einer <response>, deren Status 200 ist."""
        props = []
        for ps in response.findall("d:propstat", NS):
            status = ps.findtext("d:status", default="", namespaces=NS)
            if " 200 " in status or status.endswith(" 200"):
                prop = ps.find("d:prop", NS)
                if prop is not None:
                    props.append(prop)
        return props

    def _find_href(self, url, prop_xml, path):
        body = (f'<?xml version="1.0" encoding="utf-8"?>'
                f'<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
                f'<d:prop>{prop_xml}</d:prop></d:propfind>')
        tree = self._request("PROPFIND", url, body, 0)
        for resp in tree.findall("d:response", NS):
            for prop in self._ok_props(resp):
                href = prop.findtext(path, namespaces=NS)
                if href:
                    return urljoin(url, href.strip())
        return None

    def _principal(self, principal):
        """Kalender-Home und eigene Adressen des Principals – beides mit einer Anfrage.

        Nextcloud nennt unter calendar-user-address-set die E-Mail-Adresse des Kontos
        (mailto:…) und die Principal-Adresse. Genau so steht man selbst als ATTENDEE in
        Einladungen; daran erkennt parse_events eigene Absagen.
        """
        body = ('<?xml version="1.0" encoding="utf-8"?>'
                '<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
                '<d:prop><c:calendar-home-set/><c:calendar-user-address-set/></d:prop></d:propfind>')
        tree = self._request("PROPFIND", principal, body, 0)
        home, addresses = None, set()
        for resp in tree.findall("d:response", NS):
            for prop in self._ok_props(resp):
                href = prop.findtext("c:calendar-home-set/d:href", namespaces=NS)
                if href and not home:
                    home = urljoin(principal, href.strip())
                for el in prop.findall("c:calendar-user-address-set/d:href", NS):
                    if el.text and el.text.strip():
                        addresses.add(address_key(el.text, principal))
        return home, addresses

    def calendars(self):
        principal = self._find_href(self.root, "<d:current-user-principal/>", "d:current-user-principal/d:href")
        if not principal:
            principal = urljoin(self.root, f"principals/users/{self.user}/")
        home, self.own_addresses = self._principal(principal)
        if not self.own_addresses:
            logger.info("Kalender: Nextcloud nennt keine eigene Adresse – abgelehnte Einladungen "
                        "lassen sich nicht erkennen (E-Mail-Adresse im Nextcloud-Konto eingetragen?)")
        if not home:
            home = urljoin(self.root, f"calendars/{self.user}/")

        body = ('<?xml version="1.0" encoding="utf-8"?>'
                '<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav" '
                'xmlns:a="http://apple.com/ns/ical/" xmlns:cs="http://calendarserver.org/ns/">'
                '<d:prop><d:resourcetype/><d:displayname/><a:calendar-color/>'
                '<c:supported-calendar-component-set/></d:prop></d:propfind>')
        tree = self._request("PROPFIND", home, body, 1)

        result = []
        for resp in tree.findall("d:response", NS):
            href = resp.findtext("d:href", namespaces=NS)
            for prop in self._ok_props(resp):
                rtype = prop.find("d:resourcetype", NS)
                if rtype is None or rtype.find("c:calendar", NS) is None:
                    continue
                comps = prop.find("c:supported-calendar-component-set", NS)
                if comps is not None and len(comps):
                    names = {c.get("name") for c in comps.findall("c:comp", NS)}
                    if "VEVENT" not in names:
                        continue  # reine Aufgabenlisten (VTODO) überspringen
                url = urljoin(home, href)
                name = (prop.findtext("d:displayname", namespaces=NS) or "").strip()
                if not name:
                    name = unquote(url.rstrip("/").rsplit("/", 1)[-1])
                color = (prop.findtext("a:calendar-color", namespaces=NS) or "").strip()
                if re.match(r"^#[0-9a-fA-F]{6}", color):
                    color = color[:7]
                else:
                    color = "#000000"
                result.append({"url": url, "name": name, "color": color})
                break
        return result

    def events(self, cal_url, start, end):
        fmt = "%Y%m%dT%H%M%SZ"
        body = ('<?xml version="1.0" encoding="utf-8"?>'
                '<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
                '<d:prop><d:getetag/><c:calendar-data/></d:prop>'
                '<c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="VEVENT">'
                f'<c:time-range start="{start.astimezone(timezone.utc).strftime(fmt)}" '
                f'end="{end.astimezone(timezone.utc).strftime(fmt)}"/>'
                '</c:comp-filter></c:comp-filter></c:filter></c:calendar-query>')
        tree = self._request("REPORT", cal_url, body, 1)
        data = []
        for resp in tree.findall("d:response", NS):
            for prop in self._ok_props(resp):
                text = prop.findtext("c:calendar-data", namespaces=NS)
                if text:
                    data.append(text)
        return data


# --------------------------------------------------------------------------
# Hilfsfunktionen
# --------------------------------------------------------------------------

def address_key(value, base=""):
    """Kalenderadresse vergleichbar machen: 'MAILTO:Leon@Example.de' -> 'mailto:leon@example.de',
    relative Principal-Adressen werden absolut (die Gäste in Einladungen stehen fast immer als mailto:)."""
    text = str(value or "").strip()
    if text.lower().startswith("mailto:"):
        return "mailto:" + unquote(text[7:]).strip().lower()
    if base and not re.match(r"^[a-z][a-z0-9+.-]*:", text, re.I):
        text = urljoin(base, text)
    return text.rstrip("/").lower()


def declined_by(ev, own):
    """True, wenn man selbst diese Einladung abgelehnt hat.

    Steht man mehrfach in der Gästeliste (zweite Adresse), zählt der Termin nur dann als
    abgelehnt, wenn jeder eigene Eintrag DECLINED ist. Absagen anderer Gäste spielen keine Rolle.
    """
    if not own:
        return False
    attendees = ev.get("attendee")
    if attendees is None:
        return False
    if not isinstance(attendees, list):
        attendees = [attendees]
    mine = [a for a in attendees if address_key(a) in own]
    return bool(mine) and all(str(a.params.get("PARTSTAT", "")).upper() == "DECLINED" for a in mine)


# Serien, die mehr als MAX_PER_DAY Vorkommen am Tag erzeugen, werden nicht aufgelöst (seit 1.33).
# Kalenderprogramme legen so etwas nicht an; die Grenze hält Rechenzeit und Speicher auf dem Pi klein.
MAX_PER_DAY = 96
_BASE_PER_DAY = {"SECONDLY": 86400, "MINUTELY": 1440, "HOURLY": 24}
_FINER = {"SECONDLY": (), "MINUTELY": ("BYSECOND",), "HOURLY": ("BYMINUTE", "BYSECOND")}


def too_dense(rrule):
    """Schätzt die Vorkommen je Tag einer RRULE (obere Grenze) und vergleicht mit MAX_PER_DAY."""
    if not rrule:
        return False
    freq = str((rrule.get("FREQ") or [""])[0]).upper()
    try:
        interval = max(int((rrule.get("INTERVAL") or [1])[0]), 1)
    except (TypeError, ValueError):
        interval = 1
    per_day = _BASE_PER_DAY.get(freq, 1) / interval
    for part in _FINER.get(freq, ("BYHOUR", "BYMINUTE", "BYSECOND")):
        per_day *= max(len(rrule.get(part) or []), 1)
    return per_day > MAX_PER_DAY


def contrast_color(hex_color):
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return "#000000" if (r * 299 + g * 587 + b * 114) / 1000 >= 150 else "#FFFFFF"


def hm(dt):
    return f"{dt.hour}:{dt.minute:02d}"


def day_label(d, today):
    if d == today:
        return "Heute"
    if d == today + timedelta(days=1):
        return "Morgen"
    if d == today + timedelta(days=2):
        return "Übermorgen"
    return WOCHENTAGE[d.weekday()]


def to_local(value, tz):
    """icalendar-Wert -> (datetime in tz, ist_ganztägig)."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=tz)  # "floating time"
        return value.astimezone(tz), False
    return datetime.combine(value, time.min, tz), True


# --------------------------------------------------------------------------
# Plugin
# --------------------------------------------------------------------------

class NextcloudKalender(BasePlugin):

    def generate_settings_template(self):
        params = super().generate_settings_template()
        params["style_settings"] = True
        params["api_key"] = {
            "required": True,
            "service": "Nextcloud (App-Passwort)",
            "expected_key": DEFAULT_PASSWORD_KEY,
        }
        return params

    def _opt(self, settings, key):
        if DEFAULTS.get(key) in ("true", "false") and cfg_version(settings) >= max(SINCE_VERSION.get(key, 1), 1):
            return settings.get(key, "false")   # gespeichert und Checkbox schon bekannt: fehlt = aus
        return settings.get(key) or DEFAULTS[key]

    # ------------------------------------------------------------------
    def generate_image(self, settings, device_config):
        flag = lambda k: self._opt(settings, k) == "true"  # noqa: E731

        user = (settings.get("username") or "").strip()
        if not user:
            raise RuntimeError("Bitte den Nextcloud-Benutzernamen angeben.")
        client, confirm = open_client(settings, device_config, user, flag("verifySSL"))

        tz_name = device_config.get_config("timezone", default="Europe/Berlin") or "Europe/Berlin"
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = ZoneInfo("Europe/Berlin")
        now = self.current_time(tz)
        today = now.date()

        layout = self._opt(settings, "layout")
        if layout not in ("agenda", "week"):
            layout = "agenda"
        if layout == "week":
            first = today if self._opt(settings, "weekStart") == "today" else today - timedelta(days=today.weekday())
            days = [first + timedelta(days=i) for i in range(7)]
        else:
            try:
                n = int(self._opt(settings, "days"))
            except ValueError:
                n = 14
            n = n if n in (3, 7, 14, 30) else 14
            days = [today + timedelta(days=i) for i in range(n)]

        # Für die Monatsübersicht auch die Punkte ("hat Termine") des ganzen Monats laden
        month_start = date(today.year, today.month, 1)
        month_end = date(today.year, today.month, pycal.monthrange(today.year, today.month)[1])
        range_start = min(days[0], month_start)
        range_end = max(days[-1], month_end) + timedelta(days=1)
        start_dt = datetime.combine(range_start, time.min, tz)
        end_dt = datetime.combine(range_end, time.min, tz)

        found = client.calendars()  # wirft bei falscher Anmeldung – erst danach die Nextcloud merken
        confirm()
        calendars = self.select_calendars(found, settings.get("calendars", ""))

        events = []
        failed = []
        for cal in calendars:
            try:
                for ics in client.events(cal["url"], start_dt, end_dt):
                    events.extend(self.parse_events(ics, cal, tz, start_dt, end_dt, client.own_addresses))
            except RuntimeError as exc:
                logger.warning("Kalender %s konnte nicht gelesen werden: %s", cal["name"], exc)
                failed.append(cal["name"])
        if getattr(self, "declined_hidden", 0):
            logger.info("Kalender: %d abgelehnte Termine ausgeblendet", self.declined_hidden)
            self.declined_hidden = 0
        if failed and len(failed) == len(calendars):
            raise RuntimeError(f"Kein Kalender lesbar ({', '.join(failed)}) – siehe Logs.")

        use_colors = flag("useColors")
        for ev in events:
            ev["color"] = ev["cal_color"] if use_colors else "#000000"
            ev["fg"] = contrast_color(ev["color"])

        per_day = {d: self.events_on_day(events, d, tz, now, flag("showPast")) for d in days}

        params = {
            "layout": layout,
            "title": (settings.get("customTitle") or "").strip(),
            "today": {
                "day": today.day,
                "weekday": WOCHENTAGE[today.weekday()],
                "month": f"{MONATE[today.month - 1]} {today.year}",
                "kw": today.isocalendar()[1],
                "long": f"{WOCHENTAGE[today.weekday()]}, {today.day}. {MONATE[today.month - 1]} {today.year}",
            },
            "month": self.month_grid(today, events, tz) if flag("showMonth") and layout == "agenda" else None,
            "agenda": [],
            "week": [],
            "show_location": flag("showLocation"),
            "show_footer": flag("showFooter"),
            "use_colors": use_colors,
            "legend": [{"name": c["name"], "color": c["color"]} for c in calendars] if use_colors and len(calendars) > 1 else [],
            "updated": now.strftime("%H:%M"),
            "failed": failed,
            "plugin_settings": settings,
        }

        if layout == "agenda":
            for d in days:
                items = per_day[d]
                if items or (d == today and flag("showEmptyToday")):
                    params["agenda"].append({
                        "label": day_label(d, today),
                        "date": f"{WOCHENTAGE_KURZ[d.weekday()]}, {d.day}. {MONATE[d.month - 1]}",
                        "is_today": d == today,
                        "weekend": d.weekday() >= 5,
                        "events": items,
                    })
            params["range_text"] = f"nächste {len(days)} Tage"
        else:
            for d in days:
                params["week"].append({
                    "name": WOCHENTAGE_KURZ[d.weekday()],
                    "date": f"{d.day}.{d.month}.",
                    "is_today": d == today,
                    "weekend": d.weekday() >= 5,
                    "events": per_day[d],
                })
            params["range_text"] = (f"{days[0].day}.{days[0].month}. – {days[-1].day}.{days[-1].month}.{days[-1].year}"
                                    f" · KW {days[0].isocalendar()[1]}")

        dimensions = device_config.get_resolution()
        if device_config.get_config("orientation") == "vertical":
            dimensions = dimensions[::-1]
        params["orientation"] = "portrait" if dimensions[1] > dimensions[0] else "landscape"

        if zeichensatz is not None:
            zeichensatz.utf8_templates(self)  # sonst rät Chromium den Zeichensatz
        image = self.render_image(dimensions, "nextcloud_kalender.html", "nextcloud_kalender.css", params)
        if not image:
            raise RuntimeError("Bild konnte nicht erzeugt werden – siehe Logs.")
        if eink is not None:
            image = eink.prepare(image, device_config, enabled=flag("einkSnap"))
        return image

    def current_time(self, tz):
        """Eigene Methode, damit Tests eine feste Uhrzeit einsetzen können."""
        return datetime.now(tz)

    # ------------------------------------------------------------------
    def select_calendars(self, available, wanted_raw):
        if not available:
            raise RuntimeError("In dieser Nextcloud wurden keine Kalender gefunden.")
        wanted = [w.strip() for w in (wanted_raw or "").split(",") if w.strip()]
        if not wanted:
            return available
        by_name = {c["name"].casefold(): c for c in available}
        chosen, missing = [], []
        for w in wanted:
            cal = by_name.get(w.casefold())
            (chosen.append(cal) if cal else missing.append(w))
        if missing:
            names = ", ".join(c["name"] for c in available)
            raise RuntimeError(f"Kalender nicht gefunden: {', '.join(missing)}. Verfügbar: {names}")
        return chosen

    def parse_events(self, ics_text, cal, tz, start_dt, end_dt, own=()):
        """Termine einer ICS-Datei im Zeitraum. own = eigene Adressen (CalDavClient.own_addresses):
        Einladungen, die man selbst abgelehnt hat, fallen weg (Anzahl in self.declined_hidden)."""
        try:
            vcal = icalendar.Calendar.from_ical(ics_text)
            dense = [c for c in vcal.walk("VEVENT") if too_dense(c.get("RRULE"))]
            if dense:  # z. B. FREQ=SECONDLY
                logger.warning("Kalender %s: %d Serie(n) mit mehr als %d Vorkommen am Tag übersprungen",
                               cal["name"], len(dense), MAX_PER_DAY)
                return []
            occurrences = recurring_ical_events.of(vcal).between(start_dt, end_dt)
        except Exception:
            logger.warning("Termin in %s konnte nicht gelesen werden", cal["name"], exc_info=True)
            return []

        result = []
        for ev in occurrences:
            if str(ev.get("status", "")).upper() == "CANCELLED":
                continue
            if declined_by(ev, own):
                self.declined_hidden = getattr(self, "declined_hidden", 0) + 1
                continue
            start, all_day = to_local(ev.decoded("dtstart"), tz)
            if "dtend" in ev:
                end, _ = to_local(ev.decoded("dtend"), tz)
            elif "duration" in ev:
                end = start + ev.decoded("duration")
            else:
                end = start + (timedelta(days=1) if all_day else timedelta(0))
            result.append({
                "title": str(ev.get("summary") or "(ohne Titel)").strip(),
                "location": str(ev.get("location") or "").strip(),
                "start": start,
                "end": max(end, start),
                "all_day": all_day,
                "cal_name": cal["name"],
                "cal_color": cal["color"],
            })
        return result

    def events_on_day(self, events, d, tz, now, show_past):
        day_start = datetime.combine(d, time.min, tz)
        day_end = day_start + timedelta(days=1)
        items = []
        for ev in events:
            s, e = ev["start"], ev["end"]
            if ev["all_day"]:
                if not (s.date() <= d < e.date() or (s.date() == d and e.date() == d)):
                    continue
                total = max((e.date() - s.date()).days, 1)
                idx = (d - s.date()).days + 1
                time_text = "ganztägig"
                span_text = f"Tag {idx}/{total}" if total > 1 else ""
                sort_key = (0, s)
            else:
                touches = (s < day_end and e > day_start) or (s == e and day_start <= s < day_end)
                if not touches:
                    continue
                if not show_past and d == now.date() and e <= now and e != s:
                    continue  # heute schon vorbei
                if not show_past and d == now.date() and s == e and s < now:
                    continue
                span_text = ""
                starts_today, ends_today = s >= day_start, e <= day_end
                if starts_today and ends_today:
                    time_text = hm(s) if s == e else f"{hm(s)} – {hm(e)}"
                elif starts_today:
                    time_text = f"ab {hm(s)}"
                elif ends_today:
                    time_text = f"bis {hm(e)}"
                else:
                    time_text = "ganztägig"
                sort_key = (0, s) if time_text == "ganztägig" else (1, max(s, day_start))
            items.append({
                "title": ev["title"],
                "location": ev["location"],
                "time": time_text,
                "short": hm(s) if (not ev["all_day"] and time_text.startswith(hm(s))) else time_text,
                "span": span_text,
                "all_day": time_text == "ganztägig",
                "color": ev["color"],
                "fg": ev["fg"],
                "calendar": ev["cal_name"],
                "now": (not ev["all_day"]) and s <= now < e,
                "until": f"bis {hm(e)}" if e <= day_end else "",
                "sort": sort_key,
                "source": ev,  # Rohdaten (Start/Ende), z. B. für das Tagesdashboard
            })
        items.sort(key=lambda x: (x["sort"], x["title"]))
        return items

    def month_grid(self, today, events, tz):
        busy = set()
        for ev in events:
            d = ev["start"].date()
            last = (ev["end"] - timedelta(seconds=1)).date() if ev["end"] > ev["start"] else d
            while d <= last:
                busy.add(d)
                d += timedelta(days=1)
        weeks = []
        for week in pycal.Calendar(firstweekday=0).monthdatescalendar(today.year, today.month):
            weeks.append({
                "kw": week[0].isocalendar()[1],
                "days": [{
                    "num": d.day,
                    "other": d.month != today.month,
                    "today": d == today,
                    "busy": d in busy and d.month == today.month,
                    "weekend": d.weekday() >= 5,
                } for d in week],
            })
        return {"weeks": weeks, "head": WOCHENTAGE_KURZ}
