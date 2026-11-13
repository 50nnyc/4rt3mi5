; Instalador do app desktop (Inno Setup 6). Gerado por build.ps1:
;   ISCC.exe /DAppVersion=0.1.0 packaging\installer.iss
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{B3E1F7A2-58C4-4D9E-A1F0-7C2D4E6B9A35}
AppName=4rt3mi5
AppVersion={#AppVersion}
AppPublisher=4rt3mi5
DefaultDirName={localappdata}\Programs\4rt3mi5
DefaultGroupName=4rt3mi5
DisableProgramGroupPage=yes
DisableDirPage=yes
; Instala só para o usuário atual: não pede administrador e permite atualizar em silêncio.
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=4rt3mi5-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=force
UninstallDisplayIcon={app}\4rt3mi5.exe

[Languages]
Name: "ptbr"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na área de trabalho"; GroupDescription: "Atalhos:"

[Files]
Source: "..\dist\4rt3mi5\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; limpa arquivos da versão anterior
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\4rt3mi5"; Filename: "{app}\4rt3mi5.exe"
Name: "{autodesktop}\4rt3mi5"; Filename: "{app}\4rt3mi5.exe"; Tasks: desktopicon

[Run]
; instalação normal: oferece abrir no final
Filename: "{app}\4rt3mi5.exe"; Description: "Abrir o 4rt3mi5"; Flags: nowait postinstall skipifsilent
; atualização automática (silenciosa): reabre o app sozinho
Filename: "{app}\4rt3mi5.exe"; Flags: nowait; Check: WizardSilent
