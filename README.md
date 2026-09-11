# 🎓 Teacher Soundboard

[![Build](https://github.com/florianchristophnowak-dot/TeacherSoundboard/actions/workflows/build.yml/badge.svg)](https://github.com/florianchristophnowak-dot/TeacherSoundboard/actions/workflows/build.yml)
[![Release](https://img.shields.io/github/v/release/florianchristophnowak-dot/TeacherSoundboard?include_prereleases)](https://github.com/florianchristophnowak-dot/TeacherSoundboard/releases/latest)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Eine lokale Unterrichtshilfe: Soundboard-Leiste am Bildschirmrand und ein Panel für Sozialform, Material und Timer. Auf Wunsch steuert das Panel zusätzlich die Projektion von Boîte à Oublis – vollständig lokal, ohne Konto und ohne Internet.

## Download

| System | Empfohlener Download | Alternative |
|---|---|---|
| Windows 10/11 (x64) | [Windows-Installer](https://github.com/florianchristophnowak-dot/TeacherSoundboard/releases/latest/download/TeacherSoundboard-Windows-x64-Setup.exe) | [Portable ZIP](https://github.com/florianchristophnowak-dot/TeacherSoundboard/releases/latest/download/TeacherSoundboard-Windows-x64.zip) |
| macOS 12+ (Apple Silicon: M1–M4) | [DMG](https://github.com/florianchristophnowak-dot/TeacherSoundboard/releases/latest/download/TeacherSoundboard-macOS-Apple-Silicon.dmg) | [App als ZIP](https://github.com/florianchristophnowak-dot/TeacherSoundboard/releases/latest/download/TeacherSoundboard-macOS-Apple-Silicon.zip) |
| macOS 12+ (Intel) | [DMG](https://github.com/florianchristophnowak-dot/TeacherSoundboard/releases/latest/download/TeacherSoundboard-macOS-Intel.dmg) | [App als ZIP](https://github.com/florianchristophnowak-dot/TeacherSoundboard/releases/latest/download/TeacherSoundboard-macOS-Intel.zip) |

Die Download-Links funktionieren, sobald ein Release veröffentlicht wurde. Testpakete eines Pull Requests stehen am Ende des zugehörigen GitHub-Actions-Laufs unter „Artifacts“.

## Installation

### Windows

1. `TeacherSoundboard-Windows-x64-Setup.exe` herunterladen und starten.
2. Der Installer benötigt keine Administratorrechte und legt Verknüpfungen im Startmenü an.
3. Falls Microsoft SmartScreen erscheint: „Weitere Informationen“ und anschließend „Trotzdem ausführen“ wählen.

Die portable ZIP-Version muss vollständig entpackt werden. Die EXE darf nicht allein aus ihrem Programmordner verschoben werden.

### macOS

1. Passende Variante wählen: „Apple Silicon“ für M1/M2/M3/M4, „Intel“ für ältere Macs.
2. DMG öffnen und `TeacherSoundboard.app` in den Ordner „Programme“ ziehen.
3. Beim ersten Start die App mit Rechtsklick → „Öffnen“ starten. Falls macOS sie weiterhin blockiert: Systemeinstellungen → Datenschutz & Sicherheit → „Dennoch öffnen“.

Die automatisch erzeugten macOS-Pakete sind technisch signiert, aber ohne kostenpflichtiges Apple-Developer-Zertifikat nicht notarisiert. Deshalb kann beim ersten Start die genannte Sicherheitsabfrage erscheinen.

## Globale Hotkeys unter macOS

Globale Hotkeys benötigen einmalig eine Freigabe unter:

`Systemeinstellungen → Datenschutz & Sicherheit → Bedienungshilfen → Teacher Soundboard`

Ohne diese Freigabe startet die App weiterhin stabil und ist per Mausklick sowie mit lokalen Tastenkürzeln bedienbar.

## Bedienung

- Rechtsklick auf eine Münze: Medium, Bild und weitere Einstellungen bearbeiten
- `Alt` + Ziehen: Leiste verschieben; nahe am Rand dockt sie automatisch an
- `1`–`8`: sichtbare Münzen auslösen, wenn die App fokussiert ist
- `Escape`, `Leertaste` oder `S`: Wiedergabe stoppen
- `Strg+M` (Windows) bzw. `Cmd+M` (macOS): Verwaltung öffnen
- Globale Standard-Hotkeys: `F1`–`F8`; im Manager frei änderbar
- Boîte-Kachel: Linksklick blendet die Sprachhilfe aus und ein, Rechtsklick öffnet die kompakte Steuerung

## Unterrichtspanel ab v4.5.0

Methode/Sozialform, Material und Timer stehen in einem eigenen Panel am rechten Bildschirmrand, getrennt von der Soundboard-Leiste. Dort ist Platz für große, aus der letzten Reihe lesbare Symbole. Das Panel lässt sich am rechten Rand frei nach oben und unten schieben; angefasst wird es am grauen Griff über dem obersten Symbol, die Lage wird gespeichert.

Das Panel hat bewusst keine Hintergrundkarte, keine Trennlinien und keinerlei Schrift: Es stehen nur die farbigen Kacheln im Bild, getrennt allein durch Abstand und rechtsbündig zur Bildschirmkante angeordnet. Jede Kachel trägt ihre eigene Farbfläche, damit die Symbole ohne Rahmen auf hellem wie auf dunklem Bildschirminhalt lesbar bleiben.

Alle Bestandteile sind einzeln zu- und abschaltbar, über das Kontextmenü unter *Anzeige* oder in der Verwaltung:

- Soundboard-Leiste: die Klangschaltflächen am gewählten Bildschirmrand
- Methode oder Sozialform: Kachel anklicken und ein Symbol auswählen
- Material: Kachel anklicken und beliebig viele Materialien aktivieren
- Timer: Restzeit als schrumpfender Kreisausschnitt, darunter drei Schaltflächen für eine Minute weniger, Start/Pause und eine Minute mehr
- Boîte à Oublis: Zustand und Steuerung der Sprachhilfe, sobald die Verbindung eingerichtet ist (siehe unten)

Die Soundboard-Leiste selbst enthält nur noch Klänge und einen Symbolgriff, über den das Menü auch dann erreichbar bleibt, wenn alles andere ausgeblendet ist.

### Timer

Start, Pause und die Minutentasten liegen unmittelbar im Panel, es ist kein Umweg über ein Menü nötig. Ein Klick auf den Ring öffnet die Dauer-Auswahl mit `5`, `8`, `10` Minuten, einer eigenen Minutenzahl, Neustart und Löschen.

Die Restzeit erscheint als farbiger Kreisausschnitt, der von zwölf Uhr im Uhrzeigersinn schrumpft, und färbt sich dabei von Grün über Orange nach Rot – ablesbar ohne eine einzige Ziffer. Ist die Zeit abgelaufen, steht die Scheibe voll rot. Ohne eingestellten Timer ist sie grau; die Minutentasten verstellen dann die Startdauer. Bei Pause wechselt der Ausschnitt nach Orange, die Schaltfläche zeigt wieder das Startdreieck. Ein Druck auf Start bei abgelaufener Zeit beginnt dieselbe Dauer von vorn.

Für das Ende lässt sich eine Audiodatei hinterlegen (`mp3`, `wav`, `ogg`, `flac`, `m4a`, `aac`): in der Verwaltung unter *Klang am Ende des Timers* oder über die Lautsprecher-Schaltfläche in der Dauer-Auswahl. Der Klang läuft über einen eigenen Abspieler, unterbricht also einen laufenden Soundboard-Klang nicht und wird von diesem auch nicht abgeschnitten. Er nutzt dasselbe Ausgabegerät und dieselbe Lautstärke wie das Soundboard und ertönt genau einmal je abgelaufenem Timer. Ohne hinterlegte Datei bleibt es beim roten Ring.

Die mitgelieferten Methoden-/Sozialform- und Materialkataloge lassen sich in der Verwaltung bearbeiten. Eigene Einträge können ergänzt, umbenannt, sortiert oder gelöscht werden. Für jeden Eintrag kann ein eigenes PNG-, JPG- oder SVG-Symbol gewählt werden. Importierte Bilder werden in den lokalen Einstellungsordner kopiert und bleiben daher auch erhalten, wenn die ursprüngliche Datei später verschoben wird.

### Symbole

Die mitgelieferten Symbole liegen in `assets/icons/` als PNG mit transparentem Hintergrund; der Dateiname entspricht dem `icon_key` des Eintrags. Die farbige Kachel darunter zeichnet das Programm selbst, damit Auswahlzustand und Umgebung steuerbar bleiben. Fehlt eine Datei, wird ersatzweise ein einfaches Vektorsymbol gezeichnet.

Ein ganzes Symbolblatt lässt sich in einem Zug in Einzeldateien zerlegen:

```bash
python tools/slice_icon_sheet.py blatt.png --preview build/preview
```

## Boîte à Oublis verbinden (Companion-Modus ab v4.6.0)

Teacher Soundboard kann die Projektion von [Boîte à Oublis](https://github.com/florianchristophnowak-dot/boiteaoublis) fernsteuern: blättern, Unterstützungsstufe wechseln, aus- und einblenden, eine Live-Hilfe einwerfen. Beide Programme bleiben eigenständig – ohne das jeweils andere läuft alles unverändert weiter.

Die Verbindung arbeitet **ausschließlich auf diesem Rechner**: ein kleiner Zugang auf `127.0.0.1`, kein Konto, kein Server, keine Internetverbindung. Übertragen werden nur festgelegte Steuerbefehle und ein kurzer Zustandsbericht (Titel, Lerngruppe, Unterstützungsstufe, Seitenzahl, sichtbar oder ausgeblendet). **Wortschatzdaten bleiben vollständig in Boîte à Oublis.**

### Einrichten in drei Schritten

1. Verwaltung öffnen (`Strg+M` bzw. `Cmd+M`) → Abschnitt **Boîte à Oublis (Companion-Modus)**.
2. **Verbindung aktivieren** anhaken und mit **Datei wählen…** die portable Datei `dist/boite-a-oublis.html` auswählen.
3. **Öffnen und verbinden** anklicken. Boîte à Oublis startet im Standardbrowser und meldet sich sofort an.

Die Kopplung wird gespeichert und beim nächsten Start automatisch wiederhergestellt. Öffnet sich Boîte à Oublis später von Hand, genügt dort *Daten → Teacher Soundboard → Verbinden*; Teacher Soundboard fragt dann einmalig nach. Bricht die Verbindung ab, sucht Boîte à Oublis von selbst wieder – ein Neustart ist nie nötig. Steuern darf immer nur ein Fenster: Ein zweites übernimmt, das erste sagt sichtbar Bescheid.

### Die Kachel im Panel

Unter *Anzeige → Boîte à Oublis* erscheint eine weitere Kachel im Unterrichtspanel – schriftlos wie die übrigen. Ihr Zustand ist auf einen Blick erkennbar:

| Kachel | Bedeutung |
|---|---|
| graue Leinwand, durchgestrichen | nicht verbunden |
| blaue, leere Leinwand | verbunden, keine Projektion |
| grüne Leinwand mit Zeilen | Sprachhilfe läuft; darunter zeigen ein, zwei oder drei Balken die Unterstützungsstufe |
| dunkle Leinwand mit Rollo, grüner Rand | Projektion ausgeblendet |

- **Linksklick:** aktuelle Sprachhilfe aus- oder wieder einblenden
- **Rechtsklick:** kompakte Steuerung mit Blättern, Stufe 1/2/3, Live-Hilfe, Beenden, Boîte à Oublis öffnen und den gemeinsamen Presets

### Gemeinsame Phasen-Presets

Ein Preset startet eine Unterrichtsaktivität in beiden Programmen zugleich: eine Wortbank oder Tafel aus Boîte à Oublis mit ihrer Start-Unterstützungsstufe, dazu Sozialform, Material und Timerdauer im Soundboard, auf Wunsch mit sofortigem Timerstart.

Angelegt werden Presets in der Verwaltung unter *Gemeinsame Phasen-Presets*. Zur Szene einer Wortbank („Partnergespräch“, „Diskussion“ …) schlägt Teacher Soundboard eine passende Sozialform vor; die Zuordnung ist frei änderbar und wird auf Wunsch für die nächste Wortbank derselben Szene gemerkt. Umbenannte Szenen führen nicht ins Leere: Der Vorschlag entsteht über Ähnlichkeit, nicht über einen starren Textvergleich.

Gespeichert wird nur die Kennung des Ziels, dazu Titel und Lerngruppe als Beschriftung. Ist die Wortbank in Boîte à Oublis gelöscht, wird das Preset mit ⚠ als unvollständig markiert; der Unterrichtsteil wird dann nur nach ausdrücklicher Rückfrage angewendet.

Eine Wortbank einfach zu öffnen ändert am Soundboard nichts: Timer, Material und Sozialform ändern sich ausschließlich, wenn ein Preset ausdrücklich gestartet wird.

### Optionale globale Hotkeys

Für Sprachhilfe ein/aus, Blättern und die Unterstützungsstufen lassen sich eigene globale Hotkeys vergeben – in der Verwaltung im Abschnitt der Verbindung. Sie sind von Haus aus **leer** und können deshalb nicht mit den Klang- und Stopp-Hotkeys kollidieren; eine doppelte Belegung wird beim Eintragen abgelehnt.

### Wenn etwas nicht klappt

- **Der Browser blockiert das Beamerfenster.** Ein eigenes Fenster darf ein Browser nur nach einem Klick öffnen. Kommt der Wunsch über die Verbindung, zeigt Boîte à Oublis die Projektion zunächst als Vollbild in seinem Fenster und bietet eine Schaltfläche für das Beamerfenster an. Dauerhaft hilft es, Pop-ups für die Seite zu erlauben.
- **Kein freier Port.** Die Verbindung nutzt der Reihe nach `8317`, `8318` und `8319`. Sind alle drei belegt, meldet das die Verwaltung – Teacher Soundboard läuft normal weiter.
- **Boîte à Oublis öffnet sich ohne Einladung.** Dann in der App unter *Daten* auf **Verbinden** klicken und die Rückfrage im Soundboard bestätigen.

## Zuverlässige Medienformate

Für den problemlosen Einsatz auf beiden Systemen werden empfohlen:

| Typ | Empfehlung |
|---|---|
| Audio | MP3 oder WAV |
| Video | MP4 mit H.264-Video und AAC-Audio |
| Button-Bilder | PNG oder JPG |

Weitere Formate können funktionieren, hängen aber von den auf dem jeweiligen System verfügbaren Codecs ab.

## Stabilitätsfunktionen ab v4.3.0

- getrennte, native macOS-Pakete für Intel und Apple Silicon
- installierbare Windows-x64-Version statt einer selbstentpackenden Einzel-EXE
- Starttests für Quellcode und fertige Pakete auf allen drei Ziel-Runnern
- atomare Konfigurationsspeicherung mit toleranter Wiederherstellung ungültiger Werte
- stabile Audio-Geräte-IDs und automatischer Fallback auf die Systemausgabe
- Hotkey-Fallback, wenn ein Backend oder die macOS-Freigabe fehlt
- Schutz vor mehreren gleichzeitig laufenden Instanzen
- robustere Videoanzeige und Neupositionierung bei Monitorwechseln
- lokales Absturzprotokoll `TeacherSoundboard-crash.log`

## Neu in v4.6.0

- optionaler Companion-Modus: lokale Verbindung zu Boîte à Oublis über `127.0.0.1`
- schriftlose Boîte-Kachel im Unterrichtspanel mit den Zuständen „getrennt“, „bereit“, „Sprachhilfe läuft“, „ausgeblendet“ und den Unterstützungsstufen 1–3
- kompakte Steuerung für Blättern, Stufen, Live-Hilfe und Beenden
- gemeinsame Phasen-Presets für Wortbank, Sozialform, Material und Timer
- frei belegbare, standardmäßig leere globale Hotkeys für die Sprachhilfe

## Speicherorte

Die Einstellungen und ein eventuelles Absturzprotokoll liegen pro Benutzer unter:

- Windows: `%APPDATA%\TeacherSoundboard`
- macOS: `~/Library/Application Support/TeacherSoundboard`

Eine vorhandene macOS-Konfiguration aus Version 4.2 wird beim ersten Start automatisch aus `~/.config/TeacherSoundboard` übernommen.

## Entwicklung

```bash
python -m venv .venv
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
python soundboard.py
```

Ein Paket-Selbsttest ist ohne Benutzeroberfläche möglich:

```bash
python soundboard.py --self-test
```

GitHub Actions baut bei jedem Pull Request den Windows-Installer sowie beide macOS-Varianten. Ein Tag wie `v4.4.0` erstellt daraus automatisch ein GitHub Release.

## Lizenz

MIT License — © Florian Nowak
