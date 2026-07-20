param(
    [ValidateSet("x64", "arm64", "all")]
    [string]$Architecture = "all"
)

$ErrorActionPreference = "Stop"
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
if (-not (Test-Path -LiteralPath $vswhere)) {
    throw "Visual Studio Build Tools were not found."
}
$installation = (& $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath).Trim()
if (-not $installation) {
    throw "MSVC x64 build tools were not found."
}

$source = Join-Path $PSScriptRoot "runner.cpp"
$architectures = if ($Architecture -eq "all") { @("x64", "arm64") } else { @($Architecture) }
foreach ($target in $architectures) {
    $vcvars = if ($target -eq "arm64") { "vcvarsamd64_arm64.bat" } else { "vcvars64.bat" }
    $environmentScript = Join-Path $installation "VC\Auxiliary\Build\$vcvars"
    if (-not (Test-Path -LiteralPath $environmentScript)) {
        throw "The MSVC $target tools are not installed ($environmentScript is missing)."
    }
    $outputDirectory = Join-Path $PSScriptRoot "bin\$target"
    New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null
    $output = Join-Path $outputDirectory "mneme-runner.exe"
    $object = Join-Path $outputDirectory "runner.obj"
    $command = 'call "{0}" >nul && cl /nologo /std:c++17 /MT /W4 /WX /EHsc /DUNICODE /D_UNICODE /DWIN32_LEAN_AND_MEAN /DNOMINMAX "{1}" /Fo:"{2}" /Fe:"{3}" /link advapi32.lib userenv.lib' -f $environmentScript, $source, $object, $output
    & cmd.exe /d /c $command
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $output)) {
        throw "The $target runner build failed."
    }
    Remove-Item -LiteralPath $object -Force -ErrorAction SilentlyContinue
    Write-Host "Built $output"
}
