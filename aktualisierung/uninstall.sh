#!/usr/bin/env bash
# Signierte Updates wieder entfernen:  sudo bash uninstall.sh
# Dashboard und Ausschaltbild bleiben, wie sie sind.
set -euo pipefail
if [[ $EUID -ne 0 ]]; then
  echo "Bitte mit sudo starten:  sudo bash uninstall.sh"; exit 1
fi
systemctl disable --now inkypi-update.timer 2>/dev/null || true
rm -f /etc/systemd/system/inkypi-update.service /etc/systemd/system/inkypi-update.timer
systemctl daemon-reload
rm -f /usr/local/bin/inkypi-update
rm -rf /usr/local/inkypi-update /var/lib/inkypi-update
echo "Entfernt. Dashboard und Ausschaltbild sind unverändert installiert."
