@echo off
rem Builds the Windows screen saver into saver\ShabbatDisplay.scr (make-installer adds it to the zip).
setlocal
cd /d "%~dp0"
call "%~dp0dotnet-sdk.bat" || exit /b 1

echo Building the screen saver...
dotnet publish manager\Saver\ShabbatSaver.csproj -c Release -o dist\saver || (echo The screen saver didn't build. & exit /b 1)
if not exist saver mkdir saver
copy /y dist\saver\ShabbatDisplay.exe saver\ShabbatDisplay.scr >nul || (echo Couldn't copy it into saver\. Is the screen saver showing right now? & exit /b 1)
echo Built saver\ShabbatDisplay.scr
