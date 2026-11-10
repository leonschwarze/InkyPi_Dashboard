# InkyPi – Wetter & Kalender

Drei InkyPi-Plugins, die zusammengehören:

| Ordner | Anzeigename | Inhalt |
|---|---|---|
| `dwd_wetter` | DWD Wetter | Wetter vom Deutschen Wetterdienst |
| `nextcloud_kalender` | Nextcloud Kalender | Termine per CalDAV aus Nextcloud |
| `tagesdashboard` | Wetter & Kalender | Beides auf einem Bild, mit Kleidungsempfehlung |

![Dashboard tagsüber](docs/dashboard_tag.png)
![Dashboard abends](docs/dashboard_abend.png)

*Die Screenshots zeigen Testdaten.*

## Installation

Alle drei Ordner nach `~/InkyPi/src/plugins/` kopieren und InkyPi neu starten:

```bash
cp -r dwd_wetter nextcloud_kalender tagesdashboard ~/InkyPi/src/plugins/
sudo systemctl restart inkypi.service
```

Das Dashboard nutzt den Code der beiden anderen Plugins weiter. Deshalb müssen alle drei installiert sein, und die Ordnernamen dürfen sich nicht ändern. Ein bereits installiertes `nextcloud_kalender` bitte durch die Version aus diesem Paket ersetzen: Sie gibt zusätzlich Start und Ende jedes Termins an das Dashboard weiter.

Das App-Passwort für Nextcloud liegt wie beim Kalender-Plugin unter **API Keys** im Schlüssel `NEXTCLOUD_APP_PASSWORD`.

## Was das Dashboard zeigt

**Links: Wetter**
- Aktuelle Werte, die DWD-Warnung und sechs Kacheln: Wind, Böen, Niederschlag, Luftfeuchte, Luftdruck, Sonnenzeiten.
- **Kleidungsempfehlung** für die Zeit, in der man unterwegs ist: von jetzt bis zum Ende des letzten Termins, mindestens vier Stunden. Das Kälteempfinden ist einstellbar: normal, empfindlich (+3 °C) oder sehr empfindlich (+5 °C).
- **Tageskurve** von 6 bis 24 Uhr: Temperatur, Regenrisiko, Nachtstunden und eine „jetzt“-Linie.
- **Abends** (Standard ab 20 Uhr, einstellbar) schaltet die linke Seite auf das Wetter von morgen um. Die Kleidungsempfehlung gilt dann für die Termine von morgen, ohne Termine für 7 bis 19 Uhr.

**Rechts: Termine**
- Heute, morgen und die folgenden Tage, mit Kalenderfarben.
- Steigt die Regenwahrscheinlichkeit während eines Termins auf mindestens 50 %, steht sie am Termin, zum Beispiel „Stadthaus · 85 % Regen“.
- Was nicht mehr passt, wird als „+ 3 weitere Termine“ zusammengefasst.

**Robustheit:** Fällt der Kalender aus, etwa wegen eines falschen Passworts, zeigt das Dashboard nur das Wetter und einen Hinweis. Fällt das Wetter aus, zeigt es nur die Termine. Erst wenn beides fehlt, meldet InkyPi einen Fehler.

## Kleidungsregeln

Die Logik steht in `tagesdashboard/kleidung.py`. Grundlage ist die kälteste gefühlte Temperatur im Zeitfenster, abzüglich des Aufschlags für Kälteempfindliche:

| gefühlt (mit Aufschlag) | Grundausstattung |
|---|---|
| unter −5 °C | Daunenjacke, Mütze, Handschuhe, Schal, Thermo-Unterwäsche |
| unter 2 °C | Winterjacke, Mütze, Handschuhe, Schal |
| unter 7 °C | Winterjacke, Schal, Mütze |
| unter 12 °C | Übergangsjacke, Pullover (bei Empfindlichkeit dünner Schal) |
| unter 17 °C | leichte Jacke, Langarm |
| unter 23 °C | T-Shirt, Strickjacke für später |
| ab 23 °C | luftige Kleidung |

Zusätzlich gilt:
- **Regen:** Schirm, bei Böen ab 40 km/h stattdessen Kapuze.
- **Schnee oder Glätte:** rutschfeste Schuhe.
- **Mehr als 8 °C Unterschied im Tagesverlauf:** Zwiebellook.
- **Sonne von April bis September:** Sonnenschutz.
- **Höchstens fünf Teile.** Was am wichtigsten ist, hat Vorrang.

Die Schwellen sind Erfahrungswerte und lassen sich in der Datei leicht anpassen.

## Datenquellen

- Wetter: [Bright Sky](https://brightsky.dev) mit Open Data des Deutschen Wetterdienstes, ohne API-Key
- Termine: die eigene Nextcloud per CalDAV

## Status

Version 1.0. Wird aktiv gepflegt; Fehlerberichte und Pull Requests sind willkommen.

Lizenz: GPL-3.0 (wie InkyPi).
