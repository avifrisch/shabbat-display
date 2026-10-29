@echo off
rem Starts the Shabbat Display (data server + full-screen browser) with no console window.
cd /d "%~dp0"
where pyw >nul 2>nul
if %errorlevel%==0 (
  start "" pyw -3 "%~dp0launcher.pyw"
) else (
  start "" pythonw "%~dp0launcher.pyw"
)
