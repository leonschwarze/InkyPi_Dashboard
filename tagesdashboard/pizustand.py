"""
Wie geht's dem Pi? (seit 1.28) – eine Fußzeile in der Wochenvorschau (Variante A, immer da):

  Pi: Kalender 2× weg (40 min, zuletzt Do 3:10) · 23 Tage online · bis 52 °C · 9,8 GB frei
  Pi: 23 Tage online · bis 52 °C · 9,8 GB frei · Woche ohne Ausfälle

Probleme stehen vorn (wird die Zeile zu lang, fallen hinten die ruhigen Werte weg):
  * Unterspannung: Der Pi meldet zu wenig Spannung am Netzteil (vcgencmd get_throttled, Bit 0 = gerade,
    Bit 16 = seit dem Start; Rückfall: hwmon „rpi_volt“, in0_lcrit_alarm)
  * Neustarts der letzten 7 Tage (Startzeit = jetzt − /proc/uptime)
  * Ausfälle je Datenquelle aus der Statusanzeige (status.py): Anzahl, Dauer, wann zuletzt
Danach: wie lange online, höchste CPU-Temperatur der Woche (/sys/class/thermal/thermal_zone0/temp),
freier Speicher auf der Karte (shutil.disk_usage("/")).

Mitschreiben: record() läuft in jeder Runde mit echten Abrufen (auch wenn es kein Bild gibt, z. B. ohne
Internet). Der Zustand der Statusanzeige liegt nur im Speicher; hier wird er in eine kleine JSON-Datei
neben InkyPis device.json geschrieben (src/config/tagesdashboard_pi.json), damit die Woche einen Neustart
und ein Update des Plugins übersteht. Geschrieben wird nur, wenn sich etwas ändert (neuer Ausfall, neue
Tageshöchsttemperatur ab +1 °C, Neustart, Unterspannung) – die Speicherkarte wird geschont.
Einträge älter als KEEP fallen weg.

Ohne Pi (Entwicklungsrechner) fehlen Temperatur und Spannung einfach; die Zeile zeigt, was es gibt.
"""

import glob
import json
import logging
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

STATE_FILE = "tagesdashboard_pi.json"
WINDOW = timedelta(days=7)          # „die Woche“: die letzten 7 Tage bis jetzt
KEEP = timedelta(days=9)            # so lange bleiben Einträge in der Datei
CLOSE_GAP = timedelta(minutes=30)   # Ausfall endet ohne Runde dazwischen → Ende = letzter Fehlschlag
BOOT_TOLERANCE = timedelta(minutes=5)
VOLT_REPEAT = timedelta(hours=6)    # dauernde Unterspannung höchstens alle 6 Stunden neu eintragen
TEMP_STEP = 1.0                     # neue Tageshöchsttemperatur erst ab +1 °C speichern
KURZ = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

_last_system = None  # letzte Messung von read_system() (für line()); None = noch nie gemessen


# ----------------------------------------------------------------------
# Werte vom Pi
# ----------------------------------------------------------------------
def state_path(device_config):
    """Datei neben InkyPis device.json; ohne InkyPi-Konfiguration im Temp-Ordner."""
    cfg = getattr(device_config, "config_file", None)
    base = os.path.dirname(cfg) if isinstance(cfg, str) and cfg else tempfile.gettempdir()
    return os.path.join(base, STATE_FILE)


def _read(path):
    with open(path) as f:
        return f.read().strip()


def undervoltage():
    """{"now": bool, "since_boot": bool | None} oder None, wenn der Pi das nicht verrät."""
    try:
        out = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=3).stdout
        value = int(out.strip().split("=", 1)[1], 16)  # „throttled=0x50005“
        return {"now": bool(value & 0x1), "since_boot": bool(value & 0x10000)}
    except Exception:
        pass
    for name in glob.glob("/sys/class/hwmon/hwmon*/name"):
        try:
            if _read(name) == "rpi_volt":
                alarm = _read(os.path.join(os.path.dirname(name), "in0_lcrit_alarm"))
                return {"now": alarm == "1", "since_boot": None}
        except Exception:
            continue
    return None


def read_system():
    """Messwerte des Pi; was fehlt, fehlt (z. B. auf dem Entwicklungsrechner)."""
    out = {}
    try:
        out["uptime"] = float(_read("/proc/uptime").split()[0])
    except Exception:
        pass
    try:
        out["temp"] = int(_read("/sys/class/thermal/thermal_zone0/temp")) / 1000
    except Exception:
        pass
    try:
        out["free"] = shutil.disk_usage("/").free
    except Exception:
        pass
    out["volt"] = undervoltage()
    return out


# ----------------------------------------------------------------------
# Datei
# ----------------------------------------------------------------------
def empty():
    return {"v": 1, "episodes": [], "temp": {}, "boots": [], "volt": []}


def load(path):
    try:
        with open(path) as f:
            data = json.load(f)
        base = empty()
        base.update({k: data[k] for k in base if k in data and isinstance(data[k], type(base[k]))})
        return base
    except FileNotFoundError:
        return empty()
    except Exception as exc:
        logger.warning("Pi: Zustandsdatei %s unlesbar (%s) – beginne neu", path, exc)
        return empty()


def save(path, state):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=0)
    os.replace(tmp, path)  # nie eine halb geschriebene Datei


def _t(text):
    return datetime.fromisoformat(text)


def _iso(dt):
    return dt.replace(microsecond=0).isoformat()


# ----------------------------------------------------------------------
# Mitschreiben
# ----------------------------------------------------------------------
def record(now, outages, path, system=None):
    """Eine Runde übernehmen. outages = status.snapshot(): {quelle: (seit, zuletzt gescheitert)}.
    Gibt True zurück, wenn die Datei geschrieben wurde."""
    global _last_system
    system = read_system() if system is None else system
    _last_system = system
    state = load(path)
    before = json.dumps(state, sort_keys=True)  # geschrieben wird nur, wenn sich am Ende etwas unterscheidet

    # Neustart: Startzeit aus der Laufzeit
    boot = None
    if system.get("uptime") is not None:
        boot = now - timedelta(seconds=system["uptime"])
        if not any(abs(_t(b) - boot) <= BOOT_TOLERANCE for b in state["boots"]):
            state["boots"].append(_iso(boot.replace(second=0)))

    # Höchste Temperatur je Tag
    if system.get("temp") is not None:
        day, temp = now.date().isoformat(), round(system["temp"], 1)
        old = state["temp"].get(day)
        if old is None or temp >= old + TEMP_STEP:
            state["temp"][day] = temp

    # Unterspannung: gerade jetzt (höchstens alle 6 h neu) oder seit dem Start und noch nicht notiert
    volt = system.get("volt") or {}
    last_volt = max((_t(v) for v in state["volt"]), default=None)
    if volt.get("now") and (last_volt is None or now - last_volt >= VOLT_REPEAT):
        state["volt"].append(_iso(now))
    elif volt.get("since_boot") and boot and (last_volt is None or last_volt < boot):
        state["volt"].append(_iso(now))

    # Ausfälle der Statusanzeige als Abschnitte (Quelle, Beginn, letzter Fehlschlag, Ende)
    seen = set()
    for src, (since, last) in outages.items():
        ep = next((e for e in state["episodes"] if e["src"] == src and e["start"] == _iso(since)), None)
        if ep is None:
            ep = {"src": src, "start": _iso(since), "last": _iso(last)}
            state["episodes"].append(ep)
        elif ep.get("last") != _iso(last) or "end" in ep:
            ep["last"] = _iso(last)
            ep.pop("end", None)
        seen.add(id(ep))
    for ep in state["episodes"]:
        if "end" not in ep and id(ep) not in seen:
            last = _t(ep["last"])
            ep["end"] = _iso(now if now - last <= CLOSE_GAP else last)

    # Altes vergessen
    cut = now - KEEP
    state["episodes"] = [e for e in state["episodes"] if _t(e.get("end") or e["last"]) >= cut]
    state["temp"] = {d: v for d, v in state["temp"].items() if d >= cut.date().isoformat()}
    state["boots"] = [b for b in state["boots"] if _t(b) >= cut]
    state["volt"] = [v for v in state["volt"] if _t(v) >= cut]
    changed = json.dumps(state, sort_keys=True) != before

    if changed:
        save(path, state)
    return changed


# ----------------------------------------------------------------------
# Text
# ----------------------------------------------------------------------
def when_text(dt, now):
    """„heute 3:10“, „gestern 22:40“, sonst „Do 3:10“."""
    hm = f"{dt.hour}:{dt.minute:02d}"
    days = (now.date() - dt.date()).days
    if days <= 0:
        return f"heute {hm}"
    if days == 1:
        return f"gestern {hm}"
    return f"{KURZ[dt.weekday()]} {hm}"


def duration_text(delta):
    minutes = round(delta.total_seconds() / 60)
    if minutes < 1:
        return "kurz"
    if minutes < 60:
        return f"{minutes} min"
    hours, rest = divmod(minutes, 60)
    if hours < 24:
        return f"{hours} Std." + (f" {rest} min" if rest and hours < 3 else "")
    days = round(hours / 24)
    return f"{days} Tag{'e' if days != 1 else ''}"


def online_text(uptime):
    days = int(uptime // 86400)
    if days >= 1:
        return f"{days} Tag{'e' if days != 1 else ''} online"
    hours = int(uptime // 3600)
    return f"{hours} Std. online" if hours >= 1 else f"{int(uptime // 60)} min online"


def free_text(free):
    gb = free / 1e9
    return (f"{gb:.0f}" if gb >= 10 else f"{gb:.1f}".replace(".", ",")) + " GB frei"


def _names(names):
    """„Wetter“, „Wetter und Kalender“, „Wetter, Kalender und Radar“."""
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " und " + names[-1]


def summary(now, state, system):
    """(Probleme, ruhige Werte) als Textlisten."""
    since = now - WINDOW
    problems = []

    volt = sorted(_t(v) for v in state["volt"] if _t(v) >= since)
    if volt:
        # Wann genau, weiß der Pi nur ungefähr (Bit 16 = irgendwann seit dem Start) – deshalb der Rat statt einer Uhrzeit
        problems.append("Unterspannung (Netzteil prüfen)" if len(volt) == 1
                        else f"Unterspannung {len(volt)}× (Netzteil prüfen)")

    boots = sorted(_t(b) for b in state["boots"] if _t(b) >= since)
    if boots:
        problems.append(f"Neustart {when_text(boots[-1], now)}" if len(boots) == 1
                        else f"{len(boots)} Neustarts, zuletzt {when_text(boots[-1], now)}")

    by_src = {}
    for e in state["episodes"]:
        start, end = _t(e["start"]), _t(e.get("end") or e["last"])
        if end < since:
            continue
        by_src.setdefault(e["src"], []).append((start, end - start))
    # Quellen mit denselben Ausfällen (gleicher Beginn auf 5 Minuten) zusammenfassen – fällt das WLAN aus,
    # scheitern Wetter und Kalender zugleich, und die Zeile hieße sonst zweimal dasselbe
    groups = {}
    for src, eps in by_src.items():
        key = tuple(sorted(round(st.timestamp() / 300) for st, _ in eps))
        groups.setdefault(key, []).append((src, eps))
    rows = []
    for members in groups.values():
        names = [m[0] for m in members]
        eps = max((m[1] for m in members), key=lambda e: sum((d for _, d in e), timedelta()))
        total = sum((d for _, d in eps), timedelta())
        rows.append((total, _names(names), eps))
    for total, name, eps in sorted(rows, key=lambda r: -r[0]):
        latest = max(st for st, _ in eps)
        if len(eps) == 1:
            problems.append(f"{name} 1× weg ({when_text(latest, now)}, {duration_text(total)})")
        else:
            problems.append(f"{name} {len(eps)}× weg ({duration_text(total)}, zuletzt {when_text(latest, now)})")

    facts = []
    if system.get("uptime") is not None:
        facts.append(online_text(system["uptime"]))
    temps = [v for d, v in state["temp"].items() if d >= since.date().isoformat()]
    if system.get("temp") is not None:
        temps.append(system["temp"])
    if temps:
        facts.append(f"bis {round(max(temps))} °C")
    if system.get("free") is not None:
        facts.append(free_text(system["free"]))
    return problems, facts


def line(now, path):
    """Text der Fußzeile ohne „Pi:“ (das setzt das Template fett davor)."""
    state = load(path) if path else empty()
    system = _last_system if _last_system is not None else read_system()
    problems, facts = summary(now, state, system)
    if not problems:
        facts.append("Woche ohne Ausfälle")
    return " · ".join(problems + facts)
