@echo off
rem Fetches every data source once and reports which ones work.
cd /d "%~dp0"
python server.py --check
pause
