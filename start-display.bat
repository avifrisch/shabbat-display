@echo off
rem Starts the Shabbat Display (data server + full-screen browser) with no console window.
cd /d "%~dp0"
start "" pythonw "%~dp0launcher.pyw"
