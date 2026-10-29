@echo off
rem Sets up the Shabbat Display on this PC. Safe to run again.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup-windows.ps1"
pause
