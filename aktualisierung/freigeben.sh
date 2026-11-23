#!/usr/bin/env bash
# Eine Version freigeben (auf DEINEM Rechner, nicht auf dem Pi):
#
#   bash aktualisierung/freigeben.sh                      im Klon von InkyPi_Dashboard
#   bash aktualisierung/freigeben.sh ~/InkyPi_Ausschaltbild   für das Ausschaltbild
#
# Zeigt, was freigegeben würde, fragt nach, signiert das Tag v<Version> mit deinem Freigabe-Schlüssel,
# prüft die Unterschrift und schiebt das Tag zu GitHub. Der Pi holt es nachts (oder: sudo inkypi-update).
# Schlüssel: ~/.ssh/inkypi_freigabe (anderer Ort: INKYPI_SCHLUESSEL=/pfad/zum/schluessel).
set -euo pipefail

SCHLUESSEL="${INKYPI_SCHLUESSEL:-$HOME/.ssh/inkypi_freigabe}"
cd "${1:-.}"

fehler() { echo "FEHLER: $*" >&2; exit 1; }

[ -f "$SCHLUESSEL.pub" ] || fehler "Freigabe-Schlüssel $SCHLUESSEL.pub fehlt (anlegen: ssh-keygen -t ed25519 -C InkyPi-Freigabe -f $SCHLUESSEL)"
git rev-parse --git-dir >/dev/null 2>&1 || fehler "$(pwd) ist kein Git-Klon"

if [ -f tagesdashboard/plugin-info.json ]; then
  NAME="Tagesdashboard"
  VERSION="$(sed -n 's/.*"version" *: *"\([0-9.]*\)".*/\1/p' tagesdashboard/plugin-info.json | head -1)"
elif [ -f ausschaltbild/ausschaltbild.py ]; then
  NAME="Ausschaltbild"
  VERSION="$(sed -n 's/^VERSION = "\([0-9.]*\)".*/\1/p' ausschaltbild/ausschaltbild.py | head -1)"
else
  fehler "weder tagesdashboard/ noch ausschaltbild/ gefunden – im richtigen Klon?"
fi
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
