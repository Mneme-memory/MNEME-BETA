; Mneme-Installer.iss
; Build: open in Inno Setup Compiler and press Compile (or Ctrl+F9).
; Output: Mneme-Setup.exe lands in the Mneme root folder.
;
; This installer is designed to be run from within the cloned/downloaded
; Mneme folder. It detects its own location and treats that as the app root.

#define MyAppName    "Mneme"
#define MyAppVersion "14.0.0"
#define MyAppPublisher "Mikael Huuhtanen"
#define MyAppURL     "https://github.com/Mneme-memory/MNEME-BETA"

[Setup]
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}

; The "install directory" is wherever the user already has Mneme.
; Detect at runtime (see GetInstallDir in [Code]). Don't create it.
DefaultDirName={code:GetInstallDir}
CreateAppDir=no
DisableWelcomePage=no
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes

; Output the compiled exe to the Mneme root (two levels up from scripts/installer/)
OutputDir=..\..\
OutputBaseFilename=Mneme-Setup
SetupIconFile=..\..\Logos\mneme-tray.ico
WizardImageFile=wizard-banner.png
WizardSmallImageFile=wizard-icon.png

Compression=lzma2
SolidCompression=yes
WizardStyle=dark
WizardBackColor=$242626
WizardImageStretch=yes
PrivilegesRequired=lowest
Uninstallable=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
english.FinishedHeadingLabel=Mneme is ready.
english.ClickFinish=You can now launch Mneme from the desktop shortcut.


[Code]

var
  TailscalePage: TWizardPage;
  SkipTailscale: TNewCheckBox;
  PythonExe:     String;    // resolved python.exe path

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False; // always show Welcome so WizardImageFile renders
end;

// ── Helpers ──────────────────────────────────────────────────────────────

function GetInstallDir(Param: String): String;
begin
  // The installer exe sits in the Mneme root — use its directory as app root.
  Result := ExtractFileDir(ExpandConstant('{srcexe}'));
end;

function ScriptDir(): String;
begin
  Result := GetInstallDir('') + '\scripts\installer';
end;

function RunPS(Script, Args, Capture: String): Integer;
// Run a PowerShell script. If Capture <> '', stdout+stderr go to that file.
var
  CmdLine: String;
  RC: Integer;
begin
  CmdLine := '-NoProfile -ExecutionPolicy Bypass -File "' + Script + '"';
  if Args <> '' then
    CmdLine := CmdLine + ' ' + Args;
  if Capture <> '' then
    CmdLine := CmdLine + ' > "' + Capture + '" 2>&1';
  Exec('powershell.exe', CmdLine, '', SW_HIDE, ewWaitUntilTerminated, RC);
  Result := RC;
end;

// ── Python detection ──────────────────────────────────────────────────────

function FindPython(): String;
// Returns path to a Python 3.9+ exe, or '' if not found.
// check-python.ps1 writes the path directly to OutFile — no shell redirect needed.
var
  TempFile: String;
  Lines: TArrayOfString;
  RC: Integer;
begin
  Result := '';
  TempFile := ExpandConstant('{tmp}\mneme_pypath.txt');
  DeleteFile(TempFile);
  RC := RunPS(ScriptDir() + '\check-python.ps1', '-OutFile "' + TempFile + '"', '');
  if RC = 0 then
    if LoadStringsFromFile(TempFile, Lines) and (Length(Lines) > 0) then
      Result := Trim(Lines[0]);
  DeleteFile(TempFile);
end;

// ── Custom wizard pages ───────────────────────────────────────────────────

procedure InitializeWizard();
var
  Body: TNewStaticText;
begin
  // Tailscale explanation page — shown before the install step
  TailscalePage := CreateCustomPage(
    wpWelcome,
    'Phone Access',
    'Mneme is built to be used from your phone'
  );

  Body := TNewStaticText.Create(TailscalePage);
  Body.Parent := TailscalePage.Surface;
  Body.Left   := 0;
  Body.Top    := 0;
  Body.Width  := TailscalePage.SurfaceWidth;
  Body.AutoSize  := True;
  Body.WordWrap  := True;
  Body.Caption   :=
    'Mneme runs in your phone''s browser — you can add it to your home screen ' +
    'and open it like a native app.' + #13#10 + #13#10 +
    'To connect your phone to the server running on this computer, we''ll ' +
    'install Tailscale: a free, encrypted private network between your devices. ' +
    'No port forwarding or router settings needed.' + #13#10 + #13#10 +
    'After Mneme is set up, you''ll sign into Tailscale on both your computer ' +
    'and phone (same account, takes about 30 seconds). Then open Mneme on your ' +
    'phone by going to your computer''s Tailscale address in any browser.' + #13#10 + #13#10 +
    'Tailscale is free for personal use.';

  SkipTailscale := TNewCheckBox.Create(TailscalePage);
  SkipTailscale.Parent  := TailscalePage.Surface;
  SkipTailscale.Left    := 0;
  SkipTailscale.Top     := Body.Top + Body.Height + 24;
  SkipTailscale.Width   := TailscalePage.SurfaceWidth;
  SkipTailscale.Height  := 17;
  SkipTailscale.Caption := 'Skip Tailscale — I only want to use Mneme on this computer';
  SkipTailscale.Checked := False;
end;

// ── Main install logic ────────────────────────────────────────────────────

procedure SetStatus(Msg: String);
begin
  WizardForm.StatusLabel.Caption := Msg;
  WizardForm.StatusLabel.Refresh();
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  MnemeDir, LogFile: String;
  RC: Integer;
begin
  if CurStep <> ssInstall then Exit;

  MnemeDir := GetInstallDir('');
  LogFile  := ExpandConstant('{tmp}\mneme-install.log');

  // ── 1. Python ───────────────────────────────────────────────────────
  SetStatus('Checking Python...');
  PythonExe := FindPython();

  if PythonExe = '' then begin
    SetStatus('Installing Python 3.12 (this takes a minute)...');
    RC := RunPS(ScriptDir() + '\install-python.ps1',
      '-LogFile "' + LogFile + '"', '');
    if RC <> 0 then begin
      MsgBox(
        'Python installation failed.' + #13#10 + #13#10 +
        'Please install Python 3.9+ manually from python.org ' +
        '(check "Add Python to PATH" during installation), ' +
        'then run Mneme-Setup.exe again.',
        mbError, MB_OK);
      WizardForm.Close();
      Exit;
    end;
    PythonExe := ExpandConstant('{localappdata}') + '\Programs\Python\Python312\python.exe';
    if not FileExists(PythonExe) then
      PythonExe := FindPython();
    if PythonExe = '' then begin
      MsgBox(
        'Python was installed but could not be located.' + #13#10 + #13#10 +
        'Please restart your computer and run Mneme-Setup.exe again.',
        mbError, MB_OK);
      WizardForm.Close();
      Exit;
    end;
  end;

  // ── 2. Dependencies ─────────────────────────────────────────────────
  SetStatus('Installing packages (this may take a minute)...');
  RC := RunPS(ScriptDir() + '\install-deps.ps1',
    '-PythonExe "' + PythonExe + '" -MnemeDir "' + MnemeDir + '"', '');
  if RC <> 0 then begin
    MsgBox(
      'Package installation failed.' + #13#10 + #13#10 +
      'Check your internet connection, then try running:' + #13#10 +
      'pip install -r requirements.txt' + #13#10 + #13#10 +
      'A log is at: ' + LogFile,
      mbError, MB_OK);
    WizardForm.Close();
    Exit;
  end;

  // ── 3. System instructions (first-time only) ────────────────────────
  if not FileExists(MnemeDir + '\system_instructions.txt') then
    if FileExists(MnemeDir + '\system_instructions.example.txt') then
      CopyFile(MnemeDir + '\system_instructions.example.txt',
               MnemeDir + '\system_instructions.txt', True);

  // ── 4. Tailscale ────────────────────────────────────────────────────
  if not SkipTailscale.Checked then begin
    SetStatus('Installing Tailscale...');
    RC := RunPS(ScriptDir() + '\install-tailscale.ps1', '', '');
    // Don't abort on Tailscale failure — it can be installed later
    if RC <> 0 then
      MsgBox(
        'Tailscale could not be installed automatically.' + #13#10 +
        'You can install it later from tailscale.com/download. ' +
        'Mneme will still work from this computer in the meantime.',
        mbInformation, MB_OK);
  end;

  // ── 5. Shortcuts ────────────────────────────────────────────────────
  SetStatus('Creating shortcuts...');
  RunPS(ScriptDir() + '\create-shortcuts.ps1',
    '-MnemeDir "' + MnemeDir + '"', '');
end;
