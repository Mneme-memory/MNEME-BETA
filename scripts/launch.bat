@echo off
:: Mneme Launcher — starts the system tray + server (no console window)
cd /d "%~dp0"

set "PYTHONW_EXE=pythonw"
if exist ".python-path" (
    set /p PYTHON_EXE=<".python-path"
    if exist "%PYTHON_EXE%" (
        for %%P in ("%PYTHON_EXE%") do set "PYTHONW_EXE=%%~dpPpythonw.exe"
    )
)

start "" "%PYTHONW_EXE%" tray.py
