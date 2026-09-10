; ===== KVRouite Audio - the voice remover add-on =====
;
; Installs the files of the voice remover (PyTorch, ONNX Runtime and the
; separation models, about 900 MB) INTO an existing KVRouite installation of
; the same version. KVRouite itself ("Lite") runs without them; with them the
; switch "Remove voices" in the encoder setup becomes available.
;
; Built by build_with_pyinstaller.py --build-installer from the add-on folder
; dist\KVRouite_<ver>\KVRouite_<ver>_Audio\KVRouite_<ver>, which holds exactly
; the files the full build has and the Lite build does not.

#define MyAppName        "KVRouite Audio"
#define MyBaseAppName    "KVRouite"
#define MyAppPublisher   "ridewithoutstomach"
#define MyAppURL         "https://github.com/ridewithoutstomach/KVRouite"
; AppId of the base installer (installer\KVRouite.iss) - its InstallLocation
; is where the add-on belongs.
#define MyBaseAppId      "{C4E3D0F1-7E94-45F7-91D4-A32AB4E9KVR}"

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

#ifndef MyDistDir
  #define MyDistDir "dist\\KVRouite_" + MyAppVersion + "\\KVRouite_" + MyAppVersion + "_Audio\\KVRouite_" + MyAppVersion
#endif

#ifndef MyEula
  #define MyEula AddBackslash(SourcePath) + "AGREEMENT.txt"
#endif

[Setup]
AppId={{7A1F6C2E-3B58-4D9A-8E61-0C9D2F5AUDIO}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}

; Where the base installer put KVRouite; fallback if it is not registered.
DefaultDirName={reg:HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\{#MyBaseAppId}_is1,InstallLocation|{autopf}\{#MyBaseAppName}}
DefaultGroupName={#MyBaseAppName}
DisableProgramGroupPage=yes

OutputDir={#SourcePath}\..\dist\{#MyAppVersion}
OutputBaseFilename=KVRouite_v{#MyAppVersion}_Audio_Win_x64_Installer

WizardStyle=modern
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
PrivilegesRequired=admin
UninstallDisplayIcon={app}\KVRouite.exe
; The add-on goes into the base folder, which exists by design.
DirExistsWarning=no
UsePreviousAppDir=no
LicenseFile={#MyEula}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
; Only the add-on files. NO cleanup of the target folder - it holds KVRouite.
Source: "{#MyDistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Code]
{ The add-on only makes sense on top of KVRouite of the SAME version: the
  Python code of the audio libraries sits inside KVRouite.exe, the add-on
  brings their binaries and models. A mismatch would not start. }
function VersionInFolder(Dir: string): string;
var
  Lines: TArrayOfString;
begin
  Result := '';
  if LoadStringsFromFile(AddBackslash(Dir) + 'version.txt', Lines) then
    if GetArrayLength(Lines) > 0 then
      Result := Trim(Lines[0]);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Dir, Ver: string;
begin
  Result := True;
  if CurPageID = wpSelectDir then
  begin
    Dir := WizardDirValue;
    if not FileExists(AddBackslash(Dir) + 'KVRouite.exe') then
    begin
      MsgBox('KVRouite is not installed in this folder:' + #13#10 + Dir + #13#10#13#10 +
             'Install KVRouite {#MyAppVersion} first, then this add-on into the same folder.',
             mbError, MB_OK);
      Result := False;
      exit;
    end;
    Ver := VersionInFolder(Dir);
    if Ver <> '{#MyAppVersion}' then
    begin
      MsgBox('This add-on is for KVRouite {#MyAppVersion}, but the folder holds version ' +
             Ver + '.' + #13#10 + 'Install the matching KVRouite first.',
             mbError, MB_OK);
      Result := False;
    end;
  end;
end;
