#define AppVersion Trim(FileRead(FileOpen("..\VERSION.txt")))
[Setup]
AppId={code:InstallationId}
AppName=Murphy Waze
AppVersion={#AppVersion}
AppPublisher=mpkottawa
AppPublisherURL=https://github.com/mpkottawa/Murphy-Waze
AppSupportURL=https://github.com/mpkottawa/Murphy-Waze/issues
DefaultDirName={localappdata}\Programs\Murphy Waze
DefaultGroupName=Murphy Waze
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=Murphy-Waze-{#AppVersion}-Windows-x64-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
LicenseFile=..\LICENSE
InfoBeforeFile=installer-info.txt
UninstallDisplayName=Murphy Waze
DisableProgramGroupPage=yes
UsePreviousLanguage=no
CloseApplications=no
[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: checkedonce
[Files]
Source: "..\build\payload\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[InstallDelete]
Type: files; Name: "{app}\assets\waze-voice-studio-murph-cat.ico"
Type: files; Name: "{app}\assets\waze-voice-studio-murph.png"
Type: files; Name: "{app}\assets\waze-voice-studio-murph.ico"
[Icons]
Name: "{group}\Murphy Waze"; Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""{app}\Open Murphy Waze.ps1"""; WorkingDir: "{app}"; IconFilename: "{app}\assets\murphy-waze-white-mkz.ico"; AppUserModelID: "mpkottawa.WazeVoiceStudio"; Check: not IsTestInstall
Name: "{group}\Repair dependency setup"; Filename: "{app}\Repair dependency setup.cmd"; WorkingDir: "{app}"; Check: not IsTestInstall
Name: "{group}\Set up local reference review"; Filename: "{app}\Set up local reference review.cmd"; WorkingDir: "{app}"; Check: not IsTestInstall
Name: "{group}\Installation guide"; Filename: "{app}\README.md"; Check: not IsTestInstall
Name: "{autodesktop}\Murphy Waze"; Tasks: desktopicon; Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""{app}\Open Murphy Waze.ps1"""; WorkingDir: "{app}"; IconFilename: "{app}\assets\murphy-waze-white-mkz.ico"; AppUserModelID: "mpkottawa.WazeVoiceStudio"; Check: not IsTestInstall
[Code]
var DependencySetupFailed: Boolean;

function IsTestInstall: Boolean;
begin
  Result := ExpandConstant('{param:TestInstall|0}') = '1';
end;

function InstallationId(Param: String): String;
begin
  if IsTestInstall then Result := 'MurphyWaze-InstallerValidation'
  else Result := '{B487B552-C4DA-4FBA-8B22-B1D6F35773A0}';
end;

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
      ExpandConstant('{app}\00database\Tools'), SW_HIDE, ewWaitUntilTerminated, ResultCode) then
      ResultCode := 1;
    DependencySetupFailed := ResultCode <> 0;
    if DependencySetupFailed then
      SuppressibleMsgBox('The app files were installed, but dependency setup did not finish. Use Repair dependency setup from the Start menu to retry. Details are in .runtime\setup.log inside your installation folder.', mbError, MB_OK, IDOK)
    else
      SuppressibleMsgBox('Setup finished. Open Murphy Waze, then Settings / updates to connect ChatGPT and select a model. Speaker separation may require your Hugging Face sign-in and model consent. Your voices and preferences are preserved on upgrades.', mbInformation, MB_OK, IDOK);
  end;
end;
