# 🎓 Teacher Soundboard

[![Build](https://github.com/florianchristophnowak-dot/TeacherSoundboard/actions/workflows/build.yml/badge.svg)](https://github.com/florianchristophnowak-dot/TeacherSoundboard/actions/workflows/build.yml)
[![Release](https://img.shields.io/github/v/release/florianchristophnowak-dot/TeacherSoundboard?include_prereleases)](https://github.com/florianchristophnowak-dot/TeacherSoundboard/releases/latest)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Ein lokales Soundboard für den Unterricht mit visuellen Münz-Buttons, Audio- und Videowiedergabe sowie frei konfigurierbaren Hotkeys.

## Download

| System | Empfohlener Download | Alternative |
|---|---|---|
| Windows 10/11 (x64) | [Windows-Installer](https://github.com/florianchristophnowak-dot/TeacherSoundboard/releases/latest/download/TeacherSoundboard-Windows-x64-Setup.exe) | [Portable ZIP](https://github.com/florianchristophnowak-dot/TeacherSoundboard/releases/latest/download/TeacherSoundboard-Windows-x64.zip) |
| macOS 12+ (Apple Silicon: M1–M4) | [DMG](https://github.com/florianchristophnowak-dot/TeacherSoundboard/releases/latest/download/TeacherSoundboard-macOS-Apple-Silicon.dmg) | [App als ZIP](https://github.com/florianchristophnowak-dot/TeacherSoundboard/releases/latest/download/TeacherSoundboard-macOS-Apple-Silicon.zip) |
| macOS 12+ (Intel) | [DMG](https://github.com/florianchristophnowak-dot/TeacherSoundboard/releases/latest/download/TeacherSoundboard-macOS-Intel.dmg) | [App als ZIP](https://github.com/florianchristophnowak-dot/TeacherSoundboard/releases/latest/download/TeacherSoundboard-macOS-Intel.zip) |

Die Download-Links funktionieren, sobald ein Release ab Version `v4.3.0` veröffentlicht wurde. Testpakete eines Pull Requests stehen am Ende des zugehörigen GitHub-Actions-Laufs unter „Artifacts“.

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

GitHub Actions baut bei jedem Pull Request den Windows-Installer sowie beide macOS-Varianten. Ein Tag wie `v4.3.0` erstellt daraus automatisch ein GitHub Release.

## Lizenz

MIT License — © Florian Nowak
