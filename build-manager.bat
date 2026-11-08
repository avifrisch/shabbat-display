@echo off
rem Builds the Display Manager app into dist\manager and adds a Start-menu shortcut.
setlocal
cd /d "%~dp0"
rem the app needs a .NET 10 SDK; an older one first on PATH can't build it
set "DOTNET_DIR="
for %%d in ("%ProgramFiles%\dotnet" "%USERPROFILE%\.dotnet") do if not defined DOTNET_DIR if exist "%%~d\dotnet.exe" (
    "%%~d\dotnet.exe" --list-sdks 2>nul | findstr /b "10." >nul && set "DOTNET_DIR=%%~d"
)
if defined DOTNET_DIR (set "PATH=%DOTNET_DIR%;%PATH%") else (echo No .NET 10 SDK found. Install it with: winget install Microsoft.DotNet.SDK.10 & exit /b 1)
set DOTNET_CLI_TELEMETRY_OPTOUT=1
set DOTNET_NOLOGO=1

echo Running tests...
dotnet test manager\Manager.Tests || (echo Tests failed; nothing was built. & exit /b 1)

echo Building the app...
dotnet publish manager\App\ShabbatManager.csproj -c Release -r win-x64 --self-contained -o dist\manager || (echo The build failed. & exit /b 1)

powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Programs')+'\Shabbat Display Manager.lnk'); $s.TargetPath='%CD%\dist\manager\ShabbatManager.exe'; $s.WorkingDirectory='%CD%\dist\manager'; $s.Save()"
echo.
echo Done. Open "Shabbat Display Manager" from the Start menu.
