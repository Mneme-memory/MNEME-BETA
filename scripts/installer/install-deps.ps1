# install-deps.ps1
# Installs Mneme Python dependencies.

param(
    [Parameter(Mandatory)][string]$PythonExe,
    [Parameter(Mandatory)][string]$MnemeDir
)

$req = Join-Path $MnemeDir "requirements.txt"

# On ARM64, the direct python.exe may be an AppExecLink that PS can't invoke.
# Verify it works; if not, fall back to the py launcher.
$python = $PythonExe
$pyArgs = @()
try {
    & $python --version 2>&1 | Out-Null
} catch {
    $python = (Get-Command 'py' -ErrorAction Stop).Source
    $pyArgs = @('-3')
}

Write-Host "Upgrading pip..."
& $python @pyArgs -m pip install --upgrade pip --quiet

Write-Host "Installing dependencies..."
& $python @pyArgs -m pip install -r $req

exit $LASTEXITCODE
