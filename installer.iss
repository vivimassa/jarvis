; ============================================================================
; JARVIS — Inno Setup installer script
;
; Builds a per-user Windows installer (no admin required) from the PyInstaller
; onedir output in dist\JARVIS.
;
; Prerequisites:
;   1. Build the app first:   .\build.ps1     (produces dist\JARVIS\JARVIS.exe)
;   2. Install Inno Setup:    https://jrsoftware.org/isdl.php
;   3. Compile:               open this file in Inno Setup and click Compile,
;                             or run:  iscc installer.iss
;   Output:                   Output\JARVIS-Setup.exe
;
; Keys, memory, and logs live in %APPDATA%\JARVIS — NOT under the install dir —
; so uninstalling/reinstalling never touches user data.
; ============================================================================

#define MyAppName    "JARVIS"
#define MyAppVersion "48.1"
#define MyAppExeName "JARVIS.exe"
#define MyAppPublisher "Community fork of MARK XLVIII by FatihMakes"
#define MyAppURL     "https://www.youtube.com/@FatihMakes"

[Setup]
AppId={{7A2F1C64-3B5E-4D9A-9E21-JARVISMARK48}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=Output
OutputBaseFilename=JARVIS-Setup
SetupIconFile=config\jarvis.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
LicenseFile=LICENSE

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"
Name: "startupicon"; Description: "Start JARVIS automatically when I sign in"; GroupDescription: "Startup:"; Flags: unchecked

[Files]
; The entire PyInstaller onedir bundle (exe + _internal + assets)
Source: "dist\JARVIS\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; Optional "start on login" — added only if the user ticks the startup task.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "JARVIS"; ValueData: """{app}\{#MyAppExeName}"""; \
    Flags: uninsdeletevalue; Tasks: startupicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch JARVIS now"; \
    Flags: nowait postinstall skipifsilent
