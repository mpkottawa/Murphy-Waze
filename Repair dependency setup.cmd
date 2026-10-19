@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0packaging\setup.ps1" -AppRoot "%~dp0."
pause
