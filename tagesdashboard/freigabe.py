"""Signierte Updates in den Einstellungen des Dashboards (seit 1.45).

Das Dashboard installiert nichts selbst. Es liest nur, was der Befehl `inkypi-update`
(Ordner aktualisierung/) in /var/lib/inkypi-update/stand.json festhält, und kann einen
Lauf von Hand anstoßen – genau denselben, den man sonst mit `sudo inkypi-update` startet.
Ein Knopf in der Weboberfläche kann also nur Stände installieren, die Leon signiert hat.

Der Knopf läuft über InkyPis `/update_now` (Plugins können keine eigenen Webadressen
anmelden): Die Einstellungsseite schickt nur `inkypiUpdate=jetzt`, `generate_image`
erkennt das ganz am Anfang und ruft `starten()`. Die Antwort ist immer eine
RuntimeError-Meldung – InkyPi zeigt sie an, das Display bleibt dabei unverändert.
"""

import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

STAND = Path("/var/lib/inkypi-update/stand.json")
BEFEHL = Path("/usr/local/bin/inkypi-update")
UNIT = "inkypi-update-jetzt"   # vorübergehende systemd-Einheit, überlebt den Neustart von InkyPi
SCHLUESSEL = "inkypiUpdate"    # Formularfeld des Knopfs
WERT = "jetzt"

ART = {"nachts": "nachts", "prüfen": "nur geprüft", "von Hand": "von Hand"}


def angefordert(settings):
    """Kommt der Aufruf vom Knopf „Jetzt prüfen und installieren“?"""
    return str((settings or {}).get(SCHLUESSEL, "")).strip() == WERT


def _zeit(text):
    """„2026-11-24T03:41:12“ → „24.11. 3:41“."""
    try:
        d = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return ""
    return f"{d.day}.{d.month}. {d.hour}:{d.minute:02d}"


def status(laufend_version, stand_datei=STAND, befehl=BEFEHL):
    """Angaben für die Einstellungsseite. Wirft nie."""
    info = {"eingerichtet": Path(befehl).exists(), "plugin": laufend_version or "?",
            "installiert": None, "lauf": None, "bereit": None, "fremd": False}
    try:
        stand = json.loads(Path(stand_datei).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return info
    teil = stand.get("tagesdashboard") or {}
    if teil.get("version"):
        info["installiert"] = {"version": teil["version"], "von": teil.get("signiert_von", ""),
                               "wann": _zeit(teil.get("installiert"))}
        # Läuft ein anderer Stand als der zuletzt signiert installierte? (z. B. Plugin Manager)
        info["fremd"] = bool(laufend_version) and laufend_version != teil["version"]
    info["bereit"] = teil.get("bereit") or None
    lauf = stand.get("letzter_lauf") or {}
    if lauf.get("zeit"):
        info["lauf"] = {"wann": _zeit(lauf["zeit"]), "art": ART.get(lauf.get("art"), lauf.get("art", "")),
                        "ok": not lauf.get("fehler"), "text": lauf.get("text", "")}
    return info


def starten(befehl=BEFEHL, systemd_run=None):
    """Startet `inkypi-update` als eigene systemd-Einheit und gibt die Meldung für die Weboberfläche zurück.

    Eine eigene Einheit, weil `inkypi-update` InkyPi neu startet – als Kindprozess von InkyPi
    würde es dabei mit beendet.
    """
    if not Path(befehl).exists():
        return False, "Signierte Updates sind auf diesem Pi nicht eingerichtet (siehe README)."
    programm = systemd_run or shutil.which("systemd-run") or "/usr/bin/systemd-run"
    try:
        r = subprocess.run([programm, f"--unit={UNIT}", "--collect", "--quiet",
                            "--description=InkyPi: signiertes Update (von Hand)", str(befehl)],
                           capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"Update konnte nicht gestartet werden ({exc.__class__.__name__})."
    if r.returncode != 0:
        if "already" in (r.stderr or ""):
            return False, "Es läuft schon ein Update."
        return False, f"Update konnte nicht gestartet werden: {(r.stderr or '').strip()[:160]}"
    return True, ("Update gestartet. Gibt es eine neue signierte Version, wird sie geprüft und installiert; "
                  "das Display zeichnet danach neu (1–2 Minuten). Seite danach neu laden.")
