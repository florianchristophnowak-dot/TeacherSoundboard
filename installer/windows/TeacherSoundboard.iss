#define MyAppName "Teacher Soundboard"
#define MyAppVersion "4.3.0"
#define MyAppPublisher "Florian Nowak"
#define MyAppExeName "TeacherSoundboard.exe"
#define RepoRoot AddBackslash(SourcePath) + "..\..\"

[Setup]
AppId={{D5F72581-8FCD-4DA3-A9B9-03257C4F52B7}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\Teacher Soundboard
DefaultGroupName=Teacher Soundboard
DisableProgramGroupPage=yes
OutputDir={#RepoRoot}dist
OutputBaseFilename=TeacherSoundboard-Windows-x64-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
CloseApplications=yes
RestartApplications=no
SetupLogging=yes
VersionInfoVersion=4.3.0.0
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} Installer
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "Desktop-Verknüpfung erstellen"; GroupDescription: "Zusätzliche Verknüpfungen:"; Flags: unchecked

[Files]
Source: "{#RepoRoot}dist\TeacherSoundboard\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Teacher Soundboard"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\Teacher Soundboard"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Teacher Soundboard starten"; Flags: nowait postinstall skipifsilent
