# Shabbat Display

Echo Show replacement for Avi's home: a full-screen, hands-off information display that runs on a spare Windows laptop and updates itself on timers through Shabbat. Nobody interacts with it, so there is no touch, mic, camera or motion input, and the display changes only on a schedule.

Owner preferences:
- Builds and runs locally on his Windows PC.
- No GitHub Actions or CI workflows.
- Python standard library only on the server, so there is nothing to pip install.

## Architecture

- `server.py`: stdlib HTTP server on `127.0.0.1:8765`.
  - One background thread per data source, each on its own refresh interval (the `SOURCES` table).
  - Keeps the last good result per source in memory and in `cache.json`. Failures keep the old data, are recorded in `meta`, and retry with backoff.
  - Serves `index.html` at `/`, all data at `/api/state`, and `/health` and `/fonts/*`.
  - `python server.py --check` fetches every source once and prints OK/FAIL.
  - Settings live in the `CONFIG` dict at the top of the file (location, candle-lighting minutes, havdalah method, team, dimming, rotation, bind address).
- `index.html`: single page with no build step, all CSS and JS inline.
  - Polls `/api/state` every 20 seconds.
  - Designed on a fixed 120×67.5 rem canvas (16:9), scaled by setting the root font-size from the viewport.
  - Fixed regions: a left column (clock, dates, weather, hourly, 5-day) and a bottom band (Shabbat/Yom Tov box and the zmanim "sky bar").
  - The stage rotates between scenes `yankees`, `mlb`, `news` and `israel`. During a live Yankees game the Yankees scene repeats every other turn and a live score chip appears on the other scenes.
  - Shabbat/Yom Tov mode (`body.holy`) runs from the last candle-lighting item until havdalah, based on Hebcal calendar items.
  - Overnight dimming uses a black overlay. A small pixel shift every 10 minutes guards against burn-in. The page reloads every 6 hours if `/health` answers. It requests a Screen Wake Lock.
  - Opened as a file with no server, it renders built-in demo data (`makeDemo()`) for layout work.
- `launcher.pyw`: Windows supervisor.
  - Starts the server and Chrome or Edge in `--kiosk` mode with its own profile in `browser-profile/`, and restarts either one if it exits.
  - Calls `SetThreadExecutionState` to keep the display and system awake.
- `start-display.bat` runs the launcher with no console window. `check-feeds.bat` runs `--check`.
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
| toi | Times of Israel RSS | Cloudflare returned 403 to our cloud test machine. It may work from home. The backup is a Google News search of `site:timesofisrael.com`. |

`parse_feed()` handles both RSS and Atom, with a regex fallback for malformed XML.

## Testing

- `python server.py --check`: tests every source.
- URL parameters:
  - `?at=2026-10-30T15:10`: fakes the clock. Note this affects only the client side, since the server still fetches for the real "now".
  - `?scene=mlb&hold=1`: pins one scene and stops the rotation.
- Screenshots: from the cloud session, Playwright was used at 1920×1080, 1366×768 and 1440×900. All three fit.
- Never tested on real Windows: `launcher.pyw`, the kiosk flags, `SetThreadExecutionState` and the wake lock. Verify these first.

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
3. **Possible hardware later:** a wall monitor with a Raspberry Pi or mini PC, or an e-ink panel.
4. **Possibly to verify:** two-day Yom Tov and Shabbat running into Yom Tov in `holyState()`, which has only been exercised with demo data for a regular Shabbat.
