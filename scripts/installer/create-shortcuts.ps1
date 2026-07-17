# create-shortcuts.ps1
# Creates Mneme desktop and folder shortcuts.

param([Parameter(Mandatory)][string]$MnemeDir)

$ws = New-Object -ComObject WScript.Shell
$desktop = $ws.SpecialFolders('Desktop')
$launchBat = Join-Path $MnemeDir "scripts\launch.bat"
$iconPath  = Join-Path $MnemeDir "Logos\mneme-tray.ico"

# Desktop shortcut
$sc = $ws.CreateShortcut("$desktop\Mneme.lnk")
$sc.TargetPath      = $launchBat
$sc.WorkingDirectory = $MnemeDir
$sc.IconLocation    = $iconPath
$sc.WindowStyle     = 7
$sc.Description     = 'Start Mneme Memory System'
$sc.Save()

# Folder shortcut (inside the Mneme folder itself)
$sc2 = $ws.CreateShortcut("$MnemeDir\Launch Mneme.lnk")
$sc2.TargetPath      = $launchBat
$sc2.WorkingDirectory = $MnemeDir
$sc2.IconLocation    = $iconPath
$sc2.WindowStyle     = 7
$sc2.Description     = 'Start Mneme Memory System'
$sc2.Save()

Write-Host "Shortcuts created"
