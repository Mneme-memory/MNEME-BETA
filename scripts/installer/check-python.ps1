# check-python.ps1
# Finds a Python 3.9+ executable and writes its full path to $OutFile.
# Exit 0 if found, exit 1 if not found.

param([Parameter(Mandatory)][string]$OutFile)

function Find-PythonExe {
    param([string]$ExePath)
    $resolved = $ExePath
    if (-not (Test-Path $ExePath -ErrorAction SilentlyContinue)) {
        $cmd = Get-Command $ExePath -ErrorAction SilentlyContinue
        if (-not $cmd) { return $null }
        $resolved = $cmd.Source
    }
    try {
        $ver = (& $resolved --version 2>&1) -join " "
        if ($ver -match 'Python 3\.(\d+)' -and [int]$Matches[1] -ge 9) {
            return $resolved
        }
    } catch { }
    return $null
}

$candidates = @(
    'python',
    'python3'
)

# Attempt to ask the Python Launcher for Windows ('py.exe') where the latest python 3 is
$pyCmd = Get-Command 'py' -ErrorAction SilentlyContinue
if ($pyCmd) {
    try {
        $pyPath = (& $pyCmd.Source -3 -c "import sys; print(sys.executable)" 2>&1) -join ""
        if ($pyPath -match 'python\.exe$') {
            $candidates += $pyPath.Trim()
        }
    } catch { }
}

$candidates += @(
    "$env:LOCALAPPDATA\Programs\Python\Python314-arm64\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python313-arm64\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python312-arm64\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python39\python.exe",
    "C:\Program Files\Python314\python.exe",
    "C:\Program Files\Python313\python.exe",
    "C:\Program Files\Python312\python.exe",
    "C:\Program Files\Python311\python.exe",
    "C:\Program Files\Python310\python.exe",
    "C:\Program Files\Python39\python.exe",
    "C:\Python314\python.exe",
    "C:\Python313\python.exe",
    "C:\Python312\python.exe",
    "C:\Python311\python.exe",
    "C:\Python310\python.exe"
)

foreach ($c in $candidates) {
    $path = Find-PythonExe $c
    if ($path) {
        [System.IO.File]::WriteAllText($OutFile, $path)
        exit 0
    }
}

exit 1
