@echo off
rem Fetches every data source once and reports which ones work.
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 server.py --check
) else (
  python server.py --check
)
pause
