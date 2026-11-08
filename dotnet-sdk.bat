@echo off
rem Puts a .NET 10 SDK first on PATH (an older one first on PATH can't build the apps). Used with call.
set "DOTNET_DIR="
for %%d in ("%ProgramFiles%\dotnet" "%USERPROFILE%\.dotnet") do if not defined DOTNET_DIR if exist "%%~d\dotnet.exe" (
    "%%~d\dotnet.exe" --list-sdks 2>nul | findstr /b "10." >nul && set "DOTNET_DIR=%%~d"
)
if defined DOTNET_DIR (set "PATH=%DOTNET_DIR%;%PATH%") else (echo No .NET 10 SDK found. Install it with: winget install Microsoft.DotNet.SDK.10 & exit /b 1)
set DOTNET_CLI_TELEMETRY_OPTOUT=1
set DOTNET_NOLOGO=1
