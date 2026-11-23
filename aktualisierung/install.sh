#!/usr/bin/env bash
# Signierte Updates einrichten (einmalig, auf dem Pi, in einem geprüften Klon von InkyPi_Dashboard):
#
#   sudo bash aktualisierung/install.sh --schluessel "ssh-ed25519 AAAA… InkyPi-Freigabe"
#
# --schluessel        dein ÖFFENTLICHER Freigabe-Schlüssel (Inhalt von ~/.ssh/inkypi_freigabe.pub)
# --schluessel-ersetzen  vorhandenen Schlüssel bewusst austauschen (z. B. nach Verlust)
# --ohne-nachts       kein nächtlicher Lauf, nur  sudo inkypi-update  von Hand
set -euo pipefail

BASIS=/usr/local/inkypi-update
DATEN=/var/lib/inkypi-update
SIGNERS=$BASIS/allowed_signers
PRINZIPAL=leon

SCHLUESSEL=""
ERSETZEN=0
NACHTS=1
while [[ $# -gt 0 ]]; do
  case "$1" in
    --schluessel) SCHLUESSEL="${2:-}"; shift 2 ;;
    --schluessel-ersetzen) ERSETZEN=1; shift ;;
    --ohne-nachts) NACHTS=0; shift ;;
    *) echo "Unbekannte Angabe: $1"; exit 1 ;;
  esac
done

if [[ $EUID -ne 0 ]]; then
  echo "Bitte mit sudo starten:  sudo bash aktualisierung/install.sh --schluessel \"ssh-ed25519 …\""
  exit 1
fi
for p in git ssh ssh-keygen python3; do
  command -v "$p" >/dev/null || { echo "$p fehlt (sudo apt install git openssh-client python3)"; exit 1; }
done
# ssh-keygen -Y (Signaturen prüfen) gibt es ab OpenSSH 8.2
SSHV="$(ssh -V 2>&1 | sed -n 's/^OpenSSH_\([0-9]*\)\.\([0-9]*\).*/\1 \2/p')"
read -r SSH_MAJ SSH_MIN <<< "${SSHV:-0 0}"
if (( SSH_MAJ < 8 || (SSH_MAJ == 8 && SSH_MIN < 2) )); then
  echo "OpenSSH ${SSH_MAJ}.${SSH_MIN} ist zu alt für signierte Updates (nötig: 8.2 oder neuer)."; exit 1
fi

HIER="$(cd "$(dirname "$0")" && pwd)"
KLON="$(dirname "$HIER")"

# --- Öffentlicher Schlüssel -------------------------------------------------------------------------------
install -d -m 755 -o root -g root "$BASIS"
if [[ -n "$SCHLUESSEL" ]]; then
  # nur ein einzelner öffentlicher Schlüssel, keine Optionen davor
  if ! [[ "$SCHLUESSEL" =~ ^(ssh-ed25519|ecdsa-sha2-nistp256|ecdsa-sha2-nistp384|ecdsa-sha2-nistp521|ssh-rsa|sk-ssh-ed25519@openssh.com)\ [A-Za-z0-9+/=]+(\ .*)?$ ]]; then
    echo "Das sieht nicht wie ein öffentlicher SSH-Schlüssel aus (Inhalt der .pub-Datei, beginnt mit ssh-ed25519)."; exit 1
  fi
  if ! printf '%s\n' "$SCHLUESSEL" | ssh-keygen -l -f - >/dev/null 2>&1; then
    echo "ssh-keygen kann den Schlüssel nicht lesen – bitte die Zeile vollständig kopieren."; exit 1
  fi
  ZEILE="$PRINZIPAL namespaces=\"git\" $SCHLUESSEL"
  if [[ -f "$SIGNERS" ]] && ! grep -qxF "$ZEILE" "$SIGNERS"; then
    if [[ $ERSETZEN -ne 1 ]]; then
      echo "Es ist schon ein anderer Schlüssel eingetragen ($SIGNERS)."
      echo "Bewusst austauschen: zusätzlich --schluessel-ersetzen angeben."; exit 1
    fi
  fi
  TMP="$(mktemp "$BASIS/.signers.XXXXXX")"
  printf '%s\n' "# Wer Updates für InkyPi freigeben darf (nur öffentliche Schlüssel, Datei gehört root)" "$ZEILE" > "$TMP"
  chown root:root "$TMP"; chmod 644 "$TMP"
  mv -f "$TMP" "$SIGNERS"
  echo "Schlüssel eingetragen: $(printf '%s\n' "$SCHLUESSEL" | ssh-keygen -l -f -)"
elif [[ ! -f "$SIGNERS" ]]; then
  echo "Bitte deinen öffentlichen Freigabe-Schlüssel angeben:  --schluessel \"ssh-ed25519 …\""; exit 1
fi

# --- Ist dieser Klon selbst ein von dir signierter Stand? ---------------------------------------------------
echo "Prüfe den Klon …"
python3 "$HIER/inkypi_update.py" --klon-pruefen "$KLON"

# --- Dateien ------------------------------------------------------------------------------------------------
echo "Kopiere nach $BASIS …"
install -m 755 -o root -g root "$HIER/inkypi_update.py" "$BASIS/"
install -m 644 -o root -g root "$HIER/inkypi-update.service" "$HIER/inkypi-update.timer" "$BASIS/"
install -m 644 "$HIER/inkypi-update.service" "$HIER/inkypi-update.timer" /etc/systemd/system/
ln -sfn "$BASIS/inkypi_update.py" /usr/local/bin/inkypi-update
install -d -m 755 -o root -g root "$DATEN"

systemctl daemon-reload
if [[ $NACHTS -eq 1 ]]; then
  systemctl enable --now inkypi-update.timer
  echo "Nächtlicher Lauf eingeschaltet (täglich zwischen 3:30 und 3:50 Uhr)."
else
  systemctl disable --now inkypi-update.timer 2>/dev/null || true
  echo "Kein nächtlicher Lauf (nur von Hand)."
fi

echo
echo "Fertig. Jetzt einmal von Hand ausführen – das installiert Dashboard und Ausschaltbild aus den signierten Tags:"
echo "  sudo inkypi-update"
echo "Weitere Befehle:  sudo inkypi-update --pruefen   ·   sudo inkypi-update --verlauf"
echo "Nachts aus/an:    sudo systemctl disable --now inkypi-update.timer   bzw.  enable --now"
