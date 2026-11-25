"""Tasten am Inky Impression (seit 1.49): Zustandsdatei und Hilfsbild.

Der Tasten-Dienst (Ordner tasten/, ein eigener systemd-Dienst neben InkyPi) liest die vier Tasten und
spricht InkyPi über dessen Weboberfläche an (POST /display_plugin_instance). Das Dashboard weiß dann
aber noch nicht, *warum* es gerade neu zeichnen soll. Das sagt ihm eine kleine Datei neben InkyPis
device.json (STATE_FILE), die der Dienst schreibt und dieses Modul liest:

    {"v": 1, "neu": 7, "hilfe_bis": 1764076800.5}

  neu         Zähler, der mit jedem „Jetzt neu zeichnen“ (Taste A) und jedem Schließen des Hilfsbilds
              um eins steigt. Ändert er sich, überspringt das Dashboard beim nächsten Zeichnen beide
              Bild-Caches – sonst käme „bis zu quietMinutes lang dasselbe Bild“ zurück und der Tastendruck
              bliebe unsichtbar.
  hilfe_bis   Unix-Zeit, bis zu der das Hilfsbild (Taste D) stehen soll; 0 oder in der Vergangenheit =
              kein Hilfsbild.

Warum eine Datei und nicht „Jetzt aktualisieren“: InkyPis Weg für externe Aufrufe,
/display_plugin_instance, ist kein ManualRefresh – `_manual_refresh()` im Dashboard erkennt ihn nicht.

Nachts (Nachtbild) tut das Dashboard nichts: kein Hilfsbild, die Caches bleiben. Der Dienst prüft das
ebenfalls (er liest dafür dieselben Einstellungen), aber maßgeblich ist, was hier steht.

Nach dem Hilfsbild zeichnet das Dashboard einmal frisch (Caches übersprungen), auch wenn die Datei das
nicht eigens verlangt – abgelaufen ist abgelaufen, der Dienst muss dafür nur noch einmal anstoßen.
"""
import json
import logging
import os
import tempfile

logger = logging.getLogger(__name__)

STATE_FILE = "tasten_zustand.json"
HILFE_SEKUNDEN = 180   # so lange steht das Hilfsbild (der Dienst setzt hilfe_bis = jetzt + HILFE_SEKUNDEN);
                       # Zeichnen und Display brauchen davon etwa eine Minute – zu sehen ist es rund zwei

_seen_neu = None       # zuletzt gesehener Zähler (Modulspeicher; nach einem Neustart zählt der erste Blick als neu)
_hilfe_war = False     # beim letzten Zeichnen stand das Hilfsbild → danach einmal frisch zeichnen


def state_path(device_config):
    """Datei neben InkyPis device.json; ohne InkyPi-Konfiguration im Temp-Ordner (wie pizustand)."""
    cfg = getattr(device_config, "config_file", None)
    base = os.path.dirname(cfg) if isinstance(cfg, str) and cfg else tempfile.gettempdir()
    return os.path.join(base, STATE_FILE)


def load(path):
    """Inhalt der Datei oder {} (fehlt, kaputt, kein Wörterbuch) – ein Fehler hier darf nie das Bild kosten."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def check(path, now, night=False):
    """Was haben die Tasten dem Dashboard aufgetragen? -> (hilfe_an, frisch).

    hilfe_an  Hilfsbild statt des Dashboards zeichnen (nie im Nachtbild)
    frisch    Bild-Caches diesmal überspringen (neuer Zähler, oder das Hilfsbild ist gerade vorbei)

    Der Zähler gilt mit diesem Aufruf als gesehen – auch nachts (dann ist der Tastendruck zu spät
    gekommen und wird nicht später nachgeholt)."""
    global _seen_neu, _hilfe_war
    state = load(path)
    neu = state.get("neu")
    frisch = neu is not None and neu != _seen_neu and not night   # nachts bleibt der Cache (das Nachtbild friert ein)
    _seen_neu = neu
    until = state.get("hilfe_bis")
    hilfe = (not night and isinstance(until, (int, float)) and not isinstance(until, bool)
             and now.timestamp() < until)
    if hilfe:
        _hilfe_war = True
        return True, frisch
    if _hilfe_war:
        _hilfe_war = False
        frisch = frisch or not night   # nach dem Hilfsbild einmal frisch zeichnen – nachts gilt wie immer der Cache
    return False, frisch


def reset():
    """Nur für Tests: Modulspeicher zurücksetzen."""
    global _seen_neu, _hilfe_war
    _seen_neu, _hilfe_war = None, False


KEYS = [
    # (Buchstabe, Titel, Zusatz) – Titel None = nicht belegt
    ("A", "Jetzt neu zeichnen", "Holt frische Daten, dauert etwa eine Minute"),
    ("B", None, None),
    ("C", None, None),
    ("D", "Diese Hilfe", f"Noch einmal drücken schließt sie, sonst nach {HILFE_SEKUNDEN // 60} Minuten"),
]


MAX_LANG = 3     # bis zu so vielen Problemen steht die ausführliche Zeile („Kalender 3× weg (1 Std. 20 min, …)“)
MAX_ZEILEN = 4   # darüber nur noch die Kurzformen, höchstens so viele, dann „+ N weitere“


def pi_lines(pi_parts):
    """Zeilen des Kastens „Zustand des Pi“ aus pizustand.parts(): Probleme zuerst, dann die Fakten (online, Temperatur,
    Speicher). Das Hilfsbild hat viel weniger Platz als die Fußzeile der Wochenvorschau und kürzt deshalb nicht
    mit Auslassungspunkten, sondern nimmt bei vielen Problemen die Kurzform und zählt den Rest."""
    parts = pi_parts or []
    problems = [p for p in parts if p.get("kind") == "problem"]
    facts = [p["text"] for p in parts if p.get("kind") != "problem"]
    if len(problems) <= MAX_LANG:
        return [p["text"] for p in problems] + facts
    lines = [p.get("short") or p["text"] for p in problems[:MAX_ZEILEN]]
    if len(problems) > MAX_ZEILEN:
        lines.append(f"+ {len(problems) - MAX_ZEILEN} weitere")
    return lines + facts


def build(version, now, pi_parts, night_text=None):
    """Alles, was das Template fürs Hilfsbild braucht."""
    return {
        "tasten": [{"letter": k, "title": t, "sub": s} for k, t, s in KEYS],
        "version": version or "",
        "stand": f"{now.hour}:{now.minute:02d}",
        "pi": pi_lines(pi_parts),
        "night_text": night_text,
    }


def night_text(night_win):
    """„Im Nachtbild (23:00–6:00 Uhr) ruhen die Tasten.“ – leer, wenn es kein Nachtbild gibt."""
    if not night_win:
        return None
    a, b = night_win
    return f"Im Nachtbild ({a.hour}:{a.minute:02d}–{b.hour}:{b.minute:02d} Uhr) ruhen die Tasten."
