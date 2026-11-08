@echo off
rem Builds the Display Manager app into dist\manager and adds a Start-menu shortcut.
setlocal
cd /d "%~dp0"
where dotnet >nul 2>nul || set "PATH=%ProgramFiles%\dotnet;%USERPROFILE%\.dotnet;%PATH%"
set DOTNET_CLI_TELEMETRY_OPTOUT=1
set DOTNET_NOLOGO=1

echo Running tests...
dotnet test manager\Manager.Tests || (echo Tests failed; nothing was built. & exit /b 1)

echo Building the app...
dotnet publish manager\App\ShabbatManager.csproj -c Release -r win-x64 --self-contained -o dist\manager || (echo The build failed. & exit /b 1)

powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Programs')+'\Shabbat Display Manager.lnk'); $s.TargetPath='%CD%\dist\manager\ShabbatManager.exe'; $s.WorkingDirectory='%CD%\dist\manager'; $s.Save()"
echo.
echo Done. Open "Shabbat Display Manager" from the Start menu.
