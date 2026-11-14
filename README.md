# Tagesdashboard (Wetter & Kalender) für InkyPi – Version 1.19

Wetter vom DWD links, Nextcloud-Termine rechts, Kleidungsempfehlung, UV-Index, Pollenflug, Sternschnuppenströme, Mondfinsternisse und helle Planeten im Nachtbild, Zug mit Störungsmonitor, Morgen-Schlagzeilen, Wäsche-Karte, Nachtbild mit Bonner Silhouette, Wochenvorschau, Anfahrt zu Terminen, Festtage, Regenradar, Schlagzeilen aus Frankreich, Luftqualität, Streckenmeldungen und eine **kleine Katze**, die sich bei jeder Aktualisierung woanders versteckt – neu: nachts schläft sie auf dem Mond über Bonn.

## Installieren bzw. aktualisieren

1. Den Ordner `tagesdashboard/` aus diesem Paket nach `InkyPi/src/plugins/tagesdashboard/` kopieren (vorhandenen Ordner ersetzen).
2. `sudo systemctl restart inkypi.service` (Python-Dateien haben sich geändert).
3. In der Web-Oberfläche die Plugin-Einstellungen öffnen und einmal speichern.

## Neu in 1.19: Helle Planeten

**Helle Planeten** (Plugin-Einstellungen → Nachtbild → „Helle Planeten anzeigen“, standardmäßig **an**):

- Im Nachtbild (23–6 Uhr) erscheint unter der Tageslicht-Zeile (bzw. unter den Zeilen zu Sternschnuppen/Mondfinsternis, falls mehrere zutreffen) eine zusätzliche Textzeile, sobald Venus, Jupiter, Mars oder Saturn höchstens 14 Tage von ihrem Höhepunkt entfernt sind: „Planeten: Saturn in 9 Tagen in Opposition (0,3 mag)“. Am Höhepunkt selbst: „Planeten: Saturn heute Nacht in Opposition · die ganze Nacht sichtbar (0,3 mag)“ bzw. bei Venus „… heute Nacht am hellsten · Morgenstern (−4,9 mag)“.
- Anders als bei den Mondfinsternissen verschwindet die Zeile einen Tag nach dem Höhepunkt wieder, auch wenn der Planet real noch monatelang sichtbar bleibt – sonst wäre praktisch ständig irgendein Planet „sichtbar“ und die Zeile keine Besonderheit mehr.
- Nur am Höhepunkt selbst und bei klarem Himmel zeichnet das Nachtbild zusätzlich einen auffällig großen, strahlenden Punkt: Venus (Morgen-/Abendstern) niedrig am Horizont wie der Mond mit Katze, eine Opposition (Jupiter, Mars, Saturn) hoch über dem Siebengebirge.
- Ist kein Planet nah an seinem Höhepunkt, bleibt das Bild wie bisher unverändert.
- **Daten:** von Hand recherchierte Sichtbarkeitsfenster und Höhepunkte für alle vier mit bloßem Auge auffälligen Planeten (mehrere Astronomie-Portale, Stand November 2026) – wie bei den Mondfinsternissen keine jahresperiodische Formel, weil die Umlaufzeiten nicht ins Kalenderjahr passen; die Fenster müssen nach ihrem Ende von Hand aufgefrischt werden.

**Deine Einstellungen bleiben erhalten** (cfgVersion 18). Nach dem Update einmal speichern; helle Planeten sind sofort an.

## Neu in 1.18: Mondfinsternisse

**Mondfinsternisse** (Plugin-Einstellungen → Nachtbild → „Mondfinsternisse anzeigen“, standardmäßig **an**):

- Im Nachtbild (23–6 Uhr) erscheint unter der Tageslicht-Zeile (bzw. unter der Sternschnuppen-Zeile, falls beide zutreffen) eine zusätzliche Textzeile, sobald eine der nächsten von Bonn aus sichtbaren Mondfinsternisse höchstens 45 Tage entfernt ist: „Mondfinsternis in 14 Tagen (20.12.): totale Mondfinsternis · ab 22:43 Uhr, komplett sichtbar“. In der Nacht des Ereignisses selbst: „Mondfinsternis heute Nacht: …“.
- Bei einer **totalen** Mondfinsternis färbt sich der Mond in dieser Nacht zusätzlich rötlich (Blutmond) – Fläche, Kontur und die Spiegelung im Rhein, sofern der Himmel klar genug ist, um den Mond überhaupt zu zeigen. Halbschatten- und partielle Finsternisse bleiben Text ohne Farbeffekt.
- Ist keine Finsternis in Sicht, bleibt das Bild wie bisher unverändert.
- **Daten:** von Hand recherchierte Terminliste der nächsten fünf von Bonn aus sichtbaren Mondfinsternisse (mehrere deutsche Astronomie-Portale, Stand November 2026) – anders als die Sternschnuppenströme keine jährlich wiederkehrende Formel, sondern konkrete Kalendertermine bis Mitte 2030, die irgendwann aufgefrischt werden müssen. Sonnenfinsternisse sind bewusst nicht enthalten (sie finden tagsüber statt und passen nicht zum Nachtbild).

**Deine Einstellungen bleiben erhalten** (cfgVersion 17). Nach dem Update einmal speichern; Mondfinsternisse sind sofort an.

## Neu in 1.17: Sternschnuppenströme

**Sternschnuppenströme** (Plugin-Einstellungen → Nachtbild → „Sternschnuppenströme anzeigen“, standardmäßig **an**):

- Im Nachtbild (23–6 Uhr) erscheint unter der Tageslicht-Zeile eine zusätzliche Textzeile, sobald einer von elf bekannten Meteorströmen aktiv ist: „Sternschnuppen: Perseiden aktiv · Maximum 12./13.8.“ In der Maximumnacht steht statt des Datums die Fallrate: „Perseiden-Maximum heute Nacht · ZHR 100“.
- Bei den drei kräftigsten Strömen (Quadrantiden, Perseiden, Geminiden) zieht das Nachtbild zusätzlich ein paar helle Sternschnuppen über den Himmel – aber nur in der Maximumnacht selbst **und** bei klarem Himmel (sonst bleibt es bei der Textzeile).
- Ist kein Strom aktiv, bleibt das Bild wie bisher unverändert.
- **Daten:** feste Kalendertabelle nach der International Meteor Organization (IMO) – kein Abruf, keine tagesgenaue Berechnung für ein bestimmtes Jahr; das reale Maximum kann um etwa einen Tag abweichen.

**Deine Einstellungen bleiben erhalten** (cfgVersion 16). Nach dem Update einmal speichern; Sternschnuppenströme sind sofort an.

## Neu in 1.16: Pollenflug

**Pollenflug** (Plugin-Einstellungen → Wetter → „Pollenflug anzeigen …“, standardmäßig **an**):

- Erreicht eine ausgewählte Pollenart die eingestellte Stufe, erscheint im Wetterbereich eine zusätzliche, breite Kachel: „Birke mittel +1 weitere“. Ist die Belastung überall gering, bleibt das Bild wie bisher – anders als Luftqualität, Regenradar und Zug bekommt Pollenflug also **keine eigene Karte** in der rechten Spalte, sondern nur eine platzsparende Kachel neben Wind, Böen & Co.
- Gelb = mittel, Rot = hoch (wie bei der Luftqualität); „gering“ ohne Farbe.
- **Alle acht Pollenarten** einzeln abwählbar: Hasel, Erle, Esche, Birke, Gräser, Roggen, Beifuß, Ambrosia. „Zeigen ab“ gering (Standard), mittel oder hoch. Die Teilregion ist voreingestellt auf Bonn, lässt sich aber eintragen, falls der DWD für einen anderen Ort gelten soll.
- **Daten:** Pollenflug-Gefahrenindex des DWD (`s31fg.json`), einmal täglich aktualisiert, ohne Schlüssel.

**Deine Einstellungen bleiben erhalten** (cfgVersion 15). Nach dem Update einmal speichern; Pollenflug ist sofort an.

## Neu in 1.15: Katze auf dem Mond und drei neue Posen

- **Im Nachtbild** (23–6 Uhr, mit Bonner Silhouette) schläft die Katze jetzt eingerollt auf dem Mond: weiß mit schwarzen Linien, darüber ein gelbes „Z“. In diesen Nächten steht der Mond etwas größer und tiefer über dem Rhein zwischen Stadt und Siebengebirge (nie hinter Münster oder Langem Eugen). Wolken schieben sich höchstens vor den Mond, nicht vor die Katze. Das Nachtbild bleibt die ganze Nacht gleich, das Display flackert also nicht.
- **Drei neue Posen** für tagsüber: gähnt, jagt den eigenen Schwanz, liegt ausgestreckt auf dem Rücken. Damit gibt es elf Alltags-Posen plus vier Wetter-Posen.
- Neue Option unter „Katze“: **„Auch im Nachtbild“** (standardmäßig an). Ausgeschaltet sieht das Nachtbild aus wie bisher.

**Deine Einstellungen bleiben erhalten** (cfgVersion 14). Nach dem Update einmal speichern.

## Neu in 1.14: die Katze

**Katze** (Plugin-Einstellungen → Katze, standardmäßig **an**):

- Eine kleine Katze in Linien-Optik sitzt bei jeder Aktualisierung woanders: auf der Kopfzeile, auf der Linie unter „Heute“, „Morgen“ und den anderen Tagen oder auf der gestrichelten Linie über „+ weitere Termine“. Sie wählt nur einen Platz, an dem sie nichts verdeckt; ist nirgends genug frei, fehlt sie.
- **Posen:** sitzt, putzt sich, schaut einem Schmetterling nach, schläft, Kastenbrot, lugt über die Kante, spielt mit dem Wollknäuel, streckt sich (seit 1.15 auch: gähnt, jagt den Schwanz, liegt auf dem Rücken). Zwei Aktualisierungen hintereinander zeigen nie dieselbe Pose. Wo wenig Platz ist, nimmt sie eine flache Pose.
- **Wetterkatze** (Option „Sie passt sich dem Wetter an“, standardmäßig an): bei Regen unter dem Schirm, bei Schnee oder Frost (gefühlt unter 0 °C) mit rotem Schal, bei Sonne ab 15 °C im Sonnenbad, bei Sturmböen ab 60 km/h duckt sie sich und hält sich fest. Es zählt die laufende Stunde, genau wie in der Tageskurve.
- Nur in der normalen Ansicht. Nachtbild, Wochenvorschau und Festbilder bleiben, wie sie sind.
- Ohne Katze ist das Bild pixelgleich zu 1.13. Weil sich „Stand …“ ohnehin bei jeder Aktualisierung ändert, zeichnet das Display ihretwegen nicht öfter neu.

**Deine Einstellungen bleiben erhalten** (cfgVersion 13).

## Neu in 1.13: Streckenmeldungen (Vorwarnung)

**Streckenmeldungen** (Plugin-Einstellungen → Zug → unter „Störungsmeldungen …“ die Option „Auch Störungen und Baustellen auf der Strecke …“, standardmäßig **an**):

- Die Bahn meldet eine Verspätung erst, wenn sie deinen Zug selbst betrifft – die RE 5 um 8:04 fährt aber erst gegen 7 Uhr in Koblenz los. Ist schon um 6:40 zwischen Köln und Leverkusen ein Signal gestört, steht bis dahin „pünktlich“ da. Jetzt erscheint darunter eine **Vorwarnung mit Gleis-Symbol**, z. B. „Strecke Köln-Mülheim–Leverkusen Mitte: Reparatur an einem Signal · seit 6:40“. So kannst du früh überlegen, ob du eine andere Verbindung nimmst.
- Auch **Baustellen** auf deinem Abschnitt („Baustelle Düsseldorf–Köln-Mülheim: Umleitungen und Teilausfälle bis 4.12.“) und **behobene Störungen** (eine Stunde lang: „Behoben: Signal Köln–Köln Messe/Deutz · Verspätungen möglich“).
- Die Vorwarnung ist immer **gelb**. Rot wird die Karte erst, wenn die Bahn deinen Zug selbst als gestört meldet; deren Meldungen (mit „!“) stehen dann zuerst.
- **Nur, was deinen Weg betrifft:** Meldungen zu deiner Linie, die einen Bahnhof oder eine Stadt auf dem Weg deines Zuges bis zum Ausstieg nennen – auch vor deinem Einstieg (z. B. Remagen–Bonn-Bad Godesberg). Abschnitte hinter dem Ausstieg (Duisburg, Oberhausen …) und gleichnamige Linien anderswo (es gibt auch eine RE 5 in Hessen und in Hamburg) bleiben draußen. Dafür muss unter „Zug“ der **Ausstieg** eingetragen sein.
- **Daten:** Fahrplanauskunft des VRR, „Open Service“ über [opendata-oepnv.de](https://www.opendata-oepnv.de/ht/de/api) – frei für private Nutzung, ohne Anmeldung. Die Liste umfasst ganz NRW (etwa 4 MB) und wird darum höchstens alle 10 Minuten geholt, nur im Zeitfenster des Zuges. Der Open Service ist eine Testkopie des VRR; fällt er aus, sieht die Zugkarte aus wie bisher.

**Deine Einstellungen bleiben erhalten** (cfgVersion 12).

## Neu in 1.12: Luftqualität

**Luftqualität** (Plugin-Einstellungen → Wetter → „Luftqualität …“, standardmäßig **an**):

- Ist die Luft draußen **mäßig oder schlechter**, erscheint rechts über den Terminen eine Karte, z. B. „Feinstaub erhöht · mäßig“, darunter „PM2,5 22 · PM10 39 · 9 Sensoren“ (µg/m³) und ein kurzer Hinweis („Anstrengenden Sport draußen meiden“). Gelb = mäßig, Rot = schlecht, dicker roter Rahmen = sehr schlecht. Morgens im Nachrichtenfenster ohne den Hinweis.
- Ist die Luft gut, ändert sich am Bild nichts.
- **Daten:** Feinstaub von den Bürgersensoren auf [sensor.community](https://sensor.community) im Umkreis (Standard 3 km): nur Außensensoren, Median aus mindestens drei, über die letzte Stunde gemittelt. Ersatz ist die amtliche Messstation **Bonn-Auerberg** (DENW062) über die Luftdaten-API des Umweltbundesamts – immer dann, wenn die Luftfeuchte bei 80 % oder mehr liegt (die günstigen Sensoren zählen dann Wassertröpfchen mit und zeigen zu viel) oder wenn zu wenige Sensoren melden. Ist auch die Station nicht erreichbar, zeigt die Karte den Sensorwert gestrichelt mit dem Hinweis „Feucht: Sensoren zeigen oft zu viel“.
- **Einstufung** nach dem Luftqualitätsindex des Umweltbundesamts (Stundenwerte, Klassengrenzen seit 2025): z. B. PM2,5 ab 16 µg/m³ mäßig, ab 31 schlecht, über 50 sehr schlecht.
- **Einstellungen:** „Zeigen ab“ mäßig oder schlecht (mit den strengeren Grenzen seit 2025 ist „mäßig“ recht häufig – wenn dir die Karte zu oft kommt, auf „schlecht“ stellen), Umkreis in km, Messstation (Code beim Umweltbundesamt), und optional **Ozon und Stickstoffdioxid** der Station mitbewerten (standardmäßig aus; im Sommer meldet sich die Karte damit auch bei hohem Ozon).
- Quellen: sensor.community (Open Database License); „Umweltbundesamt mit Daten der Messnetze der Länder und des Bundes“.

**Deine Einstellungen bleiben erhalten** (cfgVersion 11).

## Neu in 1.11: Regenradar und Frankreich

**Regenradar** (Plugin-Einstellungen → Wetter → „Regenradar …“, standardmäßig **an**):

- Kommt in den nächsten zwei Stunden Regen an deinen Wetter-Ort (oder regnet es gerade), erscheint rechts über den Terminen eine Karte: „Regen 16:35–17:05 · mäßig · ab 17:45 wieder“ bzw. „Regen bis etwa 16:55 · danach trocken bis 18:20“. Darunter ein Balken je 5 Minuten, Höhe wie in der Tageskurve; bei starkem Regen roter Rahmen. Morgens im Nachrichtenfenster nur die zwei Textzeilen.
- Bleibt es trocken, ändert sich am Bild nichts.
- Daten: Radar des DWD (Messung und Vorhersage für zwei Stunden) über Bright Sky – frei, ohne Schlüssel. Gezählt wird der stärkste Wert im Umkreis von einem Kilometer, weil das Radar etwa so unscharf ist. Ob Regen oder Schnee, steht nicht im Radar; das Wort kommt aus der Vorhersage.

**Frankreich** (Nachrichten am Morgen → „Dazu eine Schlagzeile aus Frankreich, auf Französisch“, standardmäßig **aus**):

- Vierte Ebene „France“ mit kleiner Trikolore: quer eine Schlagzeile, hochkant bis zu zwei, im Original. Liveticker („DIRECT“) und Videos werden übersprungen, Etiketten wie „ENQUÊTE.“ abgeschnitten.
- Quelle: franceinfo „Les titres“; andere Feeds (z. B. Le Monde `https://www.lemonde.fr/rss/une.xml`) im Feld darunter.
- Wird es eng (z. B. Zug und Radar zugleich), fällt Frankreich als Erstes weg.

**Behoben:** InkyPi sagt dem Browser nicht, dass die Seite UTF-8 ist. Bei vielen Akzenten konnte Chromium deshalb falsch raten, dann stand überall „Ã©“ statt „é“ und „Ã¼“ statt „ü“. Das Dashboard (und Wetter und Kalender ab 1.11) gibt den Zeichensatz jetzt selbst an.

**Deine Einstellungen bleiben erhalten** (cfgVersion 10). Nach dem Update einmal speichern; das Radar ist sofort an, Frankreich musst du einschalten.

## Neu in 1.10: aufgeräumte Einstellungen

Die Einstellungsseite ist neu gegliedert, das Bild auf dem Display bleibt gleich.

- Abschnitte mit Überschrift in der Reihenfolge des Tages: Wetter-Ort, Nextcloud, Wetter, Termine, dann Nachrichten am Morgen, Zug, Anfahrt, Wäsche, Wochenvorschau, Nachtbild, Festtage und Geburtstage.
- Jede Funktion hat einen Hauptschalter; ihre Einstellungen stehen eingerückt darunter und werden blass, wenn sie aus ist. Die Werte bleiben dabei gespeichert.
- Längere Erklärungen (wie Wäsche und Anfahrt entscheiden, Takt und API-Schlüssel beim Zug) stehen hinter „So wird entschieden“ bzw. „Aktualisierung und API-Schlüssel“.
- Wochentage des Zuges als Schalter, Geburtstage auf dem Handy als Karten statt als zu breite Tabelle.
- Name des Schlüssels, SSL-Prüfung und „Schärfer auf Inky-Displays“ stehen unter **Erweitert**. Der Bereich klappt von selbst auf, wenn dort etwas vom Standard abweicht.

**Deine Einstellungen bleiben erhalten:** Alle Schlüssel heißen wie vorher (cfgVersion 9), nichts muss neu eingestellt werden. Behoben: Bei sehr alten Einstellungen ohne Versionsnummer zeigte die Seite ein gespeichertes „aus“ als „an“.

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

## Neu in 1.9: Festtage und Geburtstage

Plugin-Einstellungen → **Festtage und Geburtstage** (standardmäßig an):

- **Gruß im Kopf** neben dem Datum: 24.–26.12. „Frohe Weihnachten“, 31.12. „Guten Rutsch“, 1.1. „Frohes neues Jahr“ und an Geburtstagen „Alles Gute, …!“.
- **Festbild:** Heiligabend 17–23 Uhr „Bonn im Schnee“; Silvester ab 22 Uhr Feuerwerk über Bonn mit Fallblattanzeige, um Mitternacht „Frohes neues Jahr 2027“ mit Sektgläsern (bis 2 Uhr). Darunter Datum, Wetter und die Termine des Tages.
- **Geburtstage im Haushalt:** Name, Tag und Monat auswählen, Jahr freiwillig. Fehler werden vor dem Speichern markiert. Am Geburtstag morgens 6–10 Uhr das Festbild: der Name in Folienballons, mit Jahr auch das Alter in Gold.

## Schrift und Schärfe

Siehe `README.md` des Repos (Abschnitt „Schärfer auf dem Inky Impression“): Bildeinstellungen auf 1,0, `inky_saturation` ≤ 0,5, `/etc/fonts/local.conf` mit Autohinter.

## Screenshots (`docs/`)

Mit simulierten Daten (Beispieltermine, Beispielverbindungen):

- `anfahrt-bus_800x480.png` – Regen ab 17 Uhr: Bus schon zum ersten Termin der Kette
- `anfahrt-rad_800x480.png` – trockener Abend: Rad
- `anfahrt-verspaetung_800x480.png` – Bus mit 4 Minuten Verspätung
- `anfahrt-morgens_800x480.png` – morgens mit Schlagzeilen
- `anfahrt-bus_480x800.png` – hochkant
- `fest-weihnachten.png`, `fest-silvester.png`, `fest-neujahr.png`, `fest-geburtstag.png` – Festbilder
- `radar_800x480.png`, `radar_480x800.png` – Regenradar: Schauer 16:35–17:05, ab 17:45 wieder Regen
- `nachrichten-frankreich_800x480.png`, `nachrichten-frankreich_480x800.png` – Morgen-Schlagzeilen mit Frankreich
- `luft_800x480.png` – Luftqualität mäßig (Bürgersensoren)
- `luft_480x800.png` – Luftqualität schlecht, hochkant (feuchte Luft: Wert der Messstation)
- `strecke_800x480.png`, `strecke_480x800.png` – Zug pünktlich, darunter Signalstörung auf der Strecke und Baustelle (Beispielmeldungen)
- `katze_800x480.png` – Katze bei Regen unter dem Schirm auf der Kopfzeile
- `katze_480x800.png` – hochkant, bei Frost mit Schal
- `katze_nacht_800x480.png`, `katze_nacht_480x800.png` – Nachtbild: Katze schläft auf dem Mond über Bonn
- `katze_posen.png` – alle Posen (groß und in Displaygröße)

Die übrigen Bilder stammen aus früheren Versionen und zeigen die Katze noch nicht.
