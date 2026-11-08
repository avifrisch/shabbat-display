# Shabbat Display setup for Windows 10/11.
# Double-click setup-windows.bat to run this. It is safe to run again at any time.
#
#   1. Finds Python 3, or installs it with winget.
#   2. Looks for the house's always-on display PC (Tailscale, then the home network).
#      If it's there, this PC just shows its display; otherwise it runs its own copy.
#   3. Creates settings.json from settings.example.json, and tests every data source
#      when this PC fetches its own data.
#   4. Sets the screen and computer to never sleep while plugged in, and lid close to do nothing.
#   5. Makes the display start when you sign in.
#   6. Starts it.
#
# Or, on a PC you work at, sets the display up as a screen saver instead (no power changes).

$ErrorActionPreference = 'Continue'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Here

function Step($text) { Write-Host ''; Write-Host "== $text" -ForegroundColor Cyan }
function Ask($question, $yes = $true) {
    # Enter alone gives the default: yes, or no when $yes is false
    $a = Read-Host "$question $(if ($yes) { '[Y/n]' } else { '[y/N]' })"
    if ($a -eq '') { return [bool]$yes }
    return ($a -match '^[Yy]')
}
function Read-Settings { Get-Content (Join-Path $Here 'settings.json') -Raw -Encoding UTF8 | ConvertFrom-Json }
function Update-Setting($name, $value) {
    # Sets (or, with $null, removes) one setting. settings.json is rewritten only when
    # something changes, so a re-run leaves a hand-edited file alone.
    $cfg = Read-Settings
    $p = $cfg.PSObject.Properties[$name]
    if ($null -eq $value) {
        if (-not $p) { return }
        $cfg.PSObject.Properties.Remove($name)
    } else {
        if ($p -and "$($p.Value)" -eq "$value") { return }
        $cfg | Add-Member -NotePropertyName $name -NotePropertyValue $value -Force
    }
    [IO.File]::WriteAllText((Join-Path $Here 'settings.json'), ($cfg | ConvertTo-Json -Depth 5), (New-Object Text.UTF8Encoding $false))
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
# Files from a downloaded zip carry Windows' "came from the internet" mark, which makes
# PowerShell and Python shortcuts ask before running. These are ours, so clear it.
Get-ChildItem $Here -Recurse -File -ErrorAction SilentlyContinue | Unblock-File -ErrorAction SilentlyContinue
if ($Here -like "$env:TEMP*" -or $Here -like '*\Downloads\*') {
    $target = 'C:\ShabbatDisplay'
    Write-Host ''
    Write-Host 'This folder looks temporary (Downloads or a temp folder).' -ForegroundColor Yellow
    if (Test-Path (Join-Path $target 'launcher.pyw')) {
        if (Ask "The Shabbat Display is already in $target. Update it with this version? Its settings are kept.") {
            # stop that copy (launcher, server, browsers) so its files can be replaced
            Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and ($_.CommandLine -like "*$target\launcher.pyw*" -or
                $_.CommandLine -like "*$target\server.py*" -or $_.CommandLine -like "*$target\browser-profile*") } |
                ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
            Start-Sleep 2
            Copy-Item (Join-Path $Here '*') $target -Recurse -Force -Exclude 'settings.json'
            Write-Host "Updated $target. Setup continues there."
            & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $target 'setup-windows.ps1')
            exit $LASTEXITCODE
        }
        if (-not (Ask 'Continue setup from this folder instead?' $false)) { exit 1 }
    } elseif ((Test-Path $target) -and (Get-ChildItem $target -Force -ErrorAction SilentlyContinue | Select-Object -First 1)) {
        Write-Host "$target already has other files in it, so setup won't copy there."
        if (-not (Ask 'Continue from here anyway?')) { exit 1 }
    } elseif (Ask "Move the Shabbat Display to $target and continue setup there?") {
        New-Item -ItemType Directory -Force $target | Out-Null
        Copy-Item (Join-Path $Here '*') $target -Recurse -Force
        Write-Host "Copied to $target. Setup continues there."
        & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $target 'setup-windows.ps1')
        exit $LASTEXITCODE
    } elseif (-not (Ask 'Continue from here anyway? (the startup shortcut breaks if this folder is deleted)')) { exit 1 }
}

# The always-on display PC in this house. A second PC (or a screen saver) shows that
# PC's display instead of fetching everything itself. Tried in this order: its
# Tailscale address (works anywhere), its name on the home network, its home address.
$ServerName = 'DESKTOP-H72VKDJ'
$ServerAddresses = @(@{ Host = '100.98.145.119'; Via = 'Tailscale' },
                     @{ Host = $ServerName; Via = 'the home network' },
                     @{ Host = '192.168.4.109'; Via = 'the home network' })
$Port = 8765

function Test-Display($hostName) {
    try {
        $r = Invoke-WebRequest "http://${hostName}:$Port/health" -UseBasicParsing -TimeoutSec 4
        return ($r.StatusCode -eq 200 -and "$($r.Content)".Trim() -eq 'ok')
    } catch { return $false }
}

function Get-Tailscale {
    # 'missing', 'stopped' (installed, not connected) or 'running'
    $exe = (Get-Command tailscale.exe -ErrorAction SilentlyContinue).Source
    if (-not $exe -and (Test-Path "$env:ProgramFiles\Tailscale\tailscale.exe")) { $exe = "$env:ProgramFiles\Tailscale\tailscale.exe" }
    if (-not $exe) { return 'missing' }
    try {
        $state = (& $exe status --json 2>$null | Out-String | ConvertFrom-Json).BackendState
        if ($state -eq 'Running') { return 'running' }
    } catch {}
    return 'stopped'
}

# ------------------------------------------------------------------ Mode
Step 'How will this PC show the display?'
Write-Host ' 1. Full time: a spare PC or laptop that shows the display all day and through Shabbat.'
Write-Host ' 2. Screen saver: a PC you work at. The display appears after some minutes without'
Write-Host '    mouse or keyboard input, and any input closes it and locks the PC.'
$saver = (Read-Host 'Enter 1 or 2 [1]') -eq '2'
$launchArgs = if ($saver) { "`"$Here\launcher.pyw`" --screensaver" } else { "`"$Here\launcher.pyw`"" }

# ------------------------------------------------------------------ Display server
Step 'Where the display comes from'
$serverUrl = ''
$isServer = ($env:COMPUTERNAME -eq $ServerName)
try { $isServer = $isServer -or ((Invoke-WebRequest "http://localhost:$Port/health" -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200) } catch {}
if ($isServer) {
    Write-Host 'This PC runs the display server, so it fetches its own data.'
} else {
    $found = $null
    $ts = Get-Tailscale
    foreach ($a in $ServerAddresses) {
        if ($a.Via -eq 'Tailscale' -and $ts -ne 'running') { continue }
        Write-Host "Looking for the always-on display PC at $($a.Host) ($($a.Via))..."
        if (Test-Display $a.Host) { $found = $a; break }
    }
    if ($found) {
        Write-Host "Found it at $($found.Host), through $($found.Via)." -ForegroundColor Green
        Write-Host " 1. Show that PC's display here (recommended). Nothing else to set up."
        Write-Host ' 2. Run a separate copy on this PC that fetches its own data.'
        if ((Read-Host 'Enter 1 or 2 [1]') -ne '2') { $serverUrl = "http://$($found.Host):$Port" }
    } else {
        Write-Host "The always-on display PC ($ServerName) didn't answer." -ForegroundColor Yellow
        switch ($ts) {
            'missing' { Write-Host ' - Tailscale is not installed on this PC, so it can only be reached on the home Wi-Fi.' }
            'stopped' { Write-Host ' - Tailscale is installed but not connected. Open Tailscale and sign in, then run setup again.' }
            'running' { Write-Host " - Tailscale is connected, but $($ServerAddresses[0].Host) didn't answer. Is the display PC on?" }
        }
        Write-Host ' - On the home network it did not answer either. Check that this PC is on the home Wi-Fi'
        Write-Host '   (not a guest network) and that the display PC is on and showing the display.'
        Write-Host ' 1. Type its address yourself'
        Write-Host ' 2. Run a separate copy on this PC that fetches its own data'
        Write-Host ' 3. Stop here and try again later'
        switch (Read-Host 'Enter 1, 2 or 3 [3]') {
            '1' {
                $h = (Read-Host 'Address (for example 192.168.4.109)').Trim() -replace '^https?://', '' -replace '[:/].*$', ''
                if ($h -and (Test-Display $h)) { $serverUrl = "http://${h}:$Port"; Write-Host "Found it at $h." -ForegroundColor Green }
                elseif ($h -and (Ask "$h didn't answer. Use it anyway?")) { $serverUrl = "http://${h}:$Port" }
                elseif (-not $h) { exit 1 }
            }
            '2' { }
            default { exit 1 }
        }
    }
}

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
    Write-Host 'settings.json already exists; keeping your settings.'
} else {
    Copy-Item 'settings.example.json' 'settings.json'
    Write-Host 'Created settings.json (Teaneck, NJ). Edit it in Notepad to change location, dimming and so on.'
}
# Record where the display comes from (or that this PC has its own server).
try {
    Update-Setting 'server_url' $(if ($serverUrl) { $serverUrl } else { $null })
    if ($serverUrl) { Write-Host "This PC will show the display from $serverUrl." }
} catch {
    Write-Host "Couldn't update settings.json ($_). Add `"server_url`": `"$serverUrl`" to it in Notepad." -ForegroundColor Red
}

# ------------------------------------------------------------------ Feeds
if ($serverUrl) {
    Step 'Data'
    Write-Host 'The always-on PC fetches everything; nothing to test here.'
} else {
Step 'Testing the data sources (takes about a minute)'
# Windows downloads some root certificates only when a Windows program first asks
# for them, and Python can't trigger that (lite.cnn.com fails without it). One
# request per site from PowerShell fetches whatever roots are missing.
foreach ($site in 'https://lite.cnn.com/', 'https://api.open-meteo.com/', 'https://api.weather.gov/',
                  'https://www.hebcal.com/', 'https://statsapi.mlb.com/', 'https://www.mlb.com/',
                  'https://rss.nytimes.com/', 'https://www.timesofisrael.com/', 'https://news.google.com/',
                  'https://site.api.espn.com/', 'https://quote.cnbc.com/', 'https://www.cnbc.com/',
                  'https://query1.finance.yahoo.com/') {
    try { Invoke-WebRequest $site -UseBasicParsing -Method Head -TimeoutSec 15 | Out-Null } catch {}
}
& $python server.py --check
Write-Host 'One or two failures are usually a slow connection. The display retries on its own.'
}

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
    $cur = Read-Settings
    Write-Host ''
    Write-Host 'On a laptop with a monitor plugged in, the display can use just the monitor and turn the'
    Write-Host "laptop's own screen all the way down while it shows (Windows can't switch off one screen)."
    $ext = Ask 'Show it only on a plugged-in monitor?' ($cur.screensaver_screens -eq 'external')
    Update-Setting 'screensaver_screens' $(if ($ext) { 'external' } else { $null })
    $awake = Ask 'Keep this PC from going to sleep, and its screens on while the display shows?' ([bool]$cur.keep_pc_awake)
    Update-Setting 'keep_pc_awake' $(if ($awake) { $true } else { $null })
    # If the screen turns off before the display would appear, it opens on a dark screen.
    $minutes = 10
    try { $m = (Get-Content 'settings.json' -Raw | ConvertFrom-Json).screensaver_minutes; if ($m) { $minutes = [double]$m } } catch {}
    $idx = [regex]::Matches((powercfg /q SCHEME_CURRENT SUB_VIDEO VIDEOIDLE | Out-String), '0x[0-9a-fA-F]+')
    $off = if ($idx.Count -ge 2) { [Convert]::ToInt32($idx[$idx.Count - 2].Value, 16) / 60 } else { 0 }
    if ($off -gt 0 -and $off -le $minutes) {
        $new = [int]$minutes + 20
        Write-Host "Your screen turns off after $off minutes, before the display would appear (after $minutes)." -ForegroundColor Yellow
        if (Ask "Turn the screen off after $new minutes instead, so the display shows for 20 minutes?") {
            powercfg /change monitor-timeout-ac $new
            Write-Host 'Done.'
        }
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
if ($isServer) {
    # the Display Manager app's access code; the server makes it the first time it runs
    & $python server.py --setting port | Out-Null
    $keyFile = Join-Path $Here 'manage-key.txt'
    if (Test-Path $keyFile) {
        Write-Host ''
        Write-Host "Display Manager access code: $((Get-Content $keyFile -Raw).Trim())" -ForegroundColor Cyan
        Write-Host '(Type it into the Display Manager app once. Keep it private.)'
    }
}
Write-Host ''
Write-Host 'Setup finished.' -ForegroundColor Green
