# install-tailscale.ps1
# Checks for Tailscale and installs it if missing.
# Exit 0 if already installed or successfully installed, exit 1 on failure.

$tailscale = Get-Command tailscale -ErrorAction SilentlyContinue
if ($tailscale) {
    Write-Host "Tailscale already installed"
    exit 0
}

$url = "https://pkgs.tailscale.com/stable/tailscale-setup-latest.exe"
$installer = "$env:TEMP\tailscale-setup.exe"

Write-Host "Downloading Tailscale..."
try {
    Invoke-WebRequest -Uri $url -OutFile $installer -UseBasicParsing
} catch {
    Write-Host "Download failed: $_"
    exit 1
}

Write-Host "Installing Tailscale..."
$proc = Start-Process $installer -ArgumentList "/quiet" -Wait -PassThru
Remove-Item $installer -Force -ErrorAction SilentlyContinue

if ($proc.ExitCode -eq 0) {
    Write-Host "Tailscale installed successfully"
    exit 0
} else {
    Write-Host "Tailscale installer exited with code $($proc.ExitCode)"
    exit 1
}
