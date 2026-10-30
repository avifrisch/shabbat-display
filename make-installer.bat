@echo off
rem Builds dist\ShabbatDisplay.zip, the download for another PC in the house.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0make-installer.ps1"
pause
