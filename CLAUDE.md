# Shabbat Display

Echo Show replacement for Avi's home: a full-screen, hands-off information display that runs on a spare Windows PC/laptop or a Raspberry Pi and updates itself on timers through Shabbat. Nobody interacts with it, so there is no touch, mic, camera or motion input, and the display changes only on a schedule.

Owner preferences:
- Builds and runs locally on his Windows PC. Setup must stay easy on both Windows and Raspberry Pi OS: one setup script per platform, no manual config files to hand-edit before first run.
- No GitHub Actions or CI workflows.
- Python standard library only on the server, so there is nothing to pip install.

## Architecture

- `server.py`: stdlib HTTP server on `127.0.0.1:8765`.
  - One background thread per data source, each on its own refresh interval (the `SOURCES` table).
  - Keeps the last good result per source in memory and in `cache.json`. Failures keep the old data, are recorded in `meta`, and retry with backoff.
  - Serves `index.html` at `/`, all data at `/api/state`, and `/health` and `/fonts/*`.
  - `python server.py --check` fetches every source once and prints OK/FAIL.
  - Defaults live in the `CONFIG` dict at the top of the file (location, candle-lighting minutes, havdalah method, team, dimming, rotation, bind address). `settings.json` (gitignored, created by setup from `settings.example.json`) overrides them at startup in `load_settings()`; dict values such as `rotation_seconds` merge.
  - `python server.py --setting KEY` prints one resolved setting (used by `setup-pi.sh` for `tzid`).
- `index.html`: single page with no build step, all CSS and JS inline.
  - Polls `/api/state` every 20 seconds.
  - Designed on a fixed 120×67.5 rem canvas (16:9), scaled by setting the root font-size from the viewport.
  - Fixed regions: a left column (clock, dates, weather, hourly, 5-day) and a bottom band (Shabbat/Yom Tov box and the zmanim "sky bar").
  - The stage rotates between scenes `agenda`, `yankees`, `mlb`, `news` and `israel`. During a live Yankees game the Yankees scene repeats every other turn and a live score chip appears on the other scenes.
  - `agenda` (today plus the next non-Shabbat day) and the "Next" line under the clock show only when `agenda_ics` is set and not in `body.holy` (`agendaOn()`). If Shabbat starts while the agenda is up, `renderAll()` advances off it immediately.
  - Shabbat/Yom Tov mode (`body.holy`) runs from the last candle-lighting item until havdalah, based on Hebcal calendar items.
  - Overnight dimming uses a black overlay. A small pixel shift every 10 minutes guards against burn-in. The page reloads every 6 hours if `/health` answers. It requests a Screen Wake Lock.
  - Opened as a file with no server, it renders built-in demo data (`makeDemo()`) for layout work.
- `launcher.pyw`: supervisor for Windows and Linux.
  - Starts the server and Chrome, Edge or Chromium in `--kiosk` mode with its own profile in `browser-profile/`, and restarts either one if it exits. Reads `port` from `settings.json`.
  - Single instance (a named mutex on Windows, `flock` on `launcher.lock` on Linux).
  - Before each browser start it marks the profile as cleanly exited, and on Linux removes stale `Singleton*` locks, so a power cut never leaves a restore-pages bubble or a refused profile.
  - Keeps the screen awake with `SetThreadExecutionState` on Windows and `xset` on X11. Under Wayland it relies on `setup-pi.sh` turning blanking off with `raspi-config`.
  - `--screensaver` (Windows only; `start-screensaver.bat`, or option 2 in `setup-windows.ps1`):
    - The server runs all the time. The browser opens after `screensaver_minutes` of no input (`GetLastInputInfo`), using its own `browser-profile-saver/`, mutex and `screensaver.log`.
    - Any input (the last-input tick changing) force-closes it within about a second.
    - Skipped while `SHQueryUserNotificationState` reports locked, a full-screen app, D3D full screen or presentation mode. This is Windows' own test, so a maximized window doesn't count. An earlier window-rect check wrongly treated maximized windows as full screen when the taskbar auto-hides or on a second monitor.
    - The reason it was skipped is logged once to `screensaver.log`. At startup it warns if the power plan's screen-off time (`powercfg VIDEOIDLE`, plugged in) comes before `screensaver_minutes`. Setup offers to move it to that many minutes plus 20.
    - Doesn't keep the screen awake. The page gets `?saver=1`, so it skips its wake lock and the power plan still turns the screen off.
    - Chrome relaunches itself at startup, so the real main process is found by profile path (`browser_pids()`, a PowerShell CIM query) after the window is up.
- iPad as a second screen: set `"bind": "0.0.0.0"` and a Windows firewall rule for TCP 8765 from `LocalSubnet`. Then open `http://<ip>:8765` in Safari and add it to the Home Screen; Apple's web-app meta tags make that full screen. Needs iPadOS 14.5+, because the page uses `??` and flex `gap`. Avi's home PC is set up this way.
- Windows: `setup-windows.bat` runs `setup-windows.ps1` (finds real Python while skipping the WindowsApps Store stub, or installs it with winget, then powercfg settings and a Startup-folder shortcut to `pythonw launcher.pyw`). `start-display.bat`, `stop-display.bat`, `check-feeds.bat`.
- Pi/Linux: `setup-pi.sh` (Chromium, time zone, `raspi-config` autologin and blanking, an XDG autostart entry in `~/.config/autostart`). `start-display.sh`, `stop-display.sh`, `check-feeds.sh`. `.gitattributes` keeps `*.sh` LF.
- `fonts/`: Archivo (UI), Newsreader (headlines) and Frank Ruhl Libre (Hebrew), all OFL and bundled so the page works offline.

## Data sources and known quirks

| Key | Source | Notes |
|---|---|---|
| weather | Open-Meteo | Fahrenheit and mph. WMO weather codes are mapped to icons in `wxIcon()`. |
| nws, alerts | api.weather.gov | The points→forecast URL is looked up once and cached. Alerts appear as a banner above the stage. |
| zmanim | Hebcal `/zmanim` | Switches to tomorrow after tzeit (`is_tomorrow`). Uses tzeit at 8.5°. |
| hebdate | Hebcal `/converter` | Uses `gs=on` after sunset. |
| calendar | Hebcal `/hebcal` by ZIP 07666 | Candles (18 min), havdalah (`M=on`), parashah, holidays, Rosh Chodesh. Window is 2 days back to 10 forward. |
| team, standings, scoreboard, transactions | statsapi.mlb.com | Polls every 30 seconds during a live or imminent game, otherwise every 3 minutes. Team 147, AL East division 201. "Roster status changed" noise is filtered out. League transactions skip minor-league contracts. |
| yankees_news, mlb_news | MLB.com RSS | NBC New York Yankees feed as the backup. |
| nyt | NYT HomePage RSS | |
| cnn | lite.cnn.com HTML | CNN's RSS feeds stopped updating in 2023. The backup is a Google News RSS search of `site:cnn.com`. |
| agenda | `agenda_ics` URLs in settings.json: the LPM calendar feed (Avi's practice management app; the feed is specified in `../lpm-calendar-feed.md`, outside the repo) or any ICS link | `CATEGORIES` becomes `kind`; `deadline` and `court_date` get labels, and deadlines are counted in the "Next" line. Own ICS parser: RRULE (daily/weekly/monthly/yearly, BYDAY ordinals, BYSETPOS, COUNT, UNTIL), EXDATE, RECURRENCE-ID overrides, CANCELLED. Time zones come from the file's VTIMEZONE because Windows Python has no tzdata; zoneinfo is the fallback (Pi), then local time. Window is today plus 4 days. URLs are secret: never logged, never sent to the page. |
| toi | Times of Israel RSS | Cloudflare returned 403 to our cloud test machine. It may work from home. The backup is a Google News search of `site:timesofisrael.com`. |

`parse_feed()` handles both RSS and Atom, with a regex fallback for malformed XML.

## Testing

- `python server.py --check`: tests every source.
- URL parameters:
  - `?at=2026-10-30T15:10`: fakes the clock. Note this affects only the client side, since the server still fetches for the real "now".
  - `?scene=mlb&hold=1`: pins one scene and stops the rotation.
- Screenshots: from the cloud session, Playwright was used at 1920×1080, 1366×768 and 1440×900. All three fit.
- Never tested on real hardware: `launcher.pyw`, the kiosk flags, `SetThreadExecutionState`, the wake lock, both setup scripts, and labwc honoring XDG autostart on Pi OS. Verify these first.

## Design

- Dark navy base (`--bg #0D1726`), warm off-white text, gold accent `#E5BA5E` for Hebrew and Shabbat items, sky blue for weather.
- In Shabbat mode the background tint shifts warm. Otherwise the tint follows time of day.
- The zmanim bar is a day-length gradient (night → dawn → day → sunset → night). Labels alternate above and below, a sun or moon marker shows the current time, and the next zman is highlighted in gold.
- Headlines use the serif face. Column lists drop any item that would be clipped (`fitColumns()`).

## Open items / ideas discussed

1. **Minyan times for Bnai Yeshurun (bnaiyeshurun.org, ShulCloud).**
   - The weekly schedule is published only as a PNG image on `/minyan`.
   - The site refuses automated requests (406, and robots disallow on images.shulcloud.com). Do not build a scraper that works around that.
   - Options Avi was offered:
     - (a) A `minyanim/` drop-in folder: the newest image becomes a fifth scene.
     - (b) A hand-edited `minyanim.json` of times, shown in the bottom band with the next minyan highlighted.
     - (c) Ask the shul whether ShulCloud can publish the schedule as text or an ICS feed.
   - Awaiting his choice.
2. **Echo Show 15.** Can't host this. There is no sideloading, Silk times out to the home screen, and the device reacts to motion and voice. Not pursuing.
3. **Hardware:** Raspberry Pi 4 or 5 on a wall monitor is now supported via `setup-pi.sh`. An e-ink panel is still only an idea.
4. **Possibly to verify:** two-day Yom Tov and Shabbat running into Yom Tov in `holyState()`, which has only been exercised with demo data for a regular Shabbat.
