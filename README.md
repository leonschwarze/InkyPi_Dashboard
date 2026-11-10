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

- **Wetter (DWD):** aktuelle Werte, amtliche Warnungen und sechs Messwerte: Wind, Böen, Niederschlag, Luftfeuchte, UV-Index mit Stufe (niedrig bis extrem) und Sonnenzeiten.
- **Tageskurve** von 6 bis 24 Uhr mit „jetzt“-Linie. Darunter eine eigene Regenzeile: Die Balkenhöhe zeigt die Menge pro Stunde, die Füllung die Stärke (leicht: umrandet, mäßig: blau, stark: rot). Die Kopfzeile nennt Zeitraum und Summe, zum Beispiel „Regen 17–23 Uhr · 6,8 mm“.
- **Abends das Wetter von morgen:** ab einer einstellbaren Uhrzeit, Standard 20 Uhr.
- **Kleidungsempfehlung:** für die Zeit, in der man unterwegs ist, also bis zum Ende des letzten Termins. Das Kälteempfinden ist einstellbar: normal, empfindlich oder sehr empfindlich.
- **Termine (Nextcloud per CalDAV):** Kalenderfarben, Serientermine, ganztägige und mehrtägige Termine. Steigt das Regenrisiko während eines Termins auf mindestens 50 %, steht es am Termin.
- **Robust:** Fällt der Kalender oder das Wetter aus, zeigt das Dashboard den anderen Teil trotzdem an.
- **Layout:** Quer- und Hochformat; optimiert für E-Ink mit halbfetter Schrift und ohne grauen Text. Die Farben werden auf die sechs Displayfarben eingerastet (siehe unten).

## Schärfer auf dem Inky Impression

Das Inky Impression 7,3″ kann nur sechs Farben darstellen. Alles andere setzt der Treiber aus farbigen Pünktchen zusammen, dabei fransen Schrift und Linien aus. Zwei Maßnahmen machen das Bild deutlich schärfer:

**1. Farben einrasten (im Plugin, standardmäßig an).** Das Plugin legt jedes Pixel selbst auf eine der sechs Displayfarben fest, bevor das Bild zum Treiber geht. Kanten bleiben dadurch glatt, kräftige Farben werden einfarbig. Nur Graustufen und helle Töne (zum Beispiel die Nachtstunden im Graphen) erscheinen als feines, gleichmäßiges Punktmuster. Abschalten lässt es sich in den Plugin-Einstellungen: „Schärfer auf Inky-Displays“.

Damit das wirkt, in InkyPi unter den Bildeinstellungen (Image Settings) Sättigung, Kontrast, Schärfe und Helligkeit auf **1,0** lassen. Die Inky-Sättigung (`inky_saturation`) bei **0,5 oder weniger** einstellen. Andere Werte verfälschen die Farben wieder; das Plugin schreibt dann eine Warnung ins Log.

**2. Schrift am Pixelraster ausrichten (einmalig auf dem Pi).** Diese Einstellung schaltet den Autohinter von FreeType ein. Er richtet alle Striche einer Schriftgröße auf dieselbe Pixelbreite aus. Die grauen Kantenpixel der geglätteten Schrift macht danach das Einrasten (Punkt 1) hart schwarz oder weiß. So entstehen gleichmäßige Buchstaben ohne graue Ränder:

```bash
sudo tee /etc/fonts/local.conf > /dev/null <<'XML'
<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig>
  <match target="font">
    <edit name="antialias" mode="assign"><bool>true</bool></edit>
    <edit name="hinting" mode="assign"><bool>true</bool></edit>
    <edit name="autohint" mode="assign"><bool>true</bool></edit>
    <edit name="hintstyle" mode="assign"><const>hintfull</const></edit>
    <edit name="rgba" mode="assign"><const>none</const></edit>
    <edit name="lcdfilter" mode="assign"><const>lcdnone</const></edit>
  </match>
</fontconfig>
XML
fc-cache -f
sudo systemctl restart inkypi.service
```

Der Befehl überschreibt eine vorhandene `/etc/fonts/local.conf`. Er gilt für alle Programme auf dem Pi, die fontconfig nutzen, also auch für andere InkyPi-Plugins. Rückgängig machen: `sudo rm /etc/fonts/local.conf` und InkyPi neu starten.

Bitte nicht Schrift ganz ohne Kantenglättung (`antialias=false`) verwenden. Dann rundet FreeType jeden Buchstaben einzeln auf ganze Pixel, und die Striche werden ungleich dick: „n“ und „m“ wirken dünn, „H“ und Ziffern fett.

**Vorschau:** Die Vorschau in der InkyPi-Weboberfläche zeigt das eingerastete Bild. So sieht es auf dem Display aus, nur leuchtender.

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
    ├── nextcloud_kalender.py#   CalDAV-Client, Serientermine
    └── eink.py              #   Farben auf die Displayfarben einrasten
```

`lib/` enthält Kopien aus den Plugins „DWD Wetter“ und „Nextcloud Kalender“, Stand Version 1.1. Dadurch läuft das Dashboard ohne diese Plugins. Sind sie trotzdem installiert, stören sie sich nicht gegenseitig.

## Datenquellen

- Wetter: [Bright Sky](https://brightsky.dev) mit Open Data des Deutschen Wetterdienstes, ohne API-Key
- UV-Index: [UV-Gefahrenindex des DWD](https://opendata.dwd.de/climate_environment/health/alerts/) (`uvi.json`). Er wird nur für ausgewählte Orte berechnet; der Ort wird über den Namen zugeordnet. Ohne Treffer in der Einstellung „Ort für den UV-Index“ einen Ort in der Nähe eintragen, sonst zeigt die Kachel die Bewölkung.
- Termine: die eigene Nextcloud per CalDAV

## Status

Version 1.1 (Farben einrasten, Schrift für E-Ink). Wird aktiv gepflegt; Fehlerberichte und Pull Requests sind willkommen.

Lizenz: GPL-3.0 (wie InkyPi).
