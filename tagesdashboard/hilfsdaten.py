"""Daten für das Hilfsbild (seit 1.50, Taste D): Zugang zur Weboberfläche, Zeichnen, Updates, Datenquellen,
Netz, Dienste, Ereignisse, letzter Fehler; seit 1.53 auch die apt-Updates des Pi.

Alles hier liest nur und wirft nie: Fehlt etwas (anderer Rechner, keine Rechte, Programm nicht installiert),
fehlt einfach die Zeile. Das Hilfsbild ist ein Werkzeug für den Fehlerfall und darf selbst nie einer sein.

Jede Zeile ist ein Wörterbuch {"text": …, "bad": True|False}: `bad` markiert, was Aufmerksamkeit braucht
(rot gepunktet im Bild). Ein Abschnitt ist {"key", "title", "lines": [...]}. Die Reihenfolge bestimmt das Template.

Zugriffe auf das System laufen über `_run` (Programme) und `_read` (Dateien); Tests ersetzen beide.
"""
import logging
import os
import re
import socket
import subprocess
import time
from datetime import datetime, timedelta

from . import livestream, status as anzeige

logger = logging.getLogger(__name__)

PORT = 80                      # InkyPis Weboberfläche (der Tasten-Dienst ruft dieselbe Adresse auf)
RUN_TIMEOUT = 3                # s je Programm; das Hilfsbild soll schnell sein
FEHLER_STUNDEN = 24            # so weit zurück sucht der letzte Fehler im Journal
FEHLER_LAENGE = 84             # Zeichen; länger wird am Wortende gekürzt
DIENSTE = [                    # (Einheit, Name im Bild)
    ("inkypi.service", "InkyPi"),
    ("inkypi-tasten.service", "Tasten"),
    ("inkypi-ausschaltbild.service", "Ausschaltbild"),
    ("inkypi-update.timer", "Update"),
]
WOCHENTAGE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
APT_TIMEOUT = 20               # s; `apt-get -s` liest den ganzen Paketzwischenspeicher, auf einem Pi 3 dauert das einige Sekunden
APT_MERKEN_MIN = 60            # so lange gilt ein Ergebnis (Taste D soll nicht jedes Mal darauf warten)
APT_FEHLER_MIN = 10            # ein Fehlschlag wird früher wiederholt
LISTEN_ALT_TAGE = 7            # ältere Paketlisten → „Zahl unsicher“
_apt_gemerkt = {}              # {"bis": time.time()-Wert, "n": …, "sicher": …}; Tests leeren es


def _run(cmd, timeout=RUN_TIMEOUT):
    """Programm ausführen, Standardausgabe als Text oder None (nicht da, Fehler, zu langsam, leer)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 and r.stdout.strip() else None


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def _hm(dt):
    return f"{dt.hour}:{dt.minute:02d}"


def _line(text, bad=False):
    return {"text": text, "bad": bool(bad)}


# ---------------------------------------------------------------------------------------------- Zugang
def lokale_ip():
    """Die IPv4-Adresse, mit der der Pi ins Heimnetz geht. Ein UDP-Socket „verbindet“ sich mit einer
    Adresse aus dem Dokumentationsbereich (RFC 5737): Das schickt kein Paket, lässt aber das Betriebssystem
    die ausgehende Schnittstelle wählen. Ohne Netz → None."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.settimeout(1)
        s.connect(("192.0.2.1", 9))
        ip = s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()
    return None if ip.startswith("127.") or ip == "0.0.0.0" else ip


def zugang(host=None, ip=None, port=PORT):
    """Adresse der Weboberfläche, automatisch aus Hostname und IP. -> {"namen": [Text, …], "qr": URL | None}.
    Der QR-Code trägt die IP-Adresse, weil sie überall geht; „raspi.local“ scheitert an manchen Handys und
    Netzen (mDNS). Ohne IP trägt er den .local-Namen. Ohne beides gibt es keinen Zugang zu zeigen (None)."""
    try:
        if host is None:
            host = socket.gethostname()
        if ip is None:
            ip = lokale_ip()
    except OSError:
        host = host or ""
    host = (host or "").split(".")[0].strip()
    suffix = "" if port == 80 else f":{port}"
    namen, qr = [], None
    if host and host.lower() != "localhost":
        namen.append(f"{host.lower()}.local{suffix}")
        qr = f"http://{host.lower()}.local{suffix}"
    if ip:
        namen.append(f"{ip}{suffix}")
        qr = f"http://{ip}{suffix}"   # die IP geht vor
    if not namen:
        return None
    return {"namen": namen, "qr": qr}


def zugang_mit_qr(daten):
    """Ergänzt den QR-Code als SVG (`svg.qr`, `data-n` für fitQr im Template). Fehler → ohne Code."""
    if not daten:
        return None
    out = dict(daten)
    try:
        out["svg"], _ = livestream.qr_svg(daten["qr"])
    except Exception:  # segno-Fehler dürfen das Hilfsbild nicht kosten
        logger.exception("QR-Code fürs Hilfsbild nicht erzeugt")
        out["svg"] = None
    return out


# ---------------------------------------------------------------------------------------------- Zeichnen
def zeichnen(draw, now):
    """„Zuletzt gezeichnet 15:41“, „Neu alle 30 min“ und „Nächstes Bild ca. 16:11“ (je eine kurze Zeile: die
    mittlere Spalte des Hilfsbilds ist quer schmal, eine zusammengezogene Zeile brach um).

    `draw` = hilfsbild.last_draw(): wann das Dashboard zuletzt wirklich ein neues Bild gebaut hat und wann es
    das nächste Mal neu zeichnet. Bewusst *nicht* InkyPis Playlist-Takt und nicht `refresh_time`: Beides
    zählt jeden Aufruf von InkyPi (z. B. alle 5 min), auch wenn das Dashboard nur sein gemerktes Bild
    zurückgibt und das Display in Ruhe bleibt (seit 1.51; in 1.50 stand dort „Takt 5 min · nächstes …“,
    obwohl das Bild nur alle 30 min wechselte). Ohne Zeichenvorgang seit dem Start (`None`) fehlen beide Zeilen."""
    at = (draw or {}).get("at")
    if not isinstance(at, datetime):
        return []
    try:
        if at.tzinfo is not None and now.tzinfo is not None:
            at = at.astimezone(now.tzinfo)
    except (ValueError, OSError):
        pass
    lines = [_line(f"Zuletzt gezeichnet {_tag(at, now)}")]
    nxt, every = draw.get("next"), draw.get("every")
    if isinstance(nxt, datetime):
        try:
            if nxt.tzinfo is not None and now.tzinfo is not None:
                nxt = nxt.astimezone(now.tzinfo)
        except (ValueError, OSError):
            pass
        if isinstance(every, (int, float)) and not isinstance(every, bool) and every > 0:
            lines.append(_line(f"Neu alle {round(every)} min" if every < 120 else f"Neu alle {round(every) // 60} Std."))
        lines.append(_line("Nächstes Bild gleich" if nxt <= now else f"Nächstes Bild ca. {_tag(nxt, now)}"))
    return lines


def _tag(dt, now):
    """„15:41“ heute, „gestern 22:40“, sonst „Mo 22:40“ (innerhalb einer Woche) oder „3.11. 22:40“."""
    days = (dt.date() - now.date()).days
    if days == 0:
        return _hm(dt)
    if days == -1:
        return f"gestern {_hm(dt)}"
    if days == 1:
        return f"morgen {_hm(dt)}"
    if -6 <= days <= 6:
        return f"{WOCHENTAGE[dt.weekday()]} {_hm(dt)}"
    return f"{dt.day}.{dt.month}. {_hm(dt)}"


# ---------------------------------------------------------------------------------------------- Ereignisse
def _naechster(now, a, wochentag=None, monatserster=False):
    """Nächster Beginn eines Fensters ab jetzt: täglich um a, nur am Wochentag oder nur am Monatsersten."""
    for add in range(0, 400):
        d = now.date() + timedelta(days=add)
        if wochentag is not None and d.weekday() != wochentag:
            continue
        if monatserster and d.day != 1:
            continue
        cand = now.replace(year=d.year, month=d.month, day=d.day, hour=a.hour, minute=a.minute,
                           second=0, microsecond=0)
        if cand > now:
            return cand
    return None


def ereignisse(now, night_win=None, week_win=None, month_win=None, week_day=6):
    """Was als Nächstes kommt: das Nachtbild (die Tasten ruhen dann) und die nächste Sonderansicht
    (Wochenvorschau oder Monatsbild, je nachdem, was früher kommt)."""
    lines = []
    if night_win:
        n = _naechster(now, night_win[0])
        if n:
            lines.append(_line(f"Nachtbild ab {_tag(n, now)}"))
    kandidaten = []
    if week_win:
        w = _naechster(now, week_win[0], wochentag=week_day)
        if w:
            kandidaten.append((w, "Wochenvorschau"))
    if month_win:
        m = _naechster(now, month_win[0], monatserster=True)
        if m:
            kandidaten.append((m, "Monatsbild"))
    if kandidaten:
        wann, was = min(kandidaten)
        lines.append(_line(f"{was} ab {_tag(wann, now)}"))
    return lines


# ---------------------------------------------------------------------------------------------- Updates
def updates(info):
    """Zeilen aus `freigabe.status()`: installierter Stand, neue Freigabe, letzter Lauf."""
    if not info:
        return []
    if not info.get("eingerichtet"):
        return [_line("Signierte Updates nicht eingerichtet")]
    lines = []
    inst = info.get("installiert")
    if inst:
        txt = f"Installiert v{inst['version']}" + (f" · {inst['wann']}" if inst.get("wann") else "")
        lines.append(_line(txt))
    else:
        lines.append(_line("Noch kein signierter Stand eingespielt"))
    if info.get("fremd"):
        lines.append(_line(f"Läuft v{info.get('plugin')}, nicht der signierte Stand", bad=True))
    if info.get("bereit"):
        lines.append(_line(f"Neue Freigabe {info['bereit']} bereit"))
    else:
        lines.append(_line("Keine neue Freigabe"))
    lauf = info.get("lauf")
    if lauf:
        lines.append(_line(f"Lauf {lauf['wann']} ({lauf['art']}): " + ("ok" if lauf["ok"] else "Fehler"),
                           bad=not lauf["ok"]))
    return lines


# ---------------------------------------------------------------------------------------------- Pi-Updates (apt)
def apt_auswerten(text):
    """Ausgabe von `apt-get -s dist-upgrade` (mit LC_ALL=C) → (Updates, davon Sicherheit) oder None.
    Die Zahl steht in der Schlusszeile („12 upgraded, 2 newly installed, …“); fehlt sie, war die Ausgabe
    unbrauchbar (None statt „0 Updates“). Sicherheit: Zeilen `Inst <Paket> [alt] (neu Quelle1, Quelle2 [arch])`,
    in denen irgendeine Quelle „security“ heißt (Debian-Security:12/stable-security). Neu installierte Pakete
    (ohne `[alt]`, z. B. ein neuer Kernel) zählen nicht als Update."""
    if not text:
        return None
    m = re.search(r"^(\d+) upgraded, \d+ newly installed", text, re.M)
    if not m:
        return None
    sicher = sum(1 for ln in text.splitlines()
                 if re.match(r"Inst \S+ \[[^\]]+\] \(", ln) and re.search(r"security", ln, re.I))
    return int(m.group(1)), sicher


def _kernel_schluessel(name):
    """„6.6.51+rpt-rpi-v8“ → ((6, 6, 51), 0, „+rpt-rpi-v8“); „6.1.0-13-arm64“ → ((6, 1, 0), 13, „-arm64“)."""
    m = re.match(r"(\d+(?:\.\d+)*)(?:-(\d+))?(.*)$", name)
    if not m:
        return None
    return tuple(int(x) for x in m.group(1).split(".")), int(m.group(2) or 0), m.group(3)


def neustart_grund(run=None, read=None):
    """Warum ein Neustart aussteht: „kernel“ (unter /lib/modules liegt ein neuerer Kernel derselben Art als der
    laufende), „hinweis“ (das System hat /run/reboot-required angelegt) oder None. Kernel vergleichen wir selbst,
    weil Raspberry Pi OS die Hinweisdatei nicht anlegt."""
    run, read = run or _run, read or _read
    mein = _kernel_schluessel((run(["uname", "-r"]) or "").strip())
    if mein:
        for name in (run(["ls", "/lib/modules"]) or "").split():
            k = _kernel_schluessel(name)
            if k and k[2] == mein[2] and k[:2] > mein[:2]:
                return "kernel"
    if read("/run/reboot-required") is not None or read("/var/run/reboot-required") is not None:
        return "hinweis"
    return None


def listen_alter_tage(now, run=None):
    """Alter der Paketlisten in Tagen (neuester Zeitstempel von update-success-stamp und den *Release-Dateien in
    /var/lib/apt/lists) oder None. `apt-get -s` rechnet nur mit dem, was die Listen wissen: Hat niemand
    `apt update` ausgeführt, ist die Zahl veraltet – das Hilfsbild sagt es dann dazu."""
    out = (run or _run)(["find", "/var/lib/apt/lists", "/var/lib/apt/periodic", "-maxdepth", "1", "(",
                         "-name", "*Release", "-o", "-name", "update-success-stamp", ")", "-printf", "%T@\\n"])
    zeiten = []
    for ln in (out or "").split():
        try:
            zeiten.append(float(ln))
        except ValueError:
            pass
    return max(0.0, (now.timestamp() - max(zeiten)) / 86400) if zeiten else None


def apt_lage(now, run=None, read=None):
    """Alles über die Updates des Pi: {"n": Updates oder None, "sicher": davon Sicherheit, "neustart": Grund oder
    None, "alter": Alter der Paketlisten in Tagen oder None}. Die apt-Abfrage wird gemerkt (`APT_MERKEN_MIN`)."""
    run = run or _run
    jetzt = time.time()
    if _apt_gemerkt.get("bis", 0) <= jetzt:
        t0 = time.time()
        erg = apt_auswerten(run(["env", "LC_ALL=C", "apt-get", "-s", "dist-upgrade"], timeout=APT_TIMEOUT))
        _apt_gemerkt.update(bis=jetzt + 60 * (APT_MERKEN_MIN if erg else APT_FEHLER_MIN),
                            n=erg[0] if erg else None, sicher=erg[1] if erg else 0)
        logger.info("Pi-Updates: %s in %.1f s",
                    f"{erg[0]} ({erg[1]} Sicherheit)" if erg else "nicht ermittelt", time.time() - t0)
    return {"n": _apt_gemerkt.get("n"), "sicher": _apt_gemerkt.get("sicher", 0),
            "neustart": neustart_grund(run, read), "alter": listen_alter_tage(now, run)}


def apt_zeilen(lage):
    """Zeilen für den Abschnitt „Updates“. Rot gepunktet (bad): Sicherheitsupdates, Neustart, veraltete Listen."""
    lines = []
    n = lage.get("n")
    if n is not None:
        if n == 0:
            lines.append(_line("Pi: aktuell"))
        else:
            sicher = lage.get("sicher") or 0
            lines.append(_line(f"Pi: {n} {'Update' if n == 1 else 'Updates'}"
                               + (f" ({sicher} Sicherheit)" if sicher else ""), bad=bool(sicher)))
        alter = lage.get("alter")
        if alter is not None and alter > LISTEN_ALT_TAGE:
            lines.append(_line(f"Paketlisten {int(alter)} Tage alt, Zahl unsicher", bad=True))
    if lage.get("neustart"):
        lines.append(_line("Neustart nötig" + (" (neuer Kernel)" if lage["neustart"] == "kernel" else ""), bad=True))
    return lines


def pi_updates(now, run=None, read=None):
    """Wie alles hier: wirft nie, im Zweifel fehlen die Zeilen."""
    try:
        return apt_zeilen(apt_lage(now, run, read))
    except Exception:
        logger.exception("Pi-Updates nicht ermittelt")
        return []


# ---------------------------------------------------------------------------------------------- Datenquellen
def quellen(snapshot, now, nennen=3):
    """Quellen, die gerade ausfallen: „Kalender seit 9:10 · Radar seit 11:20“. Der Speicher von status.py
    beginnt nach einem Neustart neu; „keine Ausfälle“ heißt also: seit dem Start keine."""
    if not snapshot:
        return [_line("Alle Datenquellen erreichbar")]
    eintraege = sorted(snapshot.items(), key=lambda kv: kv[1][0])
    teile = [f"{name} seit {anzeige.since_text(seit, now)}" for name, (seit, _last) in eintraege[:nennen]]
    if len(eintraege) > nennen:
        teile.append(f"+ {len(eintraege) - nennen} weitere")
    return [_line(" · ".join(teile), bad=True)]


# ---------------------------------------------------------------------------------------------- Netz
def wlan(run=_run, read=_read):
    """„WLAN Heimnetz · gut (−58 dBm)“ / „Kabel“ / None (nichts erkannt)."""
    raw = read("/proc/net/wireless")
    iface, dbm = None, None
    if raw:
        for ln in raw.splitlines()[2:]:
            teile = ln.split()
            if len(teile) >= 4:
                iface = teile[0].rstrip(":")
                try:
                    dbm = float(teile[3].rstrip("."))
                except ValueError:
                    dbm = None
                break
    if not iface:
        return None
    ssid = _ssid(run, iface)
    name = f"WLAN {ssid}" if ssid else "WLAN"
    if dbm is None:
        return _line(name)
    if dbm >= -50:
        wort, bad = "sehr gut", False
    elif dbm >= -60:
        wort, bad = "gut", False
    elif dbm >= -70:
        wort, bad = "mäßig", False
    else:
        wort, bad = "schwach", True
    return _line(f"{name} · {wort} (−{abs(int(dbm))} dBm)", bad=bad)


def _ssid(run, iface):
    out = run(["iwgetid", "-r"])
    if out and out.strip():
        return out.strip()
    out = run(["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"])
    if out:
        for ln in out.splitlines():
            if ln.startswith("yes:"):
                return ln[4:].replace("\\:", ":").strip() or None
    out = run(["iw", "dev", iface, "link"])
    if out:
        m = re.search(r"SSID:\s*(.+)", out)
        if m:
            return m.group(1).strip()
    return None


def zeit_synchron(run=_run):
    """Zeile nur bei einem Problem: Die Uhr des Pi ist nicht mit einem Zeitserver abgeglichen (dann stimmen
    Termine, Sonnenstand und Bahn nicht). Antwort von timedatectl unklar → keine Zeile."""
    out = run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"])
    if out and out.strip().lower() == "no":
        return _line("Uhr nicht mit Zeitserver abgeglichen", bad=True)
    return None


# ---------------------------------------------------------------------------------------------- Dienste
def dienste(run=_run, liste=DIENSTE):
    """Eine Zeile mit allen laufenden Diensten oder je eine rote Zeile für jeden, der nicht läuft.
    Nicht installierte Einheiten (LoadState=not-found) zählen nicht: Wer kein Ausschaltbild hat, soll es
    nicht vermissen."""
    out = run(["systemctl", "show", "-p", "Id", "-p", "LoadState", "-p", "ActiveState", "-p", "SubState"]
              + [u for u, _ in liste])
    if not out:
        return []
    ok, schlecht = [], []
    namen = dict(liste)
    for block in re.split(r"\n\s*\n", out.strip()):
        kv = dict(ln.split("=", 1) for ln in block.splitlines() if "=" in ln)
        unit = kv.get("Id")
        if unit not in namen or kv.get("LoadState") == "not-found":
            continue
        zustand = kv.get("ActiveState", "")
        if zustand in ("active", "activating", "reloading"):
            ok.append(namen[unit])
        else:
            schlecht.append(_line(f"{namen[unit]}: {_zustand(zustand, kv.get('SubState', ''))}", bad=True))
    lines = list(schlecht)
    if ok:
        lines.append(_line("Alle Dienste laufen" if not schlecht else "Übrige Dienste laufen: " + " · ".join(ok)))
    return lines


def _zustand(active, sub):
    return {"failed": "fehlgeschlagen", "inactive": "gestoppt", "deactivating": "wird beendet"}.get(active, sub or active)


# ---------------------------------------------------------------------------------------------- Fehler
def letzter_fehler(now, run=_run):
    """Neueste Fehlerzeile von InkyPi aus den letzten 24 Stunden: „Mi 14:02 Kalender: …“. Das Journal braucht
    Leserechte; ohne sie (oder ohne journalctl) gibt es keine Zeile. Gefunden wird über das Wort ERROR bzw.
    Traceback (InkyPi und seine Plugins loggen mit Pegelnamen; systemd selbst kennt die Pegel der
    Python-Ausgabe nicht, `-p err` fände nichts)."""
    out = run(["journalctl", "-u", "inkypi.service", "--since", f"-{FEHLER_STUNDEN}h", "--no-pager",
               "-o", "short-iso", "-r", "-n", "1", "-g", "ERROR|Traceback"], timeout=5)
    if not out:
        return _line(f"Kein Fehler in {FEHLER_STUNDEN} Stunden") if _journal_lesbar(run) else None
    zeile = out.strip().splitlines()[0]
    m = re.match(r"(\S+)\s+\S+\s+\S+?\[\d+\]:\s*(.*)", zeile)
    if not m:
        return None
    wann = None
    try:
        wann = datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S%z")
        if now.tzinfo is not None:
            wann = wann.astimezone(now.tzinfo)
    except ValueError:
        pass
    text = _kurz(m.group(2))
    return _line((f"{_tag(wann, now)} " if wann else "") + text, bad=True)


def _journal_lesbar(run):
    """Sonst wäre „kein Fehler“ eine Behauptung ohne Grundlage (Journal nicht lesbar)."""
    return bool(run(["journalctl", "-u", "inkypi.service", "-n", "1", "--no-pager", "-o", "cat"], timeout=5))


def _kurz(text, n=FEHLER_LAENGE):
    text = re.sub(r"^\S+ - (ERROR|WARNING|INFO) - ", "", text.strip())   # „name - ERROR - “ vorn weg
    text = re.sub(r"\s+", " ", text)
    if len(text) <= n:
        return text
    cut = text[:n].rsplit(" ", 1)[0] or text[:n]
    return cut.rstrip(",.;:") + " …"


# ---------------------------------------------------------------------------------------------- Zusammenbau
def abschnitte(now, pi_lines, draw=None, update_info=None, status_snapshot=None,
               night_win=None, week_win=None, month_win=None, week_day=6, run=_run, read=_read):
    """Alle Abschnitte des Hilfsbilds (ohne Tasten und Zugang) in Anzeigereihenfolge. Leere fehlen."""
    zeit = zeit_synchron(run)
    netz = wlan(run, read)
    out = [
        {"key": "anzeige", "title": "Anzeige", "lines": zeichnen(draw, now)
         + ereignisse(now, night_win, week_win, month_win, week_day)},
        {"key": "updates", "title": "Updates", "lines": pi_updates(now, run, read) + updates(update_info)},
        {"key": "quellen", "title": "Datenquellen", "lines": quellen(status_snapshot or {}, now)},
        {"key": "pi", "title": "Pi", "lines": [_line(t) for t in pi_lines] + ([zeit] if zeit else [])},
        {"key": "netz", "title": "Netz und Dienste", "lines": ([netz] if netz else []) + dienste(run)},
        {"key": "fehler", "title": "Letzter Fehler", "lines": [x for x in [letzter_fehler(now, run)] if x]},
    ]
    return [s for s in out if s["lines"]]
