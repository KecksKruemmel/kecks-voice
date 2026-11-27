; KecksVoice Installer – Inno Setup 7
; Build: ISCC.exe installer\KecksVoice.iss   (Ergebnis: installer\out\KecksVoice-Setup-<Version>.exe)

#define AppName "KecksVoice"
#define AppVersion "2.0"
#define AppPublisher "KecksKruemmel"
#define AppURL "https://github.com/KecksKruemmel/kecks-voice"
#define AppExe "KecksVoice.exe"

[Setup]
AppId={{FA9A63A7-6079-418F-A067-60D69497403E}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
AppComments=Diktieren in jedes Programm – lokal, ohne Cloud und ohne Konto.
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=out
OutputBaseFilename=KecksVoice-Setup-{#AppVersion}
SetupIconFile=..\kecksvoice.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
WizardImageFile=wizard.bmp
WizardSmallImageFile=wizard_small.bmp
WizardImageStretch=no
WizardSizePercent=110
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
LicenseFile=..\LICENSE
ShowLanguageDialog=auto
VersionInfoVersion={#AppVersion}.0
VersionInfoCompany={#AppPublisher}
VersionInfoDescription={#AppName} Setup
VersionInfoProductName={#AppName}
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Verknüpfung auf dem Desktop erstellen"; GroupDescription: "Zusätzliche Verknüpfungen:"; Flags: unchecked

[Files]
Source: "..\dist\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: isreadme ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\{#AppExe}"
Name: "{group}\{#AppName} deinstallieren"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: files; Name: "{app}\kecksvoice.json"

[Messages]
german.WelcomeLabel2=Dieser Assistent installiert {#AppName} {#AppVersion} auf deinem Computer.%n%nKecksVoice läuft komplett lokal: kein Konto, keine Cloud, kein Audio verlässt deinen PC.%n%nDu brauchst keine Administrator-Rechte.
english.WelcomeLabel2=This wizard installs {#AppName} {#AppVersion} on your computer.%n%nKecksVoice runs entirely locally: no account, no cloud, no audio leaves your PC.%n%nNo administrator rights are needed.
