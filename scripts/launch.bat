@echo off
:: Mneme Launcher — starts the system tray + server (no console window)
cd /d "%~dp0"
start "" pythonw tray.py
