; GPU Task Manager installer - Inno Setup 6
;
; Built by scripts\build.ps1, which passes every product value below as /D from
; src\gtm_desktop\brand.py (the single place to rename the product). The defaults
; here only let the script compile on its own for a quick check.
;
; Per-user install: no UAC prompt, no admin rights, upgrades in place.
; Payload: the PyInstaller onedir folder (dist\<slug>\), notices included.

#ifndef AppName
  #define AppName       "GPU Task Manager"
#endif
#ifndef AppSlug
  #define AppSlug       "GPUTaskManager"
#endif
#ifndef AppVersion
  #define AppVersion    "0.1.0"
#endif
#ifndef AppPublisher
  #define AppPublisher  "Francesco Trani"
#endif
#ifndef AppURL
  #define AppURL        ""
#endif
#ifndef AppGuid
  #define AppGuid       "{5E1F7A2C-8B3D-4C6E-9A40-1D2F3B4C5A61}"
#endif
#ifndef AppExeName
  #define AppExeName    AppSlug + ".exe"
#endif
#ifndef AppMutex
  #define AppMutex      "Local\" + AppSlug + "-instance"
#endif
#ifndef RunValue
  #define RunValue      AppSlug
#endif
#ifndef SourceDir
  #define SourceDir     "..\dist\" + AppSlug
#endif

[Setup]
; Double brace: Inno reads "{{" as a literal "{" in AppId.
AppId={{#AppGuid}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
#if AppURL != ""
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
#endif
VersionInfoVersion={#AppVersion}
VersionInfoCompany={#AppPublisher}
VersionInfoProductName={#AppName}
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#AppExeName}

PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={localappdata}\Programs\{#AppSlug}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
UsePreviousAppDir=yes

; The running app holds this mutex: setup asks to close it before replacing files.
AppMutex={#AppMutex}
CloseApplications=force
RestartApplications=no

OutputDir=Output
OutputBaseFilename={#AppSlug}-Setup-{#AppVersion}
SetupIconFile=..\assets\app.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763

[Languages]
Name: "it"; MessagesFile: "compiler:Languages\Italian.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "pt_BR"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "fr"; MessagesFile: "compiler:Languages\French.isl"
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "de"; MessagesFile: "compiler:Languages\German.isl"
Name: "uk"; MessagesFile: "compiler:Languages\Ukrainian.isl"

[CustomMessages]
it.StartupGroup=Accesso a Windows
en.StartupGroup=Windows sign-in
it.AutostartTask=Avvia {#AppName} nell'area di notifica all'accesso
en.AutostartTask=Start {#AppName} in the notification area at sign-in
it.Licenses=Licenze di terze parti
en.Licenses=Third-party licenses
pt_BR.StartupGroup=Entrada no Windows
pt_BR.AutostartTask=Iniciar {#AppName} na área de notificação ao entrar
pt_BR.Licenses=Licenças de terceiros
fr.StartupGroup=Ouverture de session Windows
fr.AutostartTask=Lancer {#AppName} dans la zone de notification à l'ouverture de session
fr.Licenses=Licences tierces
es.StartupGroup=Inicio de sesión de Windows
es.AutostartTask=Iniciar {#AppName} en el área de notificación al iniciar sesión
es.Licenses=Licencias de terceros
de.StartupGroup=Windows-Anmeldung
de.AutostartTask={#AppName} bei der Anmeldung im Infobereich starten
de.Licenses=Lizenzen von Drittanbietern
uk.StartupGroup=Вхід у Windows
uk.AutostartTask=Запускати {#AppName} в області сповіщень під час входу
uk.Licenses=Ліцензії сторонніх розробників

[Tasks]
Name: "autostart";   Description: "{cm:AutostartTask}"; GroupDescription: "{cm:StartupGroup}"
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; Upgrades: drop the previous bundle so removed modules never linger next to new ones.
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\licenses"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}";        Filename: "{app}\{#AppExeName}"
Name: "{group}\{cm:Licenses}";     Filename: "{app}\THIRD-PARTY-NOTICES.txt"
Name: "{autodesktop}\{#AppName}";  Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Registry]
; Same value the app's Settings toggle writes (src\gtm_desktop\autostart.py).
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; \
  ValueName: "{#RunValue}"; ValueData: """{app}\{#AppExeName}"" --tray"; \
  Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; \
  Flags: nowait postinstall skipifsilent

[UninstallRun]
; Stop the tray app so its files can be removed. Exit code 128 (not running) is fine.
Filename: "{sys}\taskkill.exe"; Parameters: "/IM ""{#AppExeName}"" /F"; \
  Flags: runhidden waituntilterminated; RunOnceId: "StopApp"

[UninstallDelete]
; The Run value is also written by the in-app toggle (not tracked by Inno): remove it here.
Type: filesandordirs; Name: "{app}\_internal"

[Code]
// The uninstaller checks AppMutex BEFORE [UninstallRun], so a running tray app made it
// abort ("currently running"; silent mode defaults to Cancel). Stop the app first.
function InitializeUninstall(): Boolean;
var
  Code: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/IM "{#AppExeName}" /F', '', SW_HIDE,
       ewWaitUntilTerminated, Code);
  Sleep(500);
  Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    RegDeleteValue(HKEY_CURRENT_USER, 'Software\Microsoft\Windows\CurrentVersion\Run', '{#RunValue}');
end;
