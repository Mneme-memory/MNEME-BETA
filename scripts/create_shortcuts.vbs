Set ws = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' Get project root (parent of scripts folder)
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
projectRoot = fso.GetParentFolderName(scriptDir) & "\"

' Desktop shortcut
Set sc = ws.CreateShortcut(ws.SpecialFolders("Desktop") & "\Mneme.lnk")
sc.TargetPath = projectRoot & "scripts\launch.bat"
sc.WorkingDirectory = projectRoot
sc.IconLocation = projectRoot & "Logos\mneme-tray.ico"
sc.WindowStyle = 7
sc.Description = "Start Mneme Memory System"
sc.Save

' In-folder launch shortcut
Set sc2 = ws.CreateShortcut(projectRoot & "Launch Mneme.lnk")
sc2.TargetPath = projectRoot & "scripts\launch.bat"
sc2.WorkingDirectory = projectRoot
sc2.IconLocation = projectRoot & "Logos\mneme-tray.ico"
sc2.WindowStyle = 7
sc2.Description = "Start Mneme Memory System"
sc2.Save

' In-folder install shortcut
Set sc3 = ws.CreateShortcut(projectRoot & "Install Mneme.lnk")
sc3.TargetPath = projectRoot & "install-windows.bat"
sc3.WorkingDirectory = projectRoot
sc3.IconLocation = projectRoot & "Logos\mneme-tray.ico"
sc3.Description = "Install Mneme Memory System"
sc3.Save

WScript.Echo "Shortcuts created."
