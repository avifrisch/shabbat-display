@echo off
rem Stops the Shabbat Display: the launcher, the data server and the full-screen browser.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$d = '%~dp0'.TrimEnd('\'); Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and ($_.CommandLine -like \"*$d\launcher.pyw*\" -or $_.CommandLine -like \"*$d\server.py*\" -or $_.CommandLine -like \"*$d\browser-profile*\") } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
echo Shabbat Display stopped.
timeout /t 3 >nul
