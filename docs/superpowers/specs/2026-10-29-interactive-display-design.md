# Touch and click on the permanent display

Date: 2026-10-29. Status: written up after the conversation; approved by Avi 2026-10-29.

## Why

Until now the display was built for nobody to touch it. Avi now wants to go one level deeper when something catches his eye: read the whole article behind a headline, see the full forecast, see the box score. He uses either the iPad (Safari Home Screen web app, served by the always-on PC with `"bind": "0.0.0.0"`) or a mouse on the PC. The display must still look after itself: nothing he opens can leave it stuck, and nothing changes on Shabbat or Yom Tov.

## Goals

1. **Tap a headline** (NYT, CNN, Times of Israel, MLB.com Yankees and MLB news) to read the article as clean text in a reading panel.
2. **Tap the weather** (the current conditions block in the left column, and the hourly and 5-day rows under it) to open a detailed forecast panel.
3. **Tap a game** (any game card, mini game or live score chip) to open its line score and box score.
4. **Swipe left or right** on the scene area to move between scenes. With a mouse, click-and-drag does the same, and the left and right arrow keys work too. Clicking a scene name in the tab row at the top right jumps to it.
5. **Return on its own:** 2 minutes after the last touch, click or key press, any open panel closes and normal rotation resumes from wherever the scene is. Every open panel shows the countdown ("Back to the display in 1:42").
6. **Off on Shabbat and Yom Tov:** while `body.holy` is set, taps, clicks, swipes and keys do nothing, nothing looks tappable, and any open panel closes the moment holy mode begins.
7. **NYT subscription:** paywalled NYT articles come through in full using Avi's sign-in cookie pasted into `settings.json`.

## Non-goals

- No editing anything, no settings screen on the display, no search.
- No opening the real website inside the kiosk browser. Everything opens in panels inside the display.
- No touch support in screen-saver mode: there any input closes the screen saver and locks the PC, and that stays as is.
- No accounts for CNN, Times of Israel or MLB.com (no paywall).

## Anti-goals (would be a failure even if it works)

- The display ending up stuck on a panel, an error, a blank page or a different site with no way back but a keyboard.
- Anything reacting to touch on Shabbat or Yom Tov.
- The NYT cookie or the calendar ICS link appearing in a log, `/api/state`, the page source or an error message.
- The unattended display changing behavior when nobody touches it. With no input, it must run exactly as it does today.
- A server that, because it now fetches pages on request, can be made to fetch arbitrary URLs by anyone on the network.

## Constraints (from CLAUDE.md, still in force)

- Server is Python standard library only; nothing to pip install.
- `index.html` stays a single file with inline CSS and JS, no build step, and keeps working when opened as a file with `makeDemo()` data (panels should open with demo content there too).
- iPadOS 14.5+ Safari must work (the page already relies on `??` and flex `gap`; do not use anything newer than Safari 14.5 supports without a fallback).
- Fixed 120 x 67.5 rem canvas; the left column and bottom band stay where they are.
- Secrets in `settings.json` are never logged and never sent to the page.

## Decisions made with Avi

### Where panels open

In the scene area (the "stage", right of the left column and above the bottom band), taking the place of the current scene. Clock, weather summary, Shabbat box and zmanim bar stay visible. The panel has a close button (top right), the countdown at the bottom, and scrolls vertically by touch, mouse wheel or drag when its content is taller than the stage. While a panel is open, rotation is paused. Scene tabs stay visible; tapping one closes the panel and goes to that scene.

### Article reading panel

- Source label and age ("NEW YORK TIMES Â· 2 HOURS AGO"), the headline in the serif face, then the article body as paragraphs in the serif face. Images are left out.
- The server fetches the article on request and extracts the body text.
- NYT: the request carries the cookie from a new setting, `nyt_cookie` (the value of the `NYT-S` cookie, or the whole Cookie header; builder's choice, document it). README gets short steps for copying it from Chrome or Edge (sign in at nytimes.com, DevTools > Application > Cookies). If the cookie is missing or expired, show whatever text comes through plus a line saying the article is cut off and how to refresh the cookie.
- If extraction fails, the panel shows the feed's own summary for the item and a plain "The full article couldn't be loaded" line, never a raw error.
- Avi chose the cookie approach over a username and password, because NYT sign-in blocks automated logins.

### Box score panel (both teams at once)

- Status line (Final, or inning and outs when live; venue).
- Line score: innings, R, H, E, Yankees highlighted in gold when they play.
- Summary line: W, L, S with records, home runs with season totals.
- Two columns, away team on the left, home team on the right; in each, batting (name and position, AB, R, H, RBI, BB, K, AVG) above pitching (IP, H, ER, BB, K, ERA, with W/L/S/H decisions).
- During a live game: count, outs and base runners (reuse `diamond()`), and the panel refreshes every 30 seconds while open.
- A long game may scroll; that's accepted.
- Source: statsapi.mlb.com live feed or boxscore and linescore for the game's `gamePk` (games already carry `id`).
- Before a game starts: probable pitchers and start time instead of tables.

### Detailed forecast panel

Four parts, laid out as in the approved mockup (`.superpowers/brainstorm/.../boxscore-weather-v2.html`):

1. **Right now:** feels like, humidity, dew point, air quality (US AQI with its word: Good, Moderate...), wind and gusts, UV index, pressure with rising or falling arrow.
2. **Next 48 hours graph:** temperature line, rain-chance bars, rain amount where it's meaningful, a time axis, and a marker for candle lighting and havdalah when they fall inside the window. Inline SVG, no chart library.
3. **Radar loop:** the National Weather Service radar loop for the Upton, NY radar (KOKX), with Teaneck marked. Builder's choice of exact image product, but it must be a free, keyless NWS source, and the panel must survive it failing (show "Radar unavailable").
4. **7 days:** day, icon, low, range bar, high, rain chance. Tapping a day shows the NWS written forecast for that day and night inside the panel.

Weather alerts, when any are active, appear in full at the top of this panel.

Sources: Open-Meteo forecast (add the hourly and current fields needed), Open-Meteo air-quality API, NWS forecast periods already fetched, NWS radar image. All free and keyless.

## Server additions

- **On-demand endpoints**, fetched only when a panel opens, cached in memory for a few minutes:
  - `/api/article?url=...`
  - `/api/game?id=...`
  - `/api/forecast` (or fold the extra weather fields into the existing `weather` source if that's simpler; builder's choice).
  - Radar: proxied through the server, so the page only ever talks to its own server and the iPad needs no extra network access.
- **No open fetching:** `/api/article` only fetches a URL that currently appears as a `link` in one of the feed sources (`nyt`, `cnn`, `toi`, `yankees_news`, `mlb_news`). Anything else gets a 404. `/api/game` only accepts numeric ids.
- The NYT cookie is sent only to `nytimes.com` hosts, never logged, never included in responses or error text.
- Failures return a clean JSON error the panel can show politely; they never crash a handler thread.

## Interaction details

- **What's tappable:** each headline row; the weather block, hourly row and 5-day list in the left column (all open the same forecast panel); each game card, mini game and the live score chip; the scene tabs. Tappable things get a subtle press feedback, not underlines or buttons, so the unattended display looks the same.
- **Swipe:** horizontal on the stage only, with a threshold so a vertical scroll inside a panel or a sloppy tap isn't read as a swipe. Swiping skips scenes that are currently hidden (for example the agenda when there's no `agenda_ics`).
- **Swipe or arrow key with a panel open** (my call, not discussed): behaves like tapping a scene tab, closing the panel and moving to the next or previous scene. A drag counts as a swipe only when it is mostly horizontal and past the threshold; a mostly vertical drag scrolls the panel.
- **Mouse pointer** (my call, not discussed): the page hides it today (`cursor:none`). It appears when the mouse moves and hides again when the 2-minute idle timer runs out, so the unattended display looks the same as now. On the iPad there is no pointer.
- **Idle timer:** any input resets the 2-minute timer. When it runs out: close any panel, then resume the normal rotation (the next scene change follows the usual durations).
- **Holy mode:** event handlers check `body.holy` and do nothing; tappable styling is removed; an open panel closes when `renderAll()` sees holy mode start.
- **Scene repaint:** the 20-second poll must not repaint over an open panel or reset its scroll.
- **Screen-saver mode (`?saver=1`):** interaction is off, since input closes the window anyway.

## Left to the builder

- Article text extraction method (stdlib `html.parser`; site-specific selectors for the five sources, with a generic fallback such as the longest run of `<p>` elements, are fine).
- Exact MLB endpoint, caching times, and the radar image product.
- Panel animation and press-feedback styling, within the existing design language (navy, warm off-white, gold accent, sky blue for weather, serif for headlines and article text).
- How `makeDemo()` supplies demo article, box score and forecast data.
- Tests: the repo has none; verify with `python server.py --check`, the `?at=` and `?scene=` URL parameters, and screenshots at 1920x1080, 1366x768, 1440x900 and an iPad size (1180x820).

## Docs to update

CLAUDE.md (architecture, the "nobody interacts with it" line, data sources table, settings), README (NYT cookie steps, what's tappable), `settings.example.json` (`nyt_cookie`).
