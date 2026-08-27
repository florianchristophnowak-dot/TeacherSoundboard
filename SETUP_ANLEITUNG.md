# Builds und Releases auf GitHub

Das Repository ist bereits vollständig eingerichtet. GitHub Actions erstellt automatisch getestete Pakete für:

- Windows 10/11 x64: Installer und portable ZIP-Datei
- macOS 12+ Apple Silicon: DMG und ZIP-Datei
- macOS 12+ Intel: DMG und ZIP-Datei

## Testpakete eines Pull Requests herunterladen

1. Im Repository den Tab **Actions** öffnen.
2. Den gewünschten Lauf von **Build Teacher Soundboard** auswählen.
3. Nach einem vollständig grünen Lauf unten unter **Artifacts** das passende Paket herunterladen.

Artifacts sind für Tests gedacht und werden nach 14 Tagen automatisch gelöscht.

## Offizielles Release erstellen

Ein Release wird erst erzeugt, wenn ein Tag mit `v` am Anfang auf GitHub liegt. Beispiel für Version 4.3.0:

```powershell
git tag v4.3.0
git push origin v4.3.0
```

Der Workflow testet zuerst alle drei Pakete. Nur wenn Windows, Apple Silicon und Intel erfolgreich sind, wird das Release veröffentlicht.

## Prüfen

1. **Actions** öffnen und warten, bis Windows x64, macOS Apple-Silicon und macOS Intel grün sind.
2. **Releases** öffnen und das neue Release auswählen.
3. Prüfen, ob genau sechs Dateien vorhanden sind: zwei für Windows und je zwei für beide Mac-Architekturen.

## Wichtiger Hinweis zu macOS

Die automatischen Builds sind ad-hoc signiert, aber ohne Apple-Developer-Zertifikat nicht notarisiert. Der erste Start erfolgt daher gegebenenfalls über Rechtsklick → **Öffnen** oder über Systemeinstellungen → Datenschutz & Sicherheit → **Dennoch öffnen**.
