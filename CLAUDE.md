# Shabbat Display

Echo Show replacement for Avi's home: a full-screen, hands-off information display that runs on a spare Windows PC/laptop or a Raspberry Pi and updates itself on timers through Shabbat. Left alone it changes only on a schedule. On weekdays Avi can tap it (iPad) or click it (mouse) to open detail panels and swipe between scenes; it returns to rotation 2 minutes after the last input, and all interaction is off in `body.holy` and in screen-saver mode. No mic, camera or motion input. Design: `docs/superpowers/specs/2026-10-29-interactive-display-design.md`.

Owner preferences:
- Builds and runs locally on his Windows PC. Setup must stay easy on both Windows and Raspberry Pi OS: one setup script per platform, no manual config files to hand-edit before first run.
- No GitHub Actions or CI workflows.
- Python standard library only on the server, so there is nothing to pip install.

## Architecture

- `server.py`: stdlib HTTP server on `127.0.0.1:8765`.
  - One background thread per data source, each on its own refresh interval (the `SOURCES` table).
  - Keeps the last good result per source in memory and in `cache.json`. Failures keep the old data, are recorded in `meta`, and retry with backoff.
  - Serves `index.html` at `/`, all data at `/api/state`, and `/health` and `/fonts/*`.
  - On-demand endpoints for the panels, each behind `cached(key, ttl, fn)` (in memory): `/api/article?url=` (only http(s) URLs that are a `link` in one of the `ARTICLE_FEEDS`, else 404; text from `<p>`s via `extract_article()`; on failure the feed summary, retried after 60 s; Google News backup links aren't fetched; "cut off" only for NYT pages marked `isAccessibleForFree:false`), `/api/game?id=` (ASCII digits only; statsapi v1.1 live feed → `norm_boxscore()`; 25 s cache while live or not started, 10 min otherwise). `cached()` takes a ttl or a function of the value, and drops expired entries on each store, `/api/forecast` (Open-Meteo + air quality + all NWS periods + calendar candle/havdalah marks → `build_forecast()`), `/api/radar` (NWS KOKX loop GIF, 5 min).
  - `nyt_cookie` (secret, like `agenda_ics`): sent only to nytimes.com hosts by `article_headers()`. nytimes.com and timesofisrael.com answer 403 to non-browser article requests at times; that is bot protection and is not worked around.
  - Shul (Bnai Yeshurun) source, `shul` in `SOURCES` (design: `docs/superpowers/specs/2026-10-30-shul-tab-design.md`):
    - `fetch_shul()` runs hourly but fetches only when `shul_due()`. That is: nothing is stored or a stored file is missing; or on Friday, or any day with candle lighting (Erev Yom Tov), from 12:00 until candle lighting (`todays_candles()`, else 18:00) while the bulletin is dated before today; or 8:00–20:00 while the chart is more than 6 days old. Never on Saturday.
    - After a failure it retries no sooner than hourly (`RETRY_FLOOR` in `retry_wait()`).
    - One fetch runs at a time (`_shul_lock`). `/api/shul-update` answers 409 when a fetch is already running.
    - It reads `/minyan`, `/bulletin` and `/monthlycalendar`, and `shul_links()` picks the chart PNG, the newest bulletin PDF and the calendar JPGs (only `images.shulcloud.com`).
    - It downloads only URLs that changed into `shul/` (gitignored, served at `/shul/<name>`, names `[A-Za-z0-9._-]` only), and deletes files the new value no longer uses. Dates come from file names (`file_date()`).
    - `pdf_pages()` is a small stdlib PDF text reader (Flate, Tj/TJ, ToUnicode). `shabbat_times()` reads the bulletin's "Shabbat Times" box into rows `{label, time, he}` and notes `{text, after}`, using column positions measured on the real Word-made bulletin. It returns None rather than a partial table: no box, no Candle or Ends row, or Latin text in a row's Hebrew column (the box's right edge is capped at x 316). A line without a clock time becomes a note: its English left to right, then its Hebrew right to left.
    - Every request uses `SHUL_UA = "ShabbatDisplay/1.0 (personal home display)"`. The site 406s generic tools (curl, Python) but answers this. Never switch to a browser User-Agent to get past a refusal; a refusal just keeps the last files.
    - `/api/shul-update` (127.0.0.1 only) runs a forced fetch. `python server.py --update-shul` (`update-shul.bat`/`.sh`) calls it, or fetches in-process if the server isn't running.
  - `python server.py --check` fetches every source once and prints OK/FAIL.
  - Defaults live in the `CONFIG` dict at the top of the file (location, candle-lighting minutes, havdalah method, team, dimming, rotation, bind address). `settings.json` (gitignored, created by setup from `settings.example.json`) overrides them at startup in `load_settings()`; dict values such as `rotation_seconds` merge.
  - `python server.py --setting KEY` prints one resolved setting (used by `setup-pi.sh` for `tzid`).
- `index.html`: single page with no build step, all CSS and JS inline.
  - Polls `/api/state` every 20 seconds.
  - Designed on a 120×67.5 rem canvas (16:9), scaled by setting the root font-size from the viewport. On screens taller than 16:9 (the iPad, 16:10 laptops) the canvas takes the full height (`height:100%`): the scene area grows and `.side` spreads out (`max-aspect-ratio:17/10`). A 16:9 screen is unchanged.
  - On a touch screen (`pointer: coarse`, or `?fullpanel=1`) `body.fullpanel` makes panels cover the whole screen at `zoom:1.3`.
  - Fixed regions: a left column (clock, dates, weather, hourly, 5-day) and a bottom band (Shabbat/Yom Tov box and the zmanim "sky bar").
  - The stage rotates between scenes `agenda`, `shul`, `yankees`, `mlb`, `news` and `israel`. `shul` shows the weekly chart image on weekdays, with Calendar/Bulletin buttons (`PANELS.shulimg`, and `PANELS.bulletin`, which uses an iframe on the PC and a link to Safari's viewer under `body.fullpanel`). In `body.holy` it shows the bulletin's Shabbat Times only when `bulletinCurrent()` holds: the bulletin's date falls between the day of the candle lighting that began this Shabbat or Yom Tov and the day of havdalah. Otherwise, or when the times couldn't be read, it shows Hebcal candles/havdalah with the reason and "Shul times unavailable". `fitShabbat()` shrinks a long table (down to 60%) and then says there are more times in the bulletin. The title is "Yom Tov times" on Yom Tov. Images are inverted to suit the dark theme. Stale notes cover a chart older than 6 days and a bulletin that isn't this Shabbat's. During a live Yankees game the Yankees scene repeats every other turn and a live score chip appears on the other scenes.
  - `agenda` (today plus the next non-Shabbat day) and the "Next" line under the clock show only when `agenda_ics` is set and not in `body.holy` (`agendaOn()`). If Shabbat starts while the agenda is up, `renderAll()` advances off it immediately.
  - Shabbat/Yom Tov mode (`body.holy`) runs from the last candle-lighting item until havdalah, based on Hebcal calendar items.
  - Overnight dimming uses a black overlay. A small pixel shift every 10 minutes guards against burn-in. The page reloads every 6 hours if `/health` answers. It requests a Screen Wake Lock.
  - Opened as a file with no server, it renders built-in demo data (`makeDemo()`, including `demo_panels`) for layout work.
  - Interaction: elements carry `data-tap="article|game|forecast"` (plus `data-key`/`data-link` or `data-id`), scene tabs `data-scene`, forecast day rows `data-toggle`. Pointer Events on `document`: a tap is under 10 px / 500 ms; a swipe starts in `.scene-wrap`/`.stage-head` and is ≥ 80 px, mostly horizontal. `PANELS[kind] = {load, render, refreshMs?, shouldRefresh?}` render into `#panel` inside `.scene-wrap` (the scenes repaint underneath and never touch it). `lastInput` pauses rotation; `tick()` ends the interaction after `idleMs()` (2 min; `?debug=1` + `IDLE_MS_OVERRIDE`) or when `interactive()` turns false. The pointer is hidden (`cursor:none`) until the mouse moves. Hidden scene layers have `pointer-events:none`.
- `launcher.pyw`: supervisor for Windows and Linux.
  - `server_url` in settings.json (`display_url()`): the PC shows another machine's display and never starts `server.py`; the browser opens only once that server's `/health` answers (full time), and the screen saver doesn't open while it's down.
  - Starts the server and Chrome, Edge or Chromium in `--kiosk` mode with its own profile in `browser-profile/`, and restarts either one if it exits. Reads `port` from `settings.json`.
  - Single instance (a named mutex on Windows, `flock` on `launcher.lock` on Linux).
  - Before each browser start it marks the profile as cleanly exited, and on Linux removes stale `Singleton*` locks, so a power cut never leaves a restore-pages bubble or a refused profile.
  - Keeps the screen awake with `SetThreadExecutionState` on Windows and `xset` on X11. Under Wayland it relies on `setup-pi.sh` turning blanking off with `raspi-config`.
  - `--screensaver` (Windows only; `start-screensaver.bat`, or option 2 in `setup-windows.ps1`):
    - The server runs all the time. The browser opens after `screensaver_minutes` of no input (`GetLastInputInfo`), using its own `browser-profile-saver/`, mutex and `screensaver.log`.
    - It opens one kiosk window per chosen monitor, using `screens()` and `pick_screens()`. `screens()` lists monitors with `EnumDisplayMonitors` + `GetMonitorInfoW`; `internal_displays()` finds built-in panels from `QueryDisplayConfig`'s output technology (internal or embedded). Each window gets its own profile (`browser-profile-saver`, `-2`, ...). It gets `--window-position` whenever the PC has more than one monitor, because a second window in one profile opens on the first window's monitor.
    - `screensaver_screens: "external"`: plugged-in monitors only (all screens if there are none).
      - While it shows, the built-in panel's brightness goes to 0 via WMI (`WmiSetBrightness` through PowerShell) and is restored on close.
      - The old level is kept in `brightness-before-saver.txt` and restored at launcher start, in case the launcher was killed.
      - Untested on a real laptop: Avi's desktop monitors report output technology OTHER (they go through a dock). If detection fails it falls back to all screens, with no dimming.
    - `keep_pc_awake: true`: `SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)` on the saver thread, so the PC doesn't sleep but the screens still turn off.
    - Any input (the last-input tick changing) force-closes it within about a second, then locks Windows (`LockWorkStation`) unless `screensaver_lock` is false.
    - Skipped while `SHQueryUserNotificationState` reports locked, a full-screen app, D3D full screen or presentation mode. This is Windows' own test, so a maximized window doesn't count. An earlier window-rect check wrongly treated maximized windows as full screen when the taskbar auto-hides or on a second monitor.
    - The reason it was skipped is logged once to `screensaver.log`. At startup it warns if the power plan's screen-off time (`powercfg VIDEOIDLE`, plugged in) comes before `screensaver_minutes`. Setup offers to move it to that many minutes plus 20.
    - Doesn't keep the screen awake. The page gets `?saver=1`, so it skips its wake lock and the power plan still turns the screen off.
    - Chrome relaunches itself at startup, so the real main process is found by profile path (`browser_pids()`, a PowerShell CIM query) after the window is up.
- iPad as a second screen: set `"bind": "0.0.0.0"` and a Windows firewall rule for TCP 8765 from `LocalSubnet`. Then open `http://<ip>:8765` in Safari and add it to the Home Screen; Apple's web-app meta tags make that full screen. Needs iPadOS 14.5+, because the page uses `??` and flex `gap`. Avi's home PC is set up this way.
- Windows: `setup-windows.bat` runs `setup-windows.ps1` (finds real Python while skipping the WindowsApps Store stub, or installs it with winget, then powercfg settings and a Startup-folder shortcut to `pythonw launcher.pyw`). `start-display.bat`, `stop-display.bat`, `check-feeds.bat`.
- Another PC in the house: `make-installer.bat`/`.ps1` builds `dist/ShabbatDisplay.zip` with `git archive` (so settings.json and secrets never go in; `.gitattributes` export-ignores docs, tests, CLAUDE.md and the builder) for Avi to upload to avifrischlaw.com. `setup-windows.ps1` then:
  - unblocks the zip's files and offers to move out of Downloads to `C:\ShabbatDisplay`. If a copy is already there, it offers to update it instead: it stops that copy, copies over everything but settings.json, and reruns setup there.
  - in screen-saver mode, asks about `screensaver_screens` and `keep_pc_awake`. `Update-Setting` rewrites settings.json only when a value changes.
  - unless this PC is the server (`$env:COMPUTERNAME -eq $ServerName` or localhost:8765 answers), probes `$ServerAddresses` (Tailscale 100.98.145.119 if `tailscale status` says Running, then DESKTOP-H72VKDJ, then 192.168.4.109) at `/health`, explains failures (Tailscale missing/not connected, not on home Wi-Fi), and writes `server_url` into settings.json (rewritten only when it changes);
  - skips `server.py --check` for a remote-display PC. `server.py` ignores the launcher-only keys (`LAUNCHER_SETTINGS`) instead of logging them as unknown.
  - Not yet run end to end on a second PC.
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
| shul | bnaiyeshurun.org (ShulCloud): `/minyan`, `/bulletin`, `/monthlycalendar`; files on images.shulcloud.com | Fridays from noon until this Shabbat's bulletin is in, plus `--update-shul`. The chart is an image only. Bulletin file names carry the Shabbat date (`24Oct-LechLecha.pdf`). The chart's carries the Sunday it starts (`Oct25-weeklydavening.png`). The Shabbat Times box is on page 2. Hebrew gershayim (ק"ש) aren't in the PDF's ToUnicode map, so they read as קש. |
| toi | Times of Israel RSS | Cloudflare returned 403 to our cloud test machine. It may work from home. The backup is a Google News search of `site:timesofisrael.com`. |

`parse_feed()` handles both RSS and Atom, with a regex fallback for malformed XML.

## Testing

- `python server.py --check`: tests every source.
- `python -m unittest discover -s tests`: stdlib unit tests for the on-demand endpoints (`tests/test_server.py`) and the shul source (`tests/test_shul.py`). Fixtures are in `tests/fixtures/`. The article and shul pages there are made up, with real page structure, not saved copies. Synthetic bulletin PDFs come from `tests/pdfmaker.py`, laid out like the real Shabbat Times box.
- `python server.py --update-shul`: fetches the shul's files now and prints what it got, including the number of Shabbat Times rows. Compare a new bulletin's rows to its page 2 if the layout ever changes. On Avi's PC `python` in PowerShell is the Store stub; use `C:\msys64\mingw64\bin\python.exe`.
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

1. **Minyan times for Bnai Yeshurun: built (Oct 2026) as the `shul` scene.**
   - Avi wants the shul's exact times, not computed ones (the schedule moves with sunrise, seasons and holidays).
   - The 406 turned out to be a filter on generic tools' User-Agents, not on programs. A request that honestly names itself is answered. images.shulcloud.com's robots.txt (`Disallow: /`) is ShulCloud's default for all its shuls, aimed at search engines.
   - A few honest requests on Fridays plus manual runs was judged acceptable. Disguising the request was not, and still isn't.
   - A courtesy note to the shul office is still a good idea.
2. **Echo Show 15.** Can't host this. There is no sideloading, Silk times out to the home screen, and the device reacts to motion and voice. Not pursuing.
3. **Hardware:** Raspberry Pi 4 or 5 on a wall monitor is now supported via `setup-pi.sh`. An e-ink panel is still only an idea.
4. **Possibly to verify:** two-day Yom Tov and Shabbat running into Yom Tov in `holyState()`, which has only been exercised with demo data for a regular Shabbat.
