# Tagesdashboard (Wetter & Kalender) für InkyPi – Version 1.8

Wetter vom DWD links, Nextcloud-Termine rechts, Kleidungsempfehlung, UV-Index, Zug mit Störungsmonitor, Morgen-Schlagzeilen, Wäsche-Karte, Nachtbild mit Bonner Silhouette, Wochenvorschau – und neu: **Anfahrt zu Terminen**.

## Installieren bzw. aktualisieren

1. Den Ordner `tagesdashboard/` aus diesem Paket nach `InkyPi/src/plugins/tagesdashboard/` kopieren (vorhandenen Ordner ersetzen).
2. `sudo systemctl restart inkypi.service` (Python-Dateien haben sich geändert).
3. In der Web-Oberfläche die Plugin-Einstellungen öffnen und einmal speichern.

## Neu in 1.8: Anfahrt zu Terminen

Einschalten: Plugin-Einstellungen → **Anfahrt zu Terminen** → „Zeigen, wann ich los muss …“.

- **An jedem Termin** von heute und morgen steht vor dem Ort, wann du los musst: „Los 16:08 · Bus 610“ oder „Los 16:19 · Rad“. Bei Folgeterminen ohne Heimweg dazwischen: „weiter 17:38 · …“ (ab dem Termin davor).
- **Aufbruch-Karte:** etwa 2 Stunden vor der Abfahrt oben über den Terminen – Abfahrt, Verbindung (Verspätung in Rot) und der Grund für Rad oder ÖPNV.
- **Rad nur bei schönem, sicher trockenem Wetter** auf allen Wegen einer Terminkette, jeweils mit einer Stunde Abstand: kein Niederschlag, Regenrisiko unter 30 % (einstellbar), keine Böen ab 50 km/h, keine Glätte. Sonst Bus und Bahn – für die ganze Kette, damit das Rad nicht am falschen Ort steht.
- **Kette:** Termine mit weniger als 90 Minuten Pause (einstellbar). Termine ohne Ort oder mit „Video“, „online“, „Zoom“ … werden übersprungen.
- **Heimweg:** zählt nur, wenn „Auch das Wetter auf dem Heimweg berücksichtigen“ angehakt ist (Standard: aus).
- **Startort:** der Wetter-Ort; abweichend unter „Startort“ (Adresse oder `50.7374, 7.0982`).
- **Ankunft:** 5 Minuten vor Terminbeginn (einstellbar).
- **Eigene Orte:** Wird ein Terminort nicht gefunden (z. B. „Stadthaus“), eine Zeile `Stadthaus = Berliner Platz 2, 53111 Bonn` eintragen.

Daten: [Transitous](https://transitous.org) – frei, ehrenamtlich betrieben, für nicht-kommerzielle Nutzung. Fahrplan und Echtzeit stammen von DELFI; ob Bonner Busse und Bahnen Echtzeit haben, siehst du auf der Karte von Transitous. Ist der Dienst nicht erreichbar, schätzt das Dashboard aus der Entfernung („ca.“), sobald es die Orte einmal kennt.

## Schrift und Schärfe

Siehe `README.md` des Repos (Abschnitt „Schärfer auf dem Inky Impression“): Bildeinstellungen auf 1,0, `inky_saturation` ≤ 0,5, `/etc/fonts/local.conf` mit Autohinter.

## Screenshots (`docs/`)

Mit simulierten Daten (Beispieltermine, Beispielverbindungen):

- `anfahrt-bus_800x480.png` – Regen ab 17 Uhr: Bus schon zum ersten Termin der Kette
- `anfahrt-rad_800x480.png` – trockener Abend: Rad
- `anfahrt-verspaetung_800x480.png` – Bus mit 4 Minuten Verspätung
- `anfahrt-morgens_800x480.png` – morgens mit Schlagzeilen
- `anfahrt-bus_480x800.png` – hochkant
