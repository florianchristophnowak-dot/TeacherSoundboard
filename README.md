# 🎓 Teacher Soundboard

[![Build](https://github.com/YOUR_USERNAME/TeacherSoundboard/actions/workflows/build.yml/badge.svg)](https://github.com/YOUR_USERNAME/TeacherSoundboard/actions/workflows/build.yml)
[![Release](https://img.shields.io/github/v/release/YOUR_USERNAME/TeacherSoundboard?include_prereleases)](https://github.com/YOUR_USERNAME/TeacherSoundboard/releases/latest)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Ein Soundboard mit visuellen Münz-Buttons für Lehrer – mit **Tastenkombinationen** und **Cross-Platform Support**!

![Screenshot](https://via.placeholder.com/800x400?text=Teacher+Soundboard+Screenshot)

---

## 📥 Download

| Plattform | Download |
|-----------|----------|
| **Windows** | [TeacherSoundboard-Windows.exe](https://github.com/YOUR_USERNAME/TeacherSoundboard/releases/latest/download/TeacherSoundboard-Windows.exe) |
| **macOS** | [TeacherSoundboard-macOS.zip](https://github.com/YOUR_USERNAME/TeacherSoundboard/releases/latest/download/TeacherSoundboard-macOS.zip) |
| **Linux** | [TeacherSoundboard-Linux](https://github.com/YOUR_USERNAME/TeacherSoundboard/releases/latest/download/TeacherSoundboard-Linux) |

> ⚠️ **Ersetze `YOUR_USERNAME` mit deinem GitHub-Benutzernamen!**

---

## ✨ Features

### 🎹 Tastenkombinationen (Hotkeys)

- **Globale Hotkeys**: Funktionieren auch wenn andere Programme im Fokus sind
  - Standard: `F1`-`F8` für die Buttons
  - `Escape` zum Stoppen
  - Individuell konfigurierbar im Manager
  
- **Lokale Hotkeys** (wenn Soundboard fokussiert):
  - `1`-`8`: Buttons direkt auslösen
  - `Escape` / `Space` / `S`: Wiedergabe stoppen
  - `Ctrl+M`: Manager öffnen
  - `T/B/L/R` oder Pfeiltasten: Andocken

### 🖥️ Cross-Platform

Läuft auf:
- ✅ Windows 10/11
- ✅ macOS 12+ (Intel & Apple Silicon)
- ✅ Linux (Ubuntu, Fedora, Arch)

### 🎨 Anpassbar

- Bis zu 8 Sound/Video-Buttons
- Eigene Button-Bilder (PNG/JPG)
- Andocken an allen Bildschirmrändern
- Wählbares Audio-Ausgabegerät

---

## 🚀 Installation

### Fertige Downloads (empfohlen)

1. Gehe zu [**Releases**](https://github.com/YOUR_USERNAME/TeacherSoundboard/releases/latest)
2. Lade die Version für dein System herunter
3. Starten!

### Aus Quellcode

```bash
git clone https://github.com/YOUR_USERNAME/TeacherSoundboard.git
cd TeacherSoundboard
pip install -r requirements.txt
python soundboard.py
```

---

## 📁 Unterstützte Formate

| Audio | Video | Bilder |
|-------|-------|--------|
| MP3, WAV, OGG, FLAC, M4A, AAC | MP4, MOV, MKV, AVI, WebM | PNG, JPG |

---

## ⚙️ Hotkeys konfigurieren

1. `Ctrl+M` oder Rechtsklick → "Verwalten..."
2. Im Bereich "Tastenkombinationen"
3. Klicke in ein Hotkey-Feld
4. Drücke die gewünschte Taste(n)
5. `Backspace` löscht den Hotkey

---

## 🔧 Für Entwickler

### Lokal bauen

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name "TeacherSoundboard" soundboard.py
```

### CI/CD

Jeder Push auf `main` löst automatische Builds aus. 
Ein Git-Tag (z.B. `v4.2.0`) erstellt ein Release mit Downloads.

```bash
git tag v4.2.0
git push origin v4.2.0
```

---

## 📜 Changelog

### v4.2.0
- ✅ Globale Hotkeys (F1-F8)
- ✅ Konfigurierbare Hotkeys
- ✅ Cross-Platform Builds
- ✅ GitHub Actions CI/CD

### v4.1.4
- Audio-Ausgabegerät wählbar
- Verbesserte Lautstärke-Kontrolle

---

## 📄 Lizenz

MIT License – Frei verwendbar für Lehrer und alle anderen! 🎓

---

## 🤝 Beitragen

Pull Requests willkommen! Bei Fragen oder Bugs → [Issue erstellen](https://github.com/YOUR_USERNAME/TeacherSoundboard/issues/new)
