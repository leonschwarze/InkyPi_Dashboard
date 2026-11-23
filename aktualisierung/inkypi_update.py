#!/usr/bin/python3
"""Signierte Updates für das Tagesdashboard und das Ausschaltbild (seit 1.44).

Auf den Pi kommt nur, was Leon mit seinem SSH-Schlüssel freigegeben hat: ein signiertes Git-Tag `v<Version>`
in InkyPi_Dashboard bzw. InkyPi_Ausschaltbild. Der Pi kennt nur den öffentlichen Schlüssel
(/usr/local/inkypi-update/allowed_signers).

    sudo inkypi-update                 freigegebene neue Versionen prüfen und installieren
    sudo inkypi-update --pruefen       nur nachsehen, nichts ändern
    sudo inkypi-update --nur ausschaltbild
    sudo inkypi-update --nur tagesdashboard --version v1.42    bewusst eine (ältere) freigegebene Version
    sudo inkypi-update --verlauf       die letzten Einträge
    (nachts: inkypi-update.timer startet `--nachts`)

Ablauf je Teil:
  1. Tags im Repo auflisten (`git ls-remote`), nur `v<Zahlen>` und höher als installiert.
  2. Von oben nach unten: Tag holen, Signatur mit ssh-keygen gegen allowed_signers prüfen, Version aus dem
     *Inneren* des Tag-Objekts lesen (muss zum Namen passen) und mit der Version im Code vergleichen.
     Das erste Tag, das alles besteht, wird genommen – ein falsches Tag kann also nichts blockieren.
  3. Genau diesen Stand entpacken (`git archive <tag>`), vorab testen (Import bzw. Probebild).
  4. Tauschen (alter Stand bleibt als Sicherung), InkyPi neu starten, Dashboard einmal zeichnen lassen.
     Klappt das nicht, kommt der alte Stand zurück. Nachts wird eine Version höchstens dreimal versucht.

Nur Python-Standardbibliothek, läuft mit /usr/bin/python3 (nicht mit InkyPis venv – das soll ein Update
überstehen können). Braucht `git` und `ssh-keygen` (OpenSSH ≥ 8.2).
"""

import argparse
import contextlib
import fcntl
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

PROGRAMM_VERSION = "1.1"

# Feste Einstellungen. Bewusst keine Datei, die man nebenbei ändern könnte: Woher Updates kommen und wem
# vertraut wird, steht hier und in allowed_signers (nur root). --konfig gibt es nur für die Tests.
STANDARD = {
    "basis": "/usr/local/inkypi-update",          # dieses Skript, allowed_signers, Dienst-Dateien
    "daten": "/var/lib/inkypi-update",            # Spiegel der Repos, Sicherungen, stand.json, verlauf.txt
    "inkypi": "/usr/local/inkypi",                # InkyPi (src ist ein Link auf den Klon)
    "ausschaltbild_ziel": "/usr/local/inkypi-ausschaltbild",
    "systemd": "/etc/systemd/system",
    "web": "http://127.0.0.1:80",
    "repos": {
        "tagesdashboard": "https://github.com/leonschwarze/InkyPi_Dashboard",
        "ausschaltbild": "https://github.com/leonschwarze/InkyPi_Ausschaltbild",
    },
    "neustart": ["systemctl", "restart", "inkypi.service"],
    "warte_web_s": 180,         # bis InkyPi nach dem Neustart antwortet
    "zeichnen_s": 300,          # Dashboard einmal zeichnen (Chromium auf dem Pi ist langsam)
    "zeichnen_versuche": 3,
    "zeichnen_pause_s": 60,
}

TEILE = ("tagesdashboard", "ausschaltbild")
NAMEN = {"tagesdashboard": "Dashboard", "ausschaltbild": "Ausschaltbild"}
TAG_RE = re.compile(r"^v(\d{1,4}(?:\.\d{1,4}){0,3})$")
SIG_START = b"-----BEGIN SSH SIGNATURE-----"
MAX_VERSUCHE_NACHTS = 3
MAX_KANDIDATEN = 5
VERLAUF_ZEILEN = 300


class Abbruch(Exception):
    """Erwarteter Fehler mit deutscher Meldung (kein Traceback nötig)."""


# ---------------------------------------------------------------------------------------------------------------
# Hilfen

class Lauf:
    def __init__(self, cfg):
        self.cfg = cfg
        self.basis = Path(cfg["basis"])
        self.daten = Path(cfg["daten"])
        self.signers = self.basis / "allowed_signers"
        self.stand_datei = self.daten / "stand.json"
        self.verlauf_datei = self.daten / "verlauf.txt"
        self._zeilen = []
        self.kurz = []      # Ergebnis je Teil in wenigen Worten (für die Einstellungsseite des Dashboards)

    def log(self, text):
        zeile = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {text}"
        print(text, flush=True)
        self._zeilen.append(zeile)

    def verlauf_schreiben(self):
        if not self._zeilen:
            return
        try:
            alt = self.verlauf_datei.read_text(encoding="utf-8").splitlines() if self.verlauf_datei.exists() else []
            zeilen = (alt + self._zeilen)[-VERLAUF_ZEILEN:]
            self.verlauf_datei.write_text("\n".join(zeilen) + "\n", encoding="utf-8")
        except OSError as exc:
            print(f"Verlauf nicht geschrieben: {exc}", file=sys.stderr)

    # -- Stand (was installiert ist, Fehlversuche) --
    def stand(self):
        try:
            return json.loads(self.stand_datei.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except ValueError:
            raise Abbruch(f"{self.stand_datei} ist beschädigt – bitte ansehen oder löschen.")

    def stand_speichern(self, daten):
        tmp = self.stand_datei.with_suffix(".tmp")
        tmp.write_text(json.dumps(daten, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, self.stand_datei)


def run(cmd, *, cwd=None, eingabe=None, pruefen=True, zeit=600, env=None, name=None):
    """Befehl ausführen; bei Fehler Abbruch mit der letzten Zeile der Ausgabe."""
    r = subprocess.run(cmd, cwd=cwd, input=eingabe, capture_output=True, timeout=zeit, env=env)
    if pruefen and r.returncode != 0:
        fehler = (r.stderr or r.stdout).decode("utf-8", "replace").strip().splitlines()
        raise Abbruch(f"{name or Path(str(cmd[0])).name}: {fehler[-1] if fehler else f'Exit {r.returncode}'}")
    return r


def git(*args, repo=None, klon=None, **kw):
    # Eigene Einstellungen des Nutzers/Systems sollen hier nichts beeinflussen (z. B. ein anderes gpg.ssh.program).
    # safe.directory: install.sh läuft als root in einem Klon, der Leon gehört – Git würde das sonst ablehnen.
    env = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null", GIT_TERMINAL_PROMPT="0",
               LC_ALL="C")
    cmd = ["git", "-c", "safe.directory=*"]
    if repo:
        cmd += ["--git-dir", str(repo)]
    if klon:
        cmd += ["-C", str(klon)]
    befehl = next((a for a in args if not a.startswith("-") and "=" not in a), "")
    return run(cmd + list(args), env=env, name=f"git {befehl}", **kw)


def version_tupel(text):
    return tuple(int(x) for x in text.split("."))


def version_text(tupel):
    return ".".join(map(str, tupel))


# ---------------------------------------------------------------------------------------------------------------
# Vertrauen: allowed_signers und Signatur

def nur_root_schreibbar(pfad):
    """Datei bzw. Ordner gehört root und ist für niemand sonst beschreibbar – sonst könnte jemand ohne
    root-Rechte einen eigenen Schlüssel eintragen."""
    st = pfad.stat()
    return st.st_uid == 0 and not (st.st_mode & (stat.S_IWGRP | stat.S_IWOTH))


def signers_pruefen(lauf, streng=True):
    if not lauf.signers.is_file():
        raise Abbruch(f"{lauf.signers} fehlt – ohne deinen öffentlichen Schlüssel wird nichts installiert "
                      f"(einrichten: sudo bash aktualisierung/install.sh --schluessel \"ssh-ed25519 …\").")
    if streng:
        for p in (lauf.signers, lauf.signers.parent):
            if not nur_root_schreibbar(p):
                raise Abbruch(f"{p} darf nur root gehören und nur von root beschreibbar sein "
                              f"(sudo chown root:root {p} && sudo chmod go-w {p}).")
    zeilen = [z for z in lauf.signers.read_text(encoding="utf-8").splitlines() if z.strip() and not z.startswith("#")]
    if not zeilen:
        raise Abbruch(f"{lauf.signers} enthält keinen Schlüssel.")


def tag_pruefen(lauf, repo, name):
    """Signatur und Inhalt des Tag-Objekts `name` prüfen. Gibt (version_tupel, commit, unterzeichner) zurück."""
    art = git("cat-file", "-t", f"refs/tags/{name}", repo=repo).stdout.decode().strip()
    if art != "tag":
        raise Abbruch("kein signiertes Tag (nur ein einfacher Verweis auf einen Commit)")
    roh = git("cat-file", "tag", f"refs/tags/{name}", repo=repo).stdout
    pos = roh.find(SIG_START)
    if pos < 0:
        raise Abbruch("nicht signiert")
    nutzdaten, signatur = roh[:pos], roh[pos:]

    kopf = {}
    for zeile in nutzdaten.split(b"\n\n", 1)[0].decode("utf-8", "replace").splitlines():
        k, _, v = zeile.partition(" ")
        kopf.setdefault(k, v)
    if kopf.get("type") != "commit":
        raise Abbruch(f"zeigt nicht auf einen Commit ({kopf.get('type')})")
    # Die Version steht im signierten Inneren. Der Name, unter dem das Tag auf GitHub liegt, ist nicht
    # unterschrieben – ein altes, gültig signiertes Tag könnte sonst unter neuem Namen wiederkommen.
    if kopf.get("tag") != name:
        raise Abbruch(f"heißt innen „{kopf.get('tag')}“, liegt aber als „{name}“ im Repo")
    m = TAG_RE.match(kopf.get("tag", ""))
    if not m:
        raise Abbruch("kein Versions-Tag")

    with tempfile.TemporaryDirectory() as tmp:
        sig = Path(tmp) / "sig"
        sig.write_bytes(signatur)
        # Wer hat unterschrieben? (nur Schlüssel aus allowed_signers, Namensraum "git" wie bei git tag -s)
        r = run(["ssh-keygen", "-Y", "find-principals", "-f", str(lauf.signers), "-s", str(sig)], pruefen=False)
        namen = [z.strip() for z in r.stdout.decode("utf-8", "replace").splitlines() if z.strip()]
        if r.returncode != 0 or not namen:
            raise Abbruch("Signatur von einem unbekannten Schlüssel")
        wer = namen[0]
        r = run(["ssh-keygen", "-Y", "verify", "-f", str(lauf.signers), "-I", wer, "-n", "git", "-s", str(sig)],
                eingabe=nutzdaten, pruefen=False)
        if r.returncode != 0:
            raise Abbruch("Signatur ungültig")
    return version_tupel(m.group(1)), kopf["object"], wer


def inhalt_version(repo, teil, commit):
    """Version, die im Code selbst steht – schützt davor, versehentlich den falschen Stand freizugeben."""
    if teil == "tagesdashboard":
        text = git("show", f"{commit}:tagesdashboard/plugin-info.json", repo=repo, pruefen=False).stdout
        try:
            return json.loads(text).get("version")
        except ValueError:
            return None
    text = git("show", f"{commit}:ausschaltbild/ausschaltbild.py", repo=repo, pruefen=False).stdout
    m = re.search(rb'^VERSION = "([0-9.]+)"', text, re.M)
    return m.group(1).decode() if m else None


# ---------------------------------------------------------------------------------------------------------------
# Repos

def spiegel(lauf, teil):
    repo = lauf.daten / f"{teil}.git"
    url = lauf.cfg["repos"][teil]
    if not repo.exists():
        git("init", "--bare", "-q", str(repo))
        git("remote", "add", "origin", url, repo=repo)
    else:
        git("remote", "set-url", "origin", url, repo=repo)
    return repo


def tags_im_repo(lauf, repo):
    r = git("ls-remote", "--tags", "--refs", "origin", repo=repo, zeit=120)
    tags = []
    for zeile in r.stdout.decode("utf-8", "replace").splitlines():
        ref = zeile.split("\t")[-1]
        name = ref.removeprefix("refs/tags/")
        m = TAG_RE.match(name)
        if m:
            tags.append((version_tupel(m.group(1)), name))
    return sorted(tags, reverse=True)


def tag_holen(repo, name):
    # Erst entfernen: Ein lokal schon vorhandenes Tag gleichen Namens darf das Ergebnis nicht verfälschen.
    git("update-ref", "-d", f"refs/tags/{name}", repo=repo, pruefen=False)
    git("-c", "transfer.fsckObjects=true", "fetch", "-q", "--depth", "1", "--no-tags", "origin", f"+refs/tags/{name}:refs/tags/{name}",
        repo=repo, zeit=300)


def freigegebene_version(lauf, teil, *, mindestens=None, genau=None, auslassen=()):
    """Höchste freigegebene Version (> mindestens) bzw. genau die gewünschte. Gibt dict oder None zurück."""
    repo = spiegel(lauf, teil)
    kandidaten = tags_im_repo(lauf, repo)
    if genau:
        kandidaten = [k for k in kandidaten if k[1] == genau]
        if not kandidaten:
            raise Abbruch(f"{teil}: Tag {genau} gibt es im Repo nicht")
    elif mindestens:
        kandidaten = [k for k in kandidaten if k[0] > mindestens]
    kandidaten = [k for k in kandidaten if k[1] not in auslassen]
    for _, name in kandidaten[:MAX_KANDIDATEN]:
        try:
            tag_holen(repo, name)
            version, commit, wer = tag_pruefen(lauf, repo, name)
            im_code = inhalt_version(repo, teil, commit)
            if im_code != version_text(version):
                raise Abbruch(f"im Code steht Version {im_code or '–'}")
            return {"tag": name, "version": version, "commit": commit, "wer": wer, "repo": repo}
        except Abbruch as exc:
            lauf.log(f"  WARNUNG {teil} {name} abgelehnt: {exc}")
    return None


def entpacken(repo, commit, ordner, ziel):
    """Genau den signierten Commit entpacken (nicht main, nicht ein Arbeitsverzeichnis)."""
    ziel.mkdir(parents=True)
    tar = git("archive", "--format=tar", commit, *ordner, repo=repo).stdout
    with tempfile.TemporaryFile() as f:
        f.write(tar)
        f.seek(0)
        with tarfile.open(fileobj=f) as t:
            # Nur normale Dateien und Ordner innerhalb des Ziels (keine Links, keine absoluten Pfade, kein „..“).
            # Von Hand statt extractall(filter="data"): Raspberry Pi OS Bookworm hat Python 3.11.2, der Filter
            # kam erst mit 3.11.4.
            for m in t.getmembers():
                teile = Path(m.name).parts
                if m.name.startswith("/") or ".." in teile or not teile or teile[0] not in ordner:
                    raise Abbruch(f"ungültiger Pfad im Archiv: {m.name}")
                pfad = ziel.joinpath(*teile)
                if m.isdir():
                    pfad.mkdir(parents=True, exist_ok=True)
                elif m.isfile():
                    pfad.parent.mkdir(parents=True, exist_ok=True)
                    with t.extractfile(m) as quelle, open(pfad, "wb") as aus:
                        shutil.copyfileobj(quelle, aus)
                    os.chmod(pfad, 0o755 if m.mode & 0o111 else 0o644)
                elif m.type == tarfile.XGLTYPE or m.type == tarfile.XHDTYPE:
                    continue
                else:
                    raise Abbruch(f"nicht erlaubter Eintrag im Archiv: {m.name}")


# ---------------------------------------------------------------------------------------------------------------
# InkyPi

def inkypi_pfade(lauf):
    src = Path(os.path.realpath(Path(lauf.cfg["inkypi"]) / "src"))
    return {
        "src": src,
        "plugins": src / "plugins",
        "device": Path(lauf.cfg.get("device_json") or src / "config" / "device.json"),
        "python": Path(lauf.cfg["inkypi"]) / "venv_inkypi" / "bin" / "python",
    }


VORTEST = r"""
import importlib, json, sys
src, eltern, pid = sys.argv[1:4]
sys.path.insert(0, src)
import plugins
plugins.__path__.insert(0, eltern)      # neuer Stand verdeckt den installierten, genau wie InkyPi lädt
info = json.load(open(f"{eltern}/{pid}/plugin-info.json", encoding="utf-8"))
m = importlib.import_module(f"plugins.{pid}.{pid}")
assert m.__file__.startswith(eltern), m.__file__
if getattr(m, "IMPORT_ERROR", None):
    raise SystemExit(f"Bausteine nicht ladbar: {m.IMPORT_ERROR!r}")
getattr(m, info["class"])(info)
print("ok")
"""


def vortest_dashboard(lauf, neu):
    p = inkypi_pfade(lauf)
    r = run([str(p["python"]), "-c", VORTEST, str(p["src"]), str(neu), "tagesdashboard"], cwd=str(p["src"]),
            pruefen=False, zeit=300)
    if r.returncode != 0:
        fehler = (r.stderr or r.stdout).decode("utf-8", "replace").strip().splitlines()
        raise Abbruch(f"Vortest: {fehler[-1] if fehler else r.returncode}")


def web_bereit(lauf, frist):
    ende = time.monotonic() + frist
    while time.monotonic() < ende:
        try:
            with urllib.request.urlopen(lauf.cfg["web"] + "/", timeout=5):
                return True
        except (urllib.error.URLError, OSError):
            time.sleep(2)
    return False


def dashboard_instanz(lauf):
    """Erste Playlist-Instanz des Dashboards aus device.json (oder None)."""
    try:
        dev = json.loads(inkypi_pfade(lauf)["device"].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    for pl in (dev.get("playlist_config") or {}).get("playlists", []):
        for inst in pl.get("plugins", []):
            if inst.get("plugin_id") == "tagesdashboard":
                return {"playlist_name": pl.get("name"), "plugin_id": "tagesdashboard",
                        "plugin_instance": inst.get("name")}
    return None


def ausschaltbild_start_abwarten():
    """Das Ausschaltbild zeichnet nach jedem Start selbst neu – erst danach zeichnen wir, sonst kreuzen sich
    die beiden Aufträge in InkyPi."""
    for _ in range(150):
        r = subprocess.run(["systemctl", "is-active", "inkypi-ausschaltbild-start.service"],
                           capture_output=True, text=True)
        if r.stdout.strip() not in ("active", "activating"):
            return
        time.sleep(2)


def dashboard_zeichnen(lauf):
    """InkyPi neu starten lassen und das Dashboard einmal zeichnen. Gibt (ok, meldung) zurück."""
    try:
        run(lauf.cfg["neustart"], zeit=120)
    except (Abbruch, subprocess.TimeoutExpired) as exc:
        return False, f"Neustart von InkyPi fehlgeschlagen: {exc}"
    if not web_bereit(lauf, lauf.cfg["warte_web_s"]):
        return False, "InkyPi antwortet nach dem Neustart nicht"
    instanz = dashboard_instanz(lauf)
    if not instanz:
        return True, "InkyPi läuft (keine Dashboard-Instanz in der Playlist, Bild nicht geprüft)"
    if shutil.which("systemctl"):
        ausschaltbild_start_abwarten()
    meldung = ""
    for versuch in range(1, lauf.cfg["zeichnen_versuche"] + 1):
        anfrage = urllib.request.Request(lauf.cfg["web"] + "/display_plugin_instance",
                                         data=json.dumps(instanz).encode(), method="POST",
                                         headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(anfrage, timeout=lauf.cfg["zeichnen_s"]) as r:
                if json.loads(r.read() or b"{}").get("success"):
                    return True, "Dashboard gezeichnet"
                meldung = "unerwartete Antwort"
        except urllib.error.HTTPError as exc:
            try:
                meldung = json.loads(exc.read()).get("error") or f"HTTP {exc.code}"
            except ValueError:
                meldung = f"HTTP {exc.code}"
        except (urllib.error.URLError, OSError) as exc:
            meldung = str(exc)
        if versuch < lauf.cfg["zeichnen_versuche"]:
            lauf.log(f"  Zeichnen fehlgeschlagen ({meldung[:160]}), neuer Versuch in {lauf.cfg['zeichnen_pause_s']} s")
            time.sleep(lauf.cfg["zeichnen_pause_s"])
    return False, meldung[:300]


# ---------------------------------------------------------------------------------------------------------------
# Installieren

def installiere_dashboard(lauf, frei, arbeit):
    neu = arbeit / "neu"
    entpacken(frei["repo"], frei["commit"], ["tagesdashboard", "aktualisierung"], neu)
    vortest_dashboard(lauf, neu)
    lauf.log("  Vortest ok (Plugin lädt)")

    ziel = inkypi_pfade(lauf)["plugins"] / "tagesdashboard"
    sicherung = lauf.daten / "sicherung" / "tagesdashboard"
    if sicherung.exists():
        shutil.rmtree(sicherung)
    sicherung.parent.mkdir(parents=True, exist_ok=True)
    hatte_alt = ziel.exists()
    if hatte_alt:
        shutil.move(str(ziel), str(sicherung))
    shutil.move(str(neu / "tagesdashboard"), str(ziel))
    ok, meldung = dashboard_zeichnen(lauf)
    if ok:
        lauf.log(f"  {meldung}")
        if (neu / "aktualisierung").is_dir():
            selbst_aktualisieren(lauf, neu / "aktualisierung")
        return
    lauf.log(f"  FEHLER mit der neuen Version: {meldung}")
    if not hatte_alt:
        raise Abbruch("neue Version läuft nicht, und es gab keinen alten Stand – bitte von Hand ansehen")
    kaputt = lauf.daten / "fehlgeschlagen" / "tagesdashboard"
    if kaputt.exists():
        shutil.rmtree(kaputt)
    kaputt.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(ziel), str(kaputt))
    shutil.move(str(sicherung), str(ziel))
    ok2, meldung2 = dashboard_zeichnen(lauf)
    lauf.log(f"  Rückfall auf den alten Stand: {meldung2}")
    raise Abbruch(f"neue Version zurückgenommen ({meldung})")


AUS_DATEIEN = ["ausschaltbild.py", "eink.py"]
AUS_DIENSTE = ["inkypi-ausschaltbild.service", "inkypi-ausschaltbild-start.service"]


def installiere_ausschaltbild(lauf, frei, arbeit):
    p = inkypi_pfade(lauf)
    neu = arbeit / "neu"
    entpacken(frei["repo"], frei["commit"], ["ausschaltbild"], neu)
    probe = arbeit / "probe.png"
    r = run([str(p["python"]), str(neu / "ausschaltbild" / "ausschaltbild.py"), "--png", str(probe),
             "--size", "800x480"], pruefen=False, zeit=300)
    if r.returncode != 0 or not probe.is_file():
        fehler = (r.stderr or r.stdout).decode("utf-8", "replace").strip().splitlines()
        raise Abbruch(f"Vortest: {fehler[-1] if fehler else r.returncode}")
    lauf.log("  Vortest ok (Probebild erzeugt)")

    ziel = Path(lauf.cfg["ausschaltbild_ziel"])
    sicherung = lauf.daten / "sicherung" / "ausschaltbild"
    if sicherung.exists():
        shutil.rmtree(sicherung)
    sicherung.mkdir(parents=True)
    for n in AUS_DATEIEN:
        if (ziel / n).exists():
            shutil.copy2(ziel / n, sicherung / n)
    for n in AUS_DIENSTE:
        if (Path(lauf.cfg["systemd"]) / n).exists():
            shutil.copy2(Path(lauf.cfg["systemd"]) / n, sicherung / n)

    r = run(["bash", str(neu / "ausschaltbild" / "install.sh")], pruefen=False, zeit=300)
    ausgabe = (r.stdout + r.stderr).decode("utf-8", "replace").strip().splitlines()
    if r.returncode == 0:
        lauf.log("  install.sh ok")
        return
    lauf.log(f"  FEHLER in install.sh: {ausgabe[-1] if ausgabe else r.returncode}")
    for n in AUS_DATEIEN:
        if (sicherung / n).exists():
            shutil.copy2(sicherung / n, ziel / n)
    for n in AUS_DIENSTE:
        if (sicherung / n).exists():
            shutil.copy2(sicherung / n, Path(lauf.cfg["systemd"]) / n)
    run(["systemctl", "daemon-reload"], pruefen=False)
    lauf.log("  Rückfall auf den alten Stand")
    raise Abbruch("neue Version zurückgenommen")


SELBST_DATEIEN = {"inkypi_update.py": 0o755, "inkypi-update.service": 0o644, "inkypi-update.timer": 0o644}


def selbst_aktualisieren(lauf, quelle):
    """Den Updater selbst aus demselben signierten Stand erneuern (nie allowed_signers)."""
    geaendert = [n for n in SELBST_DATEIEN if (quelle / n).is_file() and (not (lauf.basis / n).is_file()
                 or (quelle / n).read_bytes() != (lauf.basis / n).read_bytes())]
    if not geaendert:
        return
    if "inkypi_update.py" in geaendert:
        run([sys.executable, "-m", "py_compile", str(quelle / "inkypi_update.py")])
    for n in geaendert:
        tmp = lauf.basis / (n + ".neu")
        shutil.copyfile(quelle / n, tmp)
        os.chmod(tmp, SELBST_DATEIEN[n])
        os.replace(tmp, lauf.basis / n)
        if n.endswith((".service", ".timer")) and Path(lauf.cfg["systemd"]).is_dir():
            shutil.copyfile(lauf.basis / n, Path(lauf.cfg["systemd"]) / n)
    if any(n.endswith((".service", ".timer")) for n in geaendert) and shutil.which("systemctl"):
        run(["systemctl", "daemon-reload"], pruefen=False)
    lauf.log(f"  Updater erneuert: {', '.join(geaendert)}")


def installiert(lauf, teil, stand):
    """Installierte Version (Tupel) oder None, wenn der Teil nicht da ist bzw. noch nie per Update kam."""
    if teil == "ausschaltbild" and not (Path(lauf.cfg["ausschaltbild_ziel"]) / "ausschaltbild.py").exists():
        return "fehlt"
    v = (stand.get(teil) or {}).get("version")
    return version_tupel(v) if v else None


def teil_bearbeiten(lauf, teil, args, stand):
    vorher = installiert(lauf, teil, stand)
    name = NAMEN.get(teil, teil)
    if vorher == "fehlt":
        lauf.log(f"{teil}: nicht installiert – übersprungen")
        return False
    eintrag = stand.setdefault(teil, {})
    vorher_text = version_text(vorher) if vorher else "unbekannt (noch nie per Update)"
    fehl = stand.setdefault("fehlversuche", {}).setdefault(teil, {})
    auslassen = [t for t, n in fehl.items() if n >= MAX_VERSUCHE_NACHTS] if args.nachts else []
    frei = freigegebene_version(lauf, teil, mindestens=vorher, genau=args.version, auslassen=auslassen)
    if not frei:
        hinweis = f" (nachts ausgelassen nach {MAX_VERSUCHE_NACHTS} Fehlversuchen: {', '.join(auslassen)})" if auslassen else ""
        lauf.log(f"{teil}: installiert {vorher_text}, keine neuere freigegebene Version{hinweis}")
        eintrag.pop("bereit", None)
        lauf.kurz.append(f"{name} aktuell")
        return False
    neu_text = version_text(frei["version"])
    lauf.log(f"{teil}: installiert {vorher_text}, freigegeben {frei['tag']} "
             f"(Commit {frei['commit'][:7]}, signiert von {frei['wer']})")
    if args.pruefen:
        eintrag["bereit"] = frei["tag"]
        lauf.kurz.append(f"{name}: {frei['tag']} liegt bereit")
        return False
    if vorher and frei["version"] < vorher:
        lauf.log(f"  ACHTUNG: {frei['tag']} ist älter als die installierte Version {vorher_text} (bewusst gewählt)")
    arbeit = Path(tempfile.mkdtemp(prefix=f"{teil}-", dir=lauf.daten))
    try:
        if teil == "tagesdashboard":
            installiere_dashboard(lauf, frei, arbeit)
        else:
            installiere_ausschaltbild(lauf, frei, arbeit)
    except Abbruch:
        fehl[frei["tag"]] = fehl.get(frei["tag"], 0) + 1
        raise
    finally:
        shutil.rmtree(arbeit, ignore_errors=True)
    fehl.pop(frei["tag"], None)
    stand[teil] = {"version": neu_text, "tag": frei["tag"], "commit": frei["commit"], "signiert_von": frei["wer"],
                   "installiert": datetime.now().isoformat(timespec="seconds")}
    lauf.log(f"{teil}: {frei['tag']} installiert")
    lauf.kurz.append(f"{name}: {frei['tag']} installiert")
    return True


# ---------------------------------------------------------------------------------------------------------------
# Selbstprüfung bei der Einrichtung (install.sh): Ist der Klon, aus dem installiert wird, ein signiertes Tag?

def klon_pruefen(lauf, klon):
    klon = Path(klon)
    gitdir = klon / ".git"
    r = git("describe", "--tags", "--exact-match", "HEAD", klon=klon, pruefen=False)
    name = r.stdout.decode().strip()
    if r.returncode != 0 or not TAG_RE.match(name):
        raise Abbruch("Der Klon steht nicht auf einem Versions-Tag (git clone --branch v… verwenden).")
    version, commit, wer = tag_pruefen(lauf, gitdir, name)
    head = git("rev-parse", "HEAD", klon=klon).stdout.decode().strip()
    if head != commit:
        raise Abbruch("HEAD passt nicht zum Tag.")
    if git("status", "--porcelain", klon=klon).stdout.strip():
        raise Abbruch("Im Klon wurden Dateien verändert oder hinzugefügt.")
    if inhalt_version(gitdir, "tagesdashboard", commit) != version_text(version):
        raise Abbruch("Version im Code passt nicht zum Tag.")
    lauf.log(f"Klon geprüft: {name} (Commit {commit[:7]}), signiert von {wer}")


# ---------------------------------------------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(prog="inkypi-update", description="Signierte Updates für Tagesdashboard und Ausschaltbild")
    ap.add_argument("--pruefen", action="store_true", help="nur nachsehen, nichts installieren")
    ap.add_argument("--nachts", action="store_true", help="vom Timer: fehlgeschlagene Versionen höchstens dreimal")
    ap.add_argument("--nur", choices=TEILE, help="nur diesen Teil")
    ap.add_argument("--version", metavar="vX.Y", help="genau diese freigegebene Version (mit --nur, auch ältere)")
    ap.add_argument("--verlauf", action="store_true", help="die letzten Einträge zeigen")
    ap.add_argument("--klon-pruefen", metavar="ORDNER", help=argparse.SUPPRESS)   # für install.sh
    ap.add_argument("--konfig", metavar="JSON", help=argparse.SUPPRESS)            # nur für Tests
    args = ap.parse_args(argv)

    cfg = json.loads(json.dumps(STANDARD))
    streng = True
    if args.konfig:
        cfg.update(json.loads(Path(args.konfig).read_text(encoding="utf-8")))
        streng = cfg.pop("streng", True)
    lauf = Lauf(cfg)

    if args.verlauf:
        if lauf.verlauf_datei.exists():
            print("\n".join(lauf.verlauf_datei.read_text(encoding="utf-8").splitlines()[-40:]))
        return 0
    if args.version and not args.nur:
        ap.error("--version braucht --nur tagesdashboard bzw. --nur ausschaltbild")
    if args.version and not TAG_RE.match(args.version):
        ap.error("--version wie v1.43")
    if streng and os.geteuid() != 0:
        print("Bitte mit sudo starten: sudo inkypi-update", file=sys.stderr)
        return 2

    try:
        signers_pruefen(lauf, streng)
        if args.klon_pruefen:
            klon_pruefen(lauf, args.klon_pruefen)
            return 0
        lauf.daten.mkdir(parents=True, exist_ok=True)
        os.chmod(lauf.daten, 0o755)
    except Abbruch as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1

    with open(lauf.daten / "sperre", "w") as sperre:
        try:
            fcntl.flock(sperre, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Es läuft schon ein Update.", file=sys.stderr)
            return 1
        art = "nachts" if args.nachts else ("prüfen" if args.pruefen else "von Hand")
        lauf.log(f"— inkypi-update {PROGRAMM_VERSION} ({art}) —")
        fehler = 0
        try:
            stand = lauf.stand()
            for teil in ([args.nur] if args.nur else TEILE):
                try:
                    teil_bearbeiten(lauf, teil, args, stand)
                except Abbruch as exc:
                    fehler += 1
                    lauf.log(f"{teil}: FEHLER – {exc}")
                    lauf.kurz.append(f"{NAMEN[teil]}: Fehler – {exc}")
                except subprocess.TimeoutExpired as exc:
                    fehler += 1
                    lauf.log(f"{teil}: FEHLER – Zeitüberschreitung bei {exc.cmd[0]}")
                    lauf.kurz.append(f"{NAMEN[teil]}: Zeitüberschreitung")
                finally:
                    with contextlib.suppress(OSError):
                        lauf.stand_speichern(stand)
        except Abbruch as exc:
            fehler += 1
            lauf.log(f"FEHLER – {exc}")
            lauf.kurz.append(str(exc))
        finally:
            # Kurzfassung des Laufs für die Einstellungsseite des Dashboards (seit 1.1 des Updaters)
            with contextlib.suppress(Exception):
                stand = lauf.stand()
                stand["letzter_lauf"] = {"zeit": datetime.now().isoformat(timespec="seconds"), "art": art,
                                         "fehler": fehler, "text": " · ".join(lauf.kurz) or "nichts zu tun"}
                lauf.stand_speichern(stand)
            lauf.verlauf_schreiben()
    return 1 if fehler else 0


if __name__ == "__main__":
    sys.exit(main())
