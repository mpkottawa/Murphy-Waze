#define AppVersion Trim(FileRead(FileOpen("..\VERSION.txt")))
[Setup]
AppId={{B487B552-C4DA-4FBA-8B22-B1D6F35773A0}
AppName=Waze Voice Studio
AppVersion={#AppVersion}
AppPublisher=mpkottawa
AppPublisherURL=https://github.com/mpkottawa/Waze-Voice-Studio
AppSupportURL=https://github.com/mpkottawa/Waze-Voice-Studio/issues
DefaultDirName={localappdata}\Programs\Waze Voice Studio
DefaultGroupName=Waze Voice Studio
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=Waze-Voice-Studio-{#AppVersion}-Windows-x64-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
LicenseFile=..\LICENSE
InfoBeforeFile=installer-info.txt
UninstallDisplayName=Waze Voice Studio
DisableProgramGroupPage=yes
CloseApplications=no
[Files]
Source: "..\VERSION.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\Open Waze Voice Studio.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\Sign in to Codex.cmd"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\Repair dependency setup.cmd"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\00database\Tools\*.py"; DestDir: "{app}\00database\Tools"; Excludes: "test_*"; Flags: ignoreversion
Source: "..\00database\Tools\requirements*.txt"; DestDir: "{app}\00database\Tools"; Flags: ignoreversion
Source: "..\00database\Tools\engine_support\*"; DestDir: "{app}\00database\Tools\engine_support"; Excludes: "__pycache__,*.pyc"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\00database\Tools\reference\file_upload.py"; DestDir: "{app}\00database\Tools\reference"; Flags: ignoreversion
Source: "setup.ps1"; DestDir: "{app}\packaging"; Flags: ignoreversion
Source: "dependencies.json"; DestDir: "{app}\packaging"; Flags: ignoreversion
[Icons]
Name: "{group}\Waze Voice Studio"; Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""{app}\Open Waze Voice Studio.ps1"""; WorkingDir: "{app}"
Name: "{group}\Repair dependency setup"; Filename: "{app}\Repair dependency setup.cmd"; WorkingDir: "{app}"
Name: "{group}\Sign in to Codex"; Filename: "{app}\Sign in to Codex.cmd"; WorkingDir: "{app}"
Name: "{group}\Installation guide"; Filename: "{app}\README.md"
Name: "{autodesktop}\Waze Voice Studio"; Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""{app}\Open Waze Voice Studio.ps1"""; WorkingDir: "{app}"
[Code]
var DependencySetupFailed: Boolean;

function GetCustomSetupExitCode: Integer;
begin
  if DependencySetupFailed then Result := 1 else Result := 0;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var ResultCode: Integer;
begin
  if CurStep = ssPostInstall then begin
    WizardForm.StatusLabel.Caption := 'Installing dependencies. Downloads may take several minutes...';
    if not Exec(ExpandConstant('{sysnative}\WindowsPowerShell\v1.0\powershell.exe'),
      ExpandConstant('-NoProfile -ExecutionPolicy Bypass -File "{app}\packaging\setup.ps1" -AppRoot "{app}"'),
      ExpandConstant('{app}\00database\Tools'), SW_SHOWNORMAL, ewWaitUntilTerminated, ResultCode) then
      ResultCode := 1;
    DependencySetupFailed := ResultCode <> 0;
    if DependencySetupFailed then
      SuppressibleMsgBox('The app files were installed, but dependency setup did not finish. Use Repair dependency setup from the Start menu to retry. Details are in .runtime\setup.log inside your installation folder.', mbError, MB_OK, IDOK)
    else
      SuppressibleMsgBox('Setup finished. Open VoiceStudio to finish its first-run runtime and model setup. For automatic reference review, use Sign in to Codex in the Start menu. Then open Waze Voice Studio.', mbInformation, MB_OK, IDOK);
  end;
end;
