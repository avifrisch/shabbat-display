# Shabbat Display

A full-screen dashboard for a spare laptop. It updates itself on fixed timers and needs no one to touch it, from candle lighting through havdalah.

**What it shows**

- **Always on screen:** clock, English and Hebrew date, current weather, the next 8 hours, a 5-day forecast, and a zmanim bar for the day. The bar marks where the sun is right now and highlights the next zman. After tzeit it switches to tomorrow's times.
- **Bottom left:** this week's Shabbat or Yom Tov, with candle lighting, havdalah, and a countdown on Friday afternoon. From candle lighting to havdalah the screen switches to a warm Shabbat theme.
- **Rotating panel:** four screens that alternate:
  - **Yankees:** live or last game, AL East standings, roster moves, Yankees news.
  - **MLB:** today's scores, league transactions, MLB.com news.
  - **Headlines:** The New York Times and CNN.
  - **Israel:** The Times of Israel.
- **During a live Yankees game:** the Yankees screen comes up every other turn, and a live score chip stays in the corner of the other screens.
- **Overnight:** the screen dims, 11 pm to 6:30 am by default.

## Data sources (all free, no accounts)

| What | Where it comes from | Refresh |
|---|---|---|
| Weather and forecast | Open-Meteo | 10 min |
| Forecast text and weather alerts | National Weather Service | 30 min / 5 min |
| Zmanim, Hebrew date, candle lighting, havdalah, parashah, holidays | Hebcal | 5–60 min |
| Yankees games, scores, standings, transactions | MLB Stats API | 30 sec during games, 3 min otherwise |
| MLB and Yankees news | MLB.com RSS (NBC New York as backup) | 15 min |
| NYT | NYT home page RSS | 10 min |
| CNN | lite.cnn.com, with a Google News backup (CNN no longer updates its RSS feeds) | 10 min |
| Times of Israel | Times of Israel RSS, with a Google News backup | 10 min |

If a source fails, the screen keeps showing the last good data, notes how old it is, and the server keeps retrying. Everything is also saved to `cache.json`, so a restart comes back with data right away.

## Setup on a Windows laptop

1. **Install Python 3** from python.org. On the first installer screen, tick **Add python.exe to PATH**.
2. **Copy this folder** somewhere permanent, such as `C:\ShabbatDisplay`.
3. **Test the feeds.** Double-click `check-feeds.bat`. Every line should say OK. One or two failures on the first try are usually a slow connection.
4. **Start it.** Double-click `start-display.bat`. Chrome (or Edge if Chrome isn't installed) opens full screen on the dashboard.
   - The launcher restarts the server or the browser if either one closes or crashes.
   - To get out of full screen, press Alt+F4.
5. **Start it automatically.**
   - Press Win+R, type `shell:startup`, and press Enter.
   - Put a shortcut to `start-display.bat` in that folder.

## Windows settings for a 25-hour unattended run

- **Power:** while it's running, the launcher tells Windows to keep the screen on and not sleep, and the page asks the browser to do the same. As a backup, set "When plugged in, turn off my screen" and "put my device to sleep" to **Never**. **Lid close must be set to Do nothing**: nothing a program does can override closing the lid. Keep it plugged in.
- **Windows Update:** set active hours to cover Shabbat, or pause updates before Shabbat, so it doesn't restart itself.
- **Notifications:** turn on Do Not Disturb permanently. Turn off the screen saver.
- **Power failures:** set automatic sign-in (run `netplwiz` and untick "Users must enter a user name and password"). If the laptop's BIOS has a "power on after AC loss" option, turn it on. Together these bring the display back after an outage with no one touching it.
- **Network:** a wired Ethernet adapter is the most reliable. If you use Wi-Fi, make sure it's set to connect automatically.
- **Input:** cover the keyboard so nobody bumps a key. If you lower the lid partway, make sure it doesn't trip the lid sensor.

## Settings

Open `server.py` in Notepad and edit the `CONFIG` block at the top. Restart the display afterward.

- **Location:** latitude, longitude, ZIP (used for Hebcal).
- **Candle lighting minutes** (default 18).
- **Havdalah method:** `"M=on"` is tzeit at 8.5°; `"m=50"` is 50 minutes after sunset.
- **Zmanim labels:** `"hebrew"` or `"english"`.
- **Dimming:** start time, end time, and how dark.
- **Rotation:** seconds each screen stays up.
- **Other devices:** set `"bind": "0.0.0.0"` to view the dashboard from another device on your network, such as a tablet in another room, at `http://<laptop-ip>:8765`.

## Previewing and testing

Open `index.html` directly (without the server) to see the layout with preview data.

With the server running, you can add these to the address:

- `?at=2026-10-30T15:10`: pretend it's a given time. Use this to see the Friday countdown or Shabbat mode before Shabbat.
- `?scene=yankees&hold=1`: show one screen without rotating. The others are `mlb`, `news` and `israel`.

## Files

| File | What it does |
|---|---|
| `server.py` | Data server. Uses only the Python standard library; nothing to install. |
| `index.html` | The dashboard page. |
| `launcher.pyw` | Keeps the server and the full-screen browser running. |
| `start-display.bat` | Starts everything with no console window. |
| `check-feeds.bat` | Tests every data source once. |
| `fonts/` | Archivo, Newsreader and Frank Ruhl Libre, bundled so the page looks right offline. All are under the SIL Open Font License. |
| `cache.json`, `server.log`, `launcher.log` | Created when it runs. Safe to delete. |
