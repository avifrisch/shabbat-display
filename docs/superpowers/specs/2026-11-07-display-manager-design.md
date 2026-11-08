# Display Manager: a Windows app to run the Shabbat Display, more sports, per-screen rotations, business news

Date: 2026-11-07. Status: draft for Avi's approval.

## Why

Today every change to the display means editing `settings.json` on some PC, or asking Claude to do it over SSH. Three things in the last weeks showed the cost:

- Ariela's Acer: the screen-saver settings live in a file on her laptop. Getting them right took several remote sessions, and when remote login stopped answering nothing could be changed.
- The Chayei Sarah bulletin downloaded on Friday but its times couldn't be read. Nobody knew until Shabbat, when the Shul tab showed only candle lighting and havdalah.
- Avi's daughter asked for basketball. Adding a sport today is a code change.

Avi wants one small Windows app on his PC that manages the whole house's display: which sports and teams, which scenes each screen rotates through, how each PC shows it (always on or screen saver), confirmation that the shul's files came in, the server's health, and his NYT sign-in. He also wants a new business page: the stock market in general plus stocks he picks in the app.

## Goals

1. **The app (WinUI 3).** A WinUI 3 desktop app, "Shabbat Display Manager", for Avi's PC (the Surface Studio). It talks to the display server on the always-on PC (DESKTOP-H72VKDJ) over Tailscale or the home network. Pages, in a left menu:
   - **Status**: one screen that says whether everything is fine: server up, each feed's last update and any failure, this week's shul files, each screen's last check-in. Problems in amber/red with a plain sentence.
   - **Sports**: every major league with an on/off switch and favorite teams (search by name, add, remove, mark one favorite). Leagues: MLB, NBA, WNBA, NFL, NHL, MLS, men's and women's college basketball, college football. MLB starts on with the Yankees, as today.
   - **Business**: a watchlist of stocks (search by ticker or company name, add, remove, reorder) and switches for the business news sources.
   - **Screens**: every screen in the house, each with a name, its rotation (which scenes, in what order, how many seconds each) and, for a PC, its mode: always on or screen saver, and for screen saver the idle minutes, lock on close, which monitor, keep awake.
   - **Shul**: this week's weekly chart, bulletin and monthly calendar: file name, when it arrived, whether it is this week's/month's, and for the bulletin how many Shabbat times were read. "Update now" and "Open" buttons. A bulletin that downloaded but couldn't be read is amber, with that sentence.
   - **NYT**: "Signed in" or "Signed out", a Sign in button and a Sign out button.
   - **Server**: per-feed health, the last lines of the server's log, a Restart button.
2. **Sports scenes for every league.** Each league switched on gets its own scene, built like the Yankees scene: the favorite team's live/last/next game, its standings, its news, plus league scores ("Around the NBA"). Other chosen teams of that league appear with the favorite in the scores. Tapping a game in a non-MLB league opens a simple score panel: the score by quarter/period/half, the game's state and clock, venue. No box scores or player stats for these leagues (Avi's choice). MLB keeps its full box score. A league with no games within the last 3 days or the next 7 drops out of the rotation by itself (off-season) and comes back when games resume. During a favorite team's live game, that team's scene repeats every other turn and the live score chip appears on the other scenes, as the Yankees do today; with two live favorites, both chips.
3. **A business scene.** The market at a glance (S&P 500, Dow Jones, Nasdaq Composite, each with level, change and percent change today), the watchlist from the app (price, change, percent change, colored up/down), and business headlines. Prices may be delayed (free source); the scene says "Delayed" and the time of the last price. Tap a headline → the reading panel, as with other news.
4. **A rotation per screen.** Each screen has a name. The house default is today's rotation without the agenda (`shul, yankees, mlb, news, israel` with today's seconds); Avi chooses which screens get the agenda (see Calls). Shabbat rules are the same on every screen (agenda hidden, Shul tab shows Shabbat times, no interaction); the new business scene and any sports scene stay in rotation over Shabbat like the existing ones, unchanged by this project.
5. **PCs take their mode from the app.** A PC's launcher asks the server for its own settings (by screen name) and follows them: always on or screen saver, and the screen-saver options. A change in the app reaches that PC within a minute, with nobody at it. If the server can't be reached, the PC keeps its last settings (cached locally), then `settings.json`.
6. **NYT sign-in from the app.** The app shows nytimes.com's own sign-in page in an embedded browser (WebView2). After sign-in it reads the `NYT-S` cookie and sends it to the server, which stores it as `nyt_cookie` and uses it from then on without a restart. Sign out deletes it. The app never shows the cookie.
7. **Shul confirmation.** The Shul page and Status page show exactly what the display has, so a failed download or unreadable bulletin is visible on Friday afternoon, not on Shabbat.

## Non-goals

- No phone app, no web admin page. Only the Windows app.
- No accounts or users. Anyone with the app and the access code can change everything.
- No real-time stock prices, no portfolio values, no charts beyond the day's change. Delayed quotes are fine.
- No fantasy sports, betting lines, player stats pages.
- No change to how Shabbat mode is decided, or to the shul source's fetch rules (honest User-Agent, Fridays, etc.).
- The iPad is a screen with a name and a rotation; it has no launcher, so it has no mode.
- The app is not part of the installer zip for other PCs. It runs on Avi's PC.

## Anti-goals (would make it a failure even if it works)

- The display changing behavior on Shabbat because of the app, or the app being needed on Shabbat. Everything the screens need lives on the server and keeps working if the app is never opened again.
- A secret leaking: `nyt_cookie`, `agenda_ics` URLs and the access code are never shown in the app, never sent to the page, never logged. The management API never returns them, only whether they are set.
- A screen going blank or a PC going dark because the app or the server is down. Every screen and launcher keeps its last good settings.
- Anything to pip install on the server, or hand-edited files to make the app work.
- Pretending to be a browser to get sports, stock or news data, or working around a refusal.

## How it works (decided)

### Server (`server.py`, still standard-library Python)

- **Household config** lives in a new gitignored file next to `settings.json`, written only by the server: `household.json`. It holds leagues and teams, the watchlist, business news switches, screens (name → rotation, mode, screen-saver options), and secrets set from the app (`nyt_cookie`). It is read live (no restart). A value in `household.json` overrides the same thing in `settings.json`; `settings.json` stays as the machine's own setup (location, bind, port, `agenda_ics`) and is never rewritten by the server.
- **Management API** under `/api/manage/...`, JSON in and out. Every request must carry the access code (header `X-Manage-Key`). Without it: 401. It answers on the same port as the display. It is meant for Tailscale and the home network only, like the display itself.
- **Access code:** generated by the server on first start into gitignored `manage-key.txt` (random, long). `setup-windows.ps1` on the server PC prints it at the end; the app asks for it once and keeps it in Windows Credential Manager.
- **New sources in `SOURCES`:**
  - Sports leagues other than MLB: one source per league that is switched on, scoreboard (today ± a few days), standings and team news for the chosen teams, and team schedules for last/next game. Polls every 30 seconds while a chosen team is live or starting within 15 minutes, else every few minutes, like MLB today.
  - MLB keeps statsapi.mlb.com and the current code. The Yankees become "MLB, favorite team Yankees" in the config, with the same behavior. Other MLB teams can be added.
  - Stocks: quotes for the three indices and the watchlist every few minutes while US markets are open (9:30–16:00 Eastern, weekdays), once after the close, not at all on weekends.
  - Business news: RSS feeds (e.g. NYT Business, CNBC), through the existing `parse_feed()`; articles open in the reading panel through the existing `/api/article` rules (only links from a configured feed).
- **Screens:** the page passes `?screen=<name>` on its `/api/state` requests. The server records each name's last check-in time (and whether it is a launcher PC) for the app's Screens and Status pages, and returns that screen's rotation in the state. No name → the house default.
- **Launcher settings:** `/api/screen-settings?screen=<name>` (no access code; returns only that screen's mode and screen-saver options, nothing secret).
- **NYT cookie:** set through the management API, stored in `household.json`, used by `article_headers()` exactly as `nyt_cookie` is today.
- **Restart:** the management API can make the server exit cleanly; the launcher on that PC restarts it (as it does after a crash).
- **Shul:** the management API exposes what `shul_summary()` knows plus `meta`, and "Update now" calls the same forced fetch as `/api/shul-update` (which stays 127.0.0.1-only for `update-shul.bat`).

### Page (`index.html`)

- `SCENES` becomes data-driven for sports: a generic sports scene renders any league from one normalized shape (the shape the Yankees/MLB scenes already use: games with teams, scores, state, inning/period/quarter, standings rows, news items). MLB's diamond/outs detail stays for MLB; other sports show period and clock.
- A `business` scene: indices row, watchlist table, headlines column, "Delayed · 3:42 pm" note.
- The rotation comes from the server's state for this screen (falling back to today's built-in order).
- The screen name comes from the URL (`?screen=`), set by the launcher, or by the iPad's saved bookmark.

### Launcher (`launcher.pyw`)

- Gets a screen name: `screen_name` in `settings.json`, else the PC's name. Adds `?screen=` to the display URL.
- Every minute asks `/api/screen-settings` and caches the answer in gitignored `screen-settings.json`. Follows `mode`: always on, or screen saver with the given options. It switches between modes without a restart. The `--screensaver` flag on the Startup shortcut becomes only the default when no mode has ever been received.

### App (`manager/`)

- C#, .NET 8, WinUI 3 (Windows App SDK), unpackaged and self-contained (`WindowsPackageType=None`), built with the `dotnet` CLI already on Avi's PC (no Visual Studio needed). `build-manager.bat` builds it into `dist/manager/` and makes a Start-menu shortcut.
- Finds the server like `setup-windows.ps1` does: Tailscale address 100.98.145.119, then DESKTOP-H72VKDJ, then 192.168.4.109; remembers the one that worked.
- Look: Windows 11 style (Mica, NavigationView on the left), dark by default with the display's gold accent.
- Saving: each page has Save; nothing changes on the screens until Save. A change shows "Saved, screens update within a minute."
- Team and stock search use the server (it knows the leagues' team lists and can look up tickers), so the app holds no data-source code.

## Calls made in the design (Claude's, for Avi to check)

- **Nothing changes on a PC until Avi saves.** On its first check-in a launcher sends its local mode and screen-saver options; the server stores them as that screen's settings. Until a screen is saved from the app, `/api/screen-settings` returns exactly what the PC already had. (No PC can flip to the house default by being upgraded.)
- **One name per PC.** All the monitors a PC uses share its name and rotation.
- **Sports scenes come in pairs, like today's MLB:** a team scene (favorite team: game, standings, news) and a league scene (scores, news). MLB's pair stays `yankees` + `mlb`. Switching a league on adds its pair to the house default rotation; screens with their own rotation get the new scenes switched off, to turn on in the Screens page.
- **The agenda is private to the screens that have it (Avi chooses which).** The agenda is on only for screens where Avi turns it on in the Screens page. A screen without `agenda` in its rotation gets no agenda at all: no "Next" line, and the server leaves the agenda out of that screen's `/api/state`. The house default rotation does not include it. At first start, only the always-on PC's screen (DESKTOP-H72VKDJ) keeps it, since it shows it today; Avi turns it on anywhere else.

## Left to the builder

- Ticker search: the SEC's `company_tickers.json` (sec.gov requires a contact email). That one request's User-Agent is `ShabbatDisplay/1.0 (personal home display; frischa@avifrischlaw.com)`, with Avi's approval; the email goes to sec.gov only, at most weekly, and nowhere else. Cached on the server.
- Data sources, with these rules: free, no account or API key, reachable with the standard library, honest User-Agent, and a fallback or a clear "not responding" when they fail. Expected: ESPN's public site API (`site.api.espn.com/apis/site/v2/sports/...`) for every league but MLB; for stocks a free delayed quote source (check what works from the house today, e.g. Stooq's CSV quotes); NYT Business and CNBC RSS for business news. These are unofficial endpoints, like statsapi today, and can change.
- Exact layouts of the sports and business scenes within the existing design (navy base, gold accent, serif headlines, the 120×67.5 rem canvas, `fitColumns()`).
- How the app looks beyond the page list above, and the order of fields on each page.
- Data shapes in `household.json` and the management API.
- Migration: on first start with no `household.json`, build it from today's behavior (MLB on, Yankees favorite, the current rotation as the house default, current `screensaver_*` values for screens that check in).

## Open risks

- **NYT may refuse the embedded sign-in** (some sites block WebView2). Fallback: a "Paste cookie" box in the app with one line of instructions.
- **Unofficial data sources** (ESPN, the quote source) can change or start refusing; the display must keep the last data and say so, as with every other feed.
- **Ariela's Acer** needs one more visit to put the new launcher in place and name the screen, after which it is managed from the app.
