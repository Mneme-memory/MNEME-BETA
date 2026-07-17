# install-python.ps1
# Installs Python 3.12 via winget (primary) or direct download (fallback).
# Exit 0 on success, exit 1 on failure.

param([string]$LogFile = "$env:TEMP\mneme-python-install.log")

function Log { param($msg) $msg | Add-Content -Path $LogFile; Write-Host $msg }

Log "=== Mneme: Installing Python ==="

# --- Try winget ---
$winget = Get-Command winget -ErrorAction SilentlyContinue
if ($winget) {
    Log "Trying winget..."
    $proc = Start-Process winget -ArgumentList @(
        'install', 'Python.Python.3.12',
        '--silent', '--accept-package-agreements', '--accept-source-agreements',
        '--architecture', 'x64'
    ) -Wait -PassThru -NoNewWindow
    # winget exit -1978335189 = package already installed (APPINSTALLER_ERROR_ALREADY_INSTALLED)
    if ($proc.ExitCode -eq 0 -or $proc.ExitCode -eq -1978335189) {
        Log "winget succeeded (exit $($proc.ExitCode))"
        exit 0
    }
    Log "winget failed (exit $($proc.ExitCode)) - falling back to direct download"
}

# --- Direct download fallback ---
$pythonVersion = "3.12.9"
$url = "https://www.python.org/ftp/python/$pythonVersion/python-$pythonVersion-amd64.exe"
$installer = "$env:TEMP\python-installer.exe"

Log "Downloading Python $pythonVersion from python.org..."
try {
    Invoke-WebRequest -Uri $url -OutFile $installer -UseBasicParsing
} catch {
    Log "Download failed: $_"
    exit 1
}

Log "Running Python installer silently..."
$proc = Start-Process $installer -ArgumentList @(
    '/quiet',
    'InstallAllUsers=0',
    'PrependPath=1',
    'Include_pip=1',
    'Include_tcltk=0'
) -Wait -PassThru

Remove-Item $installer -Force -ErrorAction SilentlyContinue

if ($proc.ExitCode -eq 0) {
    Log "Python $pythonVersion installed successfully"
    exit 0
} else {
    Log "Python installer exited with code $($proc.ExitCode)"
    exit 1
}
