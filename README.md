# InkyPi – Tagesdashboard (Wetter & Kalender)

Ein eigenständiges InkyPi-Plugin: links das Wetter vom Deutschen Wetterdienst mit Kleidungsempfehlung, rechts die Termine aus Nextcloud.

![Dashboard tagsüber](docs/dashboard_tag.png)
![Dashboard abends](docs/dashboard_abend.png)

*Die Screenshots zeigen Testdaten.*

## Installation

Aus einem GitHub-Repository, in dem der Ordner `tagesdashboard` im Wurzelverzeichnis liegt:

```bash
inkypi plugin install tagesdashboard https://github.com/<dein-name>/InkyPi-Tagesdashboard
```

Oder von Hand:

```bash
cp -r tagesdashboard ~/InkyPi/src/plugins/
sudo systemctl restart inkypi.service
```

Danach unter **API Keys** den Schlüssel `NEXTCLOUD_APP_PASSWORD` mit einem App-Passwort aus Nextcloud anlegen (Einstellungen → Sicherheit → „Neues App-Passwort erstellen“). In der Web-Oberfläche „Wetter & Kalender“ öffnen und Ort sowie Nextcloud-Zugang eintragen.

Zusätzliche Python-Pakete braucht das Plugin nicht: `requests`, `astral`, `icalendar` und `recurring-ical-events` bringt InkyPi schon mit.

**Empfohlenes Aktualisierungsintervall:** 30 Minuten.

## Funktionen

- **Wetter (DWD):** aktuelle Werte, amtliche Warnungen, sechs Messwerte und eine Tageskurve von 6 bis 24 Uhr mit „jetzt“-Linie.
- **Abends das Wetter von morgen:** ab einer einstellbaren Uhrzeit, Standard 20 Uhr.
- **Kleidungsempfehlung:** für die Zeit, in der man unterwegs ist, also bis zum Ende des letzten Termins. Das Kälteempfinden ist einstellbar: normal, empfindlich oder sehr empfindlich.
- **Termine (Nextcloud per CalDAV):** Kalenderfarben, Serientermine, ganztägige und mehrtägige Termine. Steigt das Regenrisiko während eines Termins auf mindestens 50 %, steht es am Termin.
- **Robust:** Fällt der Kalender oder das Wetter aus, zeigt das Dashboard den anderen Teil trotzdem an.
- **Layout:** Quer- und Hochformat; optimiert für E-Ink mit halbfetter Schrift und ohne grauen Text.

## Aufbau

```
tagesdashboard/
├── tagesdashboard.py        # Kombiniert Wetter und Termine, Tageskurve, Zeitfenster
├── kleidung.py              # Regeln und Symbole der Kleidungsempfehlung
├── settings.html            # Einstellungsseite (deutsch)
├── plugin-info.json
├── icon.png
├── render/                  # Template und Layout
└── lib/                     # Mitgelieferte Bausteine
    ├── dwd_wetter.py        #   Wetterabruf (Bright Sky / DWD), Warnungen, Kacheln
    ├── dwd_icons.py         #   Wetter- und Messwert-Symbole
    └── nextcloud_kalender.py#   CalDAV-Client, Serientermine
```

`lib/` enthält Kopien aus den Plugins „DWD Wetter“ und „Nextcloud Kalender“, Stand Version 1.0. Dadurch läuft das Dashboard ohne diese Plugins. Sind sie trotzdem installiert, stören sie sich nicht gegenseitig.

## Datenquellen

- Wetter: [Bright Sky](https://brightsky.dev) mit Open Data des Deutschen Wetterdienstes, ohne API-Key
- Termine: die eigene Nextcloud per CalDAV

## Status

Version 1.0. Wird aktiv gepflegt; Fehlerberichte und Pull Requests sind willkommen.

Lizenz: GPL-3.0 (wie InkyPi).
