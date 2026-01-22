# 🚀 GitHub Repository einrichten – Schritt für Schritt

Diese Anleitung erklärt, wie du das Repository auf GitHub einrichtest und automatische Builds bekommst.

---

## Schritt 1: GitHub Account

Falls du noch keinen hast:
1. Gehe zu https://github.com
2. Klicke "Sign up"
3. Erstelle einen Account

---

## Schritt 2: Neues Repository erstellen

1. Gehe zu https://github.com/new
2. Fülle aus:
   - **Repository name:** `TeacherSoundboard`
   - **Description:** `Soundboard für Lehrer mit Hotkeys`
   - **Public** (für kostenlose Actions)
   - ☐ NICHT "Add a README file" ankreuzen!
3. Klicke **"Create repository"**

---

## Schritt 3: Git installieren (falls nicht vorhanden)

### Windows:
1. Lade herunter: https://git-scm.com/download/win
2. Installiere mit Standard-Einstellungen

### Prüfen ob Git da ist:
```powershell
git --version
```

---

## Schritt 4: Dateien hochladen

Öffne PowerShell im Ordner `TeacherSoundboard_GitHub` und führe aus:

```powershell
# Git initialisieren
git init

# Alle Dateien hinzufügen
git add .

# Ersten Commit erstellen
git commit -m "Initial commit - Teacher Soundboard v4.2.0"

# GitHub als Remote hinzufügen (ERSETZE deinen-username!)
git remote add origin https://github.com/DEIN-USERNAME/TeacherSoundboard.git

# Hauptbranch umbenennen und pushen
git branch -M main
git push -u origin main
```

> ⚠️ **Wichtig:** Ersetze `DEIN-USERNAME` mit deinem GitHub-Benutzernamen!

---

## Schritt 5: GitHub Actions prüfen

1. Gehe zu deinem Repository auf GitHub
2. Klicke auf **"Actions"** Tab
3. Du solltest einen laufenden Build sehen! 🎉

Der Build dauert ca. 5-10 Minuten.

---

## Schritt 6: Downloads holen

Nach erfolgreichem Build:

1. Klicke auf den grünen ✓ Build
2. Scrolle runter zu **"Artifacts"**
3. Lade herunter:
   - `TeacherSoundboard-Windows`
   - `TeacherSoundboard-macOS`
   - `TeacherSoundboard-Linux`

---

## Schritt 7: Release erstellen (optional)

Für einen "offiziellen" Release mit Download-Links:

```powershell
# Tag erstellen
git tag v4.2.0

# Tag hochladen
git push origin v4.2.0
```

Das erstellt automatisch einen Release unter:
`https://github.com/DEIN-USERNAME/TeacherSoundboard/releases`

---

## 📝 README anpassen

Öffne `README.md` und ersetze alle `YOUR_USERNAME` mit deinem echten GitHub-Benutzernamen.

Dann:
```powershell
git add README.md
git commit -m "Update README with correct username"
git push
```

---

## ❓ Probleme?

### "Permission denied"
→ Du musst dich bei GitHub anmelden. Git fragt nach Username/Passwort oder Token.

### "Actions disabled"
→ Gehe zu Repository Settings → Actions → General → Aktiviere Actions

### Build schlägt fehl
→ Klicke auf den fehlgeschlagenen Build und schaue ins Log

---

## 🎉 Fertig!

Du hast jetzt:
- ✅ Automatische Builds für Windows, Mac, Linux
- ✅ Download-Links für alle Plattformen
- ✅ Versionierung mit Tags
- ✅ Professionelles Open-Source-Projekt!
