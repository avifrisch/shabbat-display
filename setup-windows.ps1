# Shabbat Display setup for Windows 10/11.
# Double-click setup-windows.bat to run this. It is safe to run again at any time.
#
#   1. Finds Python 3, or installs it with winget.
#   2. Creates settings.json from settings.example.json.
#   3. Tests every data source.
#   4. Sets the screen and computer to never sleep while plugged in, and lid close to do nothing.
#   5. Makes the display start when you sign in.
#   6. Starts it.
#
# Or, on a PC you work at, sets the display up as a screen saver instead (no power changes).

$ErrorActionPreference = 'Continue'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Here

function Step($text) { Write-Host ''; Write-Host "== $text" -ForegroundColor Cyan }
function Ask($question) {
    $a = Read-Host "$question [Y/n]"
    return ($a -eq '' -or $a -match '^[Yy]')
}

function Find-Python {
    # Full path of a working python.exe, 3.9 or newer. Skips the Microsoft Store
    # placeholder in WindowsApps, which only opens the Store.
    $candidates = @()
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) {
        $p = & $py.Source -3 -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $p) { $candidates += "$p".Trim() }
    }
    foreach ($c in @(Get-Command python.exe -All -ErrorAction SilentlyContinue)) {
        if ($c.Source -notlike '*\WindowsApps\*') { $candidates += $c.Source }
    }
    $candidates += @(Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe",
                                   "$env:ProgramFiles\Python3*\python.exe" -ErrorAction SilentlyContinue |
                     Sort-Object FullName -Descending | ForEach-Object { $_.FullName })
    foreach ($c in $candidates) {
        & $c -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) { return $c }
    }
    return $null
}

Write-Host 'Shabbat Display setup' -ForegroundColor Yellow
Write-Host "Folder: $Here"
if ($Here -like "$env:TEMP*" -or $Here -like '*\Downloads\*') {
    Write-Host ''
    Write-Host 'Tip: this folder looks temporary. Move it somewhere permanent, such as C:\ShabbatDisplay,' -ForegroundColor Yellow
    Write-Host 'and run setup again from there, so the startup shortcut keeps working.' -ForegroundColor Yellow
    if (-not (Ask 'Continue from here anyway?')) { exit 1 }
}

# ------------------------------------------------------------------ Mode
Step 'How will this PC show the display?'
Write-Host ' 1. Full time: a spare PC or laptop that shows the display all day and through Shabbat.'
Write-Host ' 2. Screen saver: a PC you work at. The display appears after some minutes without'
Write-Host '    mouse or keyboard input, and any input closes it.'
$saver = (Read-Host 'Enter 1 or 2 [1]') -eq '2'
$launchArgs = if ($saver) { "`"$Here\launcher.pyw`" --screensaver" } else { "`"$Here\launcher.pyw`"" }

# ------------------------------------------------------------------ Python
Step 'Python'
$python = Find-Python
if (-not $python) {
    Write-Host 'Python 3 is not installed.'
    if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) {
        Write-Host 'Install it from https://www.python.org/downloads/ (tick "Add python.exe to PATH"), then run setup again.' -ForegroundColor Red
        Start-Process 'https://www.python.org/downloads/'
        exit 1
    }
    if (-not (Ask 'Install Python 3.13 now with winget?')) { exit 1 }
    winget install --exact --id Python.Python.3.13 --scope user --silent --accept-package-agreements --accept-source-agreements
    $python = Find-Python
    if (-not $python) {
        Write-Host 'Python still was not found. Close this window, open a new one and run setup again.' -ForegroundColor Red
        exit 1
    }
}
$pythonw = Join-Path (Split-Path $python) 'pythonw.exe'
if (-not (Test-Path $pythonw)) { $pythonw = $python }
Write-Host "Using $python"

# ------------------------------------------------------------------ Browser
Step 'Browser'
$browser = @("$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
             "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
             "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe",
             "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
             "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe") |
           Where-Object { Test-Path $_ } | Select-Object -First 1
if ($browser) { Write-Host "Using $browser" }
else { Write-Host 'No Chrome or Edge found. Install Google Chrome, then run setup again.' -ForegroundColor Red; exit 1 }

# ------------------------------------------------------------------ Settings
Step 'Settings'
if (Test-Path 'settings.json') {
    Write-Host 'settings.json already exists; leaving it as is.'
} else {
    Copy-Item 'settings.example.json' 'settings.json'
    Write-Host 'Created settings.json (Teaneck, NJ). Edit it in Notepad to change location, dimming and so on.'
}

# ------------------------------------------------------------------ Feeds
Step 'Testing the data sources (takes about a minute)'
# Windows downloads some root certificates only when a Windows program first asks
# for them, and Python can't trigger that (lite.cnn.com fails without it). One
# request per site from PowerShell fetches whatever roots are missing.
foreach ($site in 'https://lite.cnn.com/', 'https://api.open-meteo.com/', 'https://api.weather.gov/',
                  'https://www.hebcal.com/', 'https://statsapi.mlb.com/', 'https://www.mlb.com/',
                  'https://rss.nytimes.com/', 'https://www.timesofisrael.com/', 'https://news.google.com/') {
    try { Invoke-WebRequest $site -UseBasicParsing -Method Head -TimeoutSec 15 | Out-Null } catch {}
}
& $python server.py --check
Write-Host 'One or two failures are usually a slow connection. The display retries on its own.'

# ------------------------------------------------------------------ Power
if ($saver) {
    Step 'Windows screen saver'
    Write-Host 'The display takes the place of the Windows screen saver; your power settings stay as they are,'
    Write-Host 'so the screen still turns off when your power plan says.'
    Write-Host 'To change how long before it appears, set "screensaver_minutes" in settings.json (default 10).'
    if (Ask 'Turn off the Windows screen saver so the two do not overlap?') {
        Set-ItemProperty 'HKCU:\Control Panel\Desktop' -Name ScreenSaveActive -Value '0'
        Write-Host 'Done.'
    }
} else {
Step 'Power settings'
Write-Host 'While plugged in: screen never turns off, computer never sleeps, closing the lid does nothing.'
if (Ask 'Apply these?') {
    powercfg /change monitor-timeout-ac 0
    powercfg /change standby-timeout-ac 0
    powercfg /change hibernate-timeout-ac 0
    powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0 2>$null
    powercfg /setactive SCHEME_CURRENT
    Set-ItemProperty 'HKCU:\Control Panel\Desktop' -Name ScreenSaveActive -Value '0'
    Write-Host 'Done.'
}
}

# ------------------------------------------------------------------ Startup
Step 'Start automatically'
$startup = [Environment]::GetFolderPath('Startup')
$lnkPath = Join-Path $startup $(if ($saver) { 'Shabbat Display Screen Saver.lnk' } else { 'Shabbat Display.lnk' })
$otherLnk = Join-Path $startup $(if ($saver) { 'Shabbat Display.lnk' } else { 'Shabbat Display Screen Saver.lnk' })
if (Ask $(if ($saver) { 'Turn on the screen saver every time you sign in?' } else { 'Start the display every time you sign in?' })) {
    Remove-Item $otherLnk -ErrorAction SilentlyContinue  # one mode or the other
    $shell = New-Object -ComObject WScript.Shell
    $lnk = $shell.CreateShortcut($lnkPath)
    $lnk.TargetPath = $pythonw
    $lnk.Arguments = $launchArgs
    $lnk.WorkingDirectory = $Here
    $lnk.Description = 'Shabbat Display'
    $lnk.Save()
    Write-Host "Added $lnkPath"
}

# ------------------------------------------------------------------ Manual steps
if (-not $saver) {
Step 'Do these by hand (see README.md for details)'
Write-Host ' - Windows Update: set active hours to cover Shabbat, or pause updates before Shabbat.'
Write-Host ' - Notifications: turn on Do Not Disturb.'
Write-Host ' - Power failures: run netplwiz and untick "Users must enter a user name and password";'
Write-Host '   turn on "power on after AC loss" in the BIOS if it has one.'
}

Step 'Start'
$startQ = if ($saver) { 'Turn on the screen saver now?' } else { 'Start the display now? (Alt+F4 closes the browser; it reopens within a minute)' }
if (Ask $startQ) {
    Start-Process -FilePath $pythonw -ArgumentList $launchArgs -WorkingDirectory $Here
}
Write-Host ''
Write-Host 'Setup finished.' -ForegroundColor Green
