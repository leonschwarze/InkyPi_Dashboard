#!/usr/bin/env bash
# Eine Version freigeben (auf DEINEM Rechner, nicht auf dem Pi):
#
#   bash aktualisierung/freigeben.sh                      im Klon von InkyPi_Dashboard
#   bash aktualisierung/freigeben.sh ~/InkyPi_Ausschaltbild   für das Ausschaltbild (ebenso ~/inkypi_tasten für die Tasten)
#
# Zeigt, was freigegeben würde, fragt nach, signiert das Tag v<Version> mit deinem Freigabe-Schlüssel,
# prüft die Unterschrift und schiebt das Tag zu GitHub. Der Pi holt es nachts (oder: sudo inkypi-update).
# Schlüssel: ~/.ssh/inkypi_freigabe (anderer Ort: INKYPI_SCHLUESSEL=/pfad/zum/schluessel).
set -euo pipefail

SCHLUESSEL="${INKYPI_SCHLUESSEL:-$HOME/.ssh/inkypi_freigabe}"

fehler() { echo "FEHLER: $*" >&2; exit 1; }

# Welcher Klon? Mit Angabe dieser Ordner, sonst der Klon, in dem du gerade stehst (egal in welchem
# Unterordner), sonst der Klon, in dem dieses Skript liegt (InkyPi_Dashboard).
if [ $# -ge 1 ]; then
  cd "$1" 2>/dev/null || fehler "Ordner $1 gibt es nicht"
fi
WURZEL="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "$WURZEL" ]; then
  [ $# -ge 1 ] && fehler "$(pwd) ist kein Git-Klon"
  WURZEL="$(cd "$(dirname "$0")/.." && git rev-parse --show-toplevel 2>/dev/null || true)"
  [ -n "$WURZEL" ] || fehler "kein Git-Klon gefunden – bitte im Klon starten oder den Ordner angeben"
fi
cd "$WURZEL"

[ -f "$SCHLUESSEL.pub" ] || fehler "Freigabe-Schlüssel $SCHLUESSEL.pub fehlt (anlegen: ssh-keygen -t ed25519 -C InkyPi-Freigabe -f $SCHLUESSEL)"

# Nur die drei Repos, die der Pi kennt (nicht InkyPi_Plugin_Dev – dort gäbe es beide Ordner)
HERKUNFT="$(git remote get-url origin 2>/dev/null || true)"
case "$HERKUNFT" in
  *[Ii]nky[Pp]i_[Dd]ashboard|*[Ii]nky[Pp]i_[Dd]ashboard.git|*[Ii]nky[Pp]i_[Dd]ashboard/)
    NAME="Tagesdashboard"
    [ -f tagesdashboard/plugin-info.json ] || fehler "$WURZEL: tagesdashboard/plugin-info.json fehlt"
    VERSION="$(sed -n 's/.*"version" *: *"\([0-9.]*\)".*/\1/p' tagesdashboard/plugin-info.json | head -1)" ;;
  *[Ii]nky[Pp]i_[Aa]usschaltbild|*[Ii]nky[Pp]i_[Aa]usschaltbild.git|*[Ii]nky[Pp]i_[Aa]usschaltbild/)
    NAME="Ausschaltbild"
    [ -f ausschaltbild/ausschaltbild.py ] || fehler "$WURZEL: ausschaltbild/ausschaltbild.py fehlt"
    VERSION="$(sed -n 's/^VERSION = "\([0-9.]*\)".*/\1/p' ausschaltbild/ausschaltbild.py | head -1)" ;;
  *[Ii]nky[Pp]i_[Tt]asten|*[Ii]nky[Pp]i_[Tt]asten.git|*[Ii]nky[Pp]i_[Tt]asten/)
    NAME="Tasten"
    [ -f tasten.py ] || fehler "$WURZEL: tasten.py fehlt"
    VERSION="$(sed -n 's/^VERSION = "\([0-9.]*\)".*/\1/p' tasten.py | head -1)" ;;
  *)
    fehler "$WURZEL ist ein Klon von ${HERKUNFT:-?} – freigegeben werden nur InkyPi_Dashboard, InkyPi_Ausschaltbild und inkypi_tasten" ;;
esac
[ -n "$VERSION" ] || fehler "keine Versionsnummer im Code gefunden"
TAG="v$VERSION"

echo "Hole den Stand von GitHub …"
git fetch -q origin
git fetch -q origin --tags
[ -z "$(git status --porcelain)" ] || fehler "im Klon gibt es Änderungen – bitte erst aufräumen (git status)"
HEAD="$(git rev-parse HEAD)"
ZWEIG="$(git rev-parse origin/HEAD 2>/dev/null || git rev-parse origin/main)"
if [ "$HEAD" != "$ZWEIG" ]; then
  fehler "dein Klon ist nicht auf dem Stand von GitHub – erst  git pull --ff-only"
fi
if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null || [ -n "$(git ls-remote --tags origin "refs/tags/$TAG")" ]; then
  fehler "$TAG gibt es schon. Neue Version? Dann muss sie im Code eine neue Nummer haben."
fi

VORHER="$(git tag -l 'v*' --sort=-v:refname | head -1)"
echo
echo "  $NAME $VERSION   ($(git remote get-url origin))"
git log -1 --format='  Commit   %h  %s%n  von      %an, %ad' --date=format:'%d.%m.%Y %H:%M'
if [ -n "$VORHER" ]; then
  echo "  seit $VORHER: $(git diff --shortstat "$VORHER" HEAD)"
  git log --format='           %h  %s' "$VORHER..HEAD" | head -15
fi
echo
echo "  Stimmt der Commit mit dem überein, den Claude dir genannt hat?"
printf "  Diesen Stand als %s freigeben? [j/N] " "$TAG"
read -r ANTWORT
case "$ANTWORT" in j|J|ja|Ja) ;; *) echo "Abgebrochen, nichts geändert."; exit 0 ;; esac

git -c gpg.format=ssh -c user.signingkey="$SCHLUESSEL.pub" tag -s "$TAG" -m "$NAME $VERSION"

# Selbstkontrolle mit genau den Regeln des Pi
PRUEF="$(mktemp)"
trap 'rm -f "$PRUEF"' EXIT
echo "leon namespaces=\"git\" $(cat "$SCHLUESSEL.pub")" > "$PRUEF"
if ! git -c gpg.format=ssh -c gpg.ssh.allowedSignersFile="$PRUEF" verify-tag "$TAG"; then
  git tag -d "$TAG" >/dev/null
  fehler "Unterschrift lässt sich nicht prüfen – Tag wieder gelöscht"
fi

git push -q origin "refs/tags/$TAG"
echo
echo "Freigegeben: $TAG. Der Pi holt es heute Nacht – oder sofort:  ssh <pi> sudo inkypi-update"
