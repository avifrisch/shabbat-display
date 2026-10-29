@echo off
rem Starts the Shabbat Display as a screen saver: it appears after screensaver_minutes
rem without mouse or keyboard input (settings.json, default 10) and any input closes it.
cd /d "%~dp0"
where pyw >nul 2>nul
if %errorlevel%==0 (
  start "" pyw -3 "%~dp0launcher.pyw" --screensaver
) else (
  start "" pythonw "%~dp0launcher.pyw" --screensaver
)
