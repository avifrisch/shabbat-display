@echo off
rem Fetches the shul's davening chart, bulletin and calendar now (the display also
rem does this by itself on Friday afternoons).
cd /d "%~dp0"
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY for /f "delims=" %%p in ('where python 2^>nul') do (
  echo %%p | find /i "WindowsApps" >nul || if not defined PY set "PY="%%p""
)
if not defined PY if exist "C:\msys64\mingw64\bin\python.exe" set "PY="C:\msys64\mingw64\bin\python.exe""
if not defined PY (
  echo Python wasn't found. Run setup-windows.bat first.
  pause
  exit /b 1
)
%PY% server.py --update-shul
pause
