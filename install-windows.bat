@echo off
setlocal enabledelayedexpansion

:: Ensure window stays open no matter what
if not defined MNEME_WRAPPED (
    set "MNEME_WRAPPED=1"
    cmd /k "%~f0" %*
    exit /b
)

echo.
echo  ===================================================================
echo   MNEME INSTALLER
echo  ===================================================================
echo.

:: ── Check Python ──────────────────────────────────────────────────────

echo  [1/5] Checking Python installation...

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo   Python is not installed or not in PATH.
    echo.
    echo   Please install Python 3.9 or higher:
    echo     https://www.python.org/downloads/
    echo.
    echo   IMPORTANT: Check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

:: Check Python version (need 3.9+)
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PYVER=%%v
for /f "tokens=1,2 delims=." %%a in ("!PYVER!") do (
    set PYMAJOR=%%a
    set PYMINOR=%%b
)

if !PYMAJOR! lss 3 (
    echo   Python !PYVER! is too old. Please install Python 3.9 or higher.
    pause
    exit /b 1
)
if !PYMAJOR! equ 3 if !PYMINOR! lss 9 (
    echo   Python !PYVER! is too old. Please install Python 3.9 or higher.
    pause
    exit /b 1
)

echo        Python !PYVER! found.

:: ── Install dependencies ──────────────────────────────────────────────

echo.
echo  [2/5] Installing Python dependencies...
echo        This may take a minute...
echo.

python -m pip install --upgrade pip >nul 2>&1
python -m pip install -r "%~dp0requirements.txt"

if %errorlevel% neq 0 (
    echo.
    echo   Dependency installation failed.
    echo   Try running as administrator, or manually:
    echo     pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

echo.
echo        Dependencies installed.

:: ── Copy example files ────────────────────────────────────────────────

echo.
echo  [3/5] Preparing configuration files...

if not exist "%~dp0system_instructions.txt" (
    if exist "%~dp0system_instructions.example.txt" (
        copy "%~dp0system_instructions.example.txt" "%~dp0system_instructions.txt" >nul
        echo        System instructions created.
    )
)

:: Don't copy config.json — the in-app setup wizard handles this
echo        Configuration will be completed in the browser.

:: ── Tailscale (optional) ──────────────────────────────────────────────

echo.
echo  [4/5] Tailscale (recommended - required for phone access)
echo.

tailscale version >nul 2>&1
if %errorlevel% equ 0 (
    echo        Tailscale is already installed.
    goto :tailscale_done
)

echo        Mneme is designed to be used from your phone.
echo        Tailscale creates a secure private network so your
echo        phone can reach Mneme running on this computer.
echo        (Free for personal use, no port forwarding needed.)
echo.
set /p INSTALL_TS="        Install Tailscale? (y/n): "
if /i not "!INSTALL_TS!"=="y" (
    echo        Skipped. You can install Tailscale later from:
    echo          https://tailscale.com/download/windows
    goto :tailscale_done
)

echo.
echo        Downloading Tailscale installer...
echo.

:: Download via PowerShell (works on all Windows 10/11)
powershell -Command "& { Invoke-WebRequest -Uri 'https://pkgs.tailscale.com/stable/tailscale-setup-latest.exe' -OutFile '%TEMP%\tailscale-setup.exe' }" 2>nul

if exist "%TEMP%\tailscale-setup.exe" (
    echo        Running Tailscale installer...
    echo        (Follow the Tailscale setup window to sign in)
    echo.
    start /wait "" "%TEMP%\tailscale-setup.exe"
    del "%TEMP%\tailscale-setup.exe" >nul 2>&1
    echo        Tailscale installation complete.
) else (
    echo        Download failed. You can install Tailscale manually:
    echo          https://tailscale.com/download/windows
)
:tailscale_done

:: ── Shortcuts ────────────────────────────────────────────────────────

echo.
echo  [5/5] Creating shortcuts...

:: Create shortcuts via PowerShell (works with OneDrive-redirected Desktop)
set "PS1=%TEMP%\mneme_shortcuts.ps1"
(
    echo $ws = New-Object -ComObject WScript.Shell
    echo $desktop = $ws.SpecialFolders('Desktop'^)
    echo $mnemeDir = '%~dp0'
    echo $launchBat = '%~dp0scripts\launch.bat'
    echo $iconPath = '%~dp0Logos\mneme-tray.ico'
    echo.
    echo $sc = $ws.CreateShortcut("$desktop\Mneme.lnk"^)
    echo $sc.TargetPath = $launchBat
    echo $sc.WorkingDirectory = $mnemeDir
    echo $sc.IconLocation = $iconPath
    echo $sc.WindowStyle = 7
    echo $sc.Description = 'Start Mneme Memory System'
    echo $sc.Save(^)
    echo.
    echo $sc2 = $ws.CreateShortcut("${mnemeDir}Launch Mneme.lnk"^)
    echo $sc2.TargetPath = $launchBat
    echo $sc2.WorkingDirectory = $mnemeDir
    echo $sc2.IconLocation = $iconPath
    echo $sc2.WindowStyle = 7
    echo $sc2.Description = 'Start Mneme Memory System'
    echo $sc2.Save(^)
    echo.
    echo Write-Output "DESKTOP=$desktop"
) > "%PS1%"
for /f "tokens=1,* delims==" %%A in ('powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" 2^>^&1') do (
    if "%%A"=="DESKTOP" set "ACTUAL_DESKTOP=%%B"
)
set "PS_ERR=%errorlevel%"
del "%PS1%" >nul 2>&1

if %PS_ERR% neq 0 (
    echo        Shortcut creation failed. You can start Mneme manually:
    echo          python scripts/tray.py
    goto :shortcuts_done
)
if exist "%ACTUAL_DESKTOP%\Mneme.lnk" (
    echo        Desktop shortcut created.
) else (
    echo        Could not create desktop shortcut. You can start Mneme manually:
    echo          python scripts/tray.py
)
if exist "%~dp0Launch Mneme.lnk" (
    echo        Folder shortcut created.
)
:shortcuts_done

:: ── Done ──────────────────────────────────────────────────────────────

echo.
echo  ===================================================================
echo   INSTALLATION COMPLETE
echo  ===================================================================
echo.
echo   Next steps:
echo.
echo     1. Double-click the "Mneme" shortcut on your desktop
echo        (or run: python src/backend/server.py)
echo.
echo     2. Open http://localhost:8080 in your browser
echo.
echo     3. Complete the setup wizard with your API keys
echo.
echo     4. Start chatting!
echo.
echo  ===================================================================
echo.

set /p LAUNCH="  Launch Mneme now? (y/n): "
if /i "!LAUNCH!"=="y" (
    echo.
    echo  Starting Mneme...
    start "" pythonw "%~dp0scripts\tray.py"
    timeout /t 3 >nul
    start "" http://localhost:8080
)

echo.
pause
