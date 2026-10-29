# Shabbat Display

A full-screen dashboard for a spare Windows PC or laptop, or a Raspberry Pi on a wall monitor. It updates itself on fixed timers and needs no one to touch it, from candle lighting through havdalah.

**What it shows**

- **Always on screen:** clock, English and Hebrew date, current weather, the next 8 hours, a 5-day forecast, and a zmanim bar for the day. The bar marks where the sun is right now and highlights the next zman. After tzeit it switches to tomorrow's times.
- **Bottom left:** this week's Shabbat or Yom Tov, with candle lighting, havdalah, and a countdown on Friday afternoon. From candle lighting to havdalah the screen switches to a warm Shabbat theme.
- **Rotating panel:** screens that alternate:
  - **Agenda** (weekdays, once you add your calendar): today's events and the next day's, with deadlines and court dates labeled. A "Next" line under the clock shows the next event and how many deadlines are due today. Both disappear from candle lighting until havdalah.
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
| Agenda | The LPM calendar feed, or any calendar's private ICS link | 10 min |

If a source fails, the screen keeps showing the last good data, notes how old it is, and the server keeps retrying. Everything is also saved to `cache.json`, so a restart comes back with data right away.

## Setup on a Windows PC or laptop

1. **Copy this folder** somewhere permanent, such as `C:\ShabbatDisplay`. Not Downloads, and not inside the zip.
2. **Double-click `setup-windows.bat`.** It asks before each change:
   - installs Python 3 with winget if it isn't already installed (nothing else to install)
   - creates `settings.json`
   - tests every data source
   - sets the screen and computer to never sleep while plugged in, and lid close to do nothing
   - makes the display start when you sign in
   - starts it
3. **Do the manual steps** under [Keeping it running unattended](#keeping-it-running-unattended).

Chrome is used if it's installed; otherwise Edge, which comes with Windows.

## As a screen saver on a work PC

On a PC you sit at, the display can come up as a screen saver instead of running full time. It appears after 10 minutes without mouse or keyboard input, and any mouse move or key press closes it.

1. Copy this folder somewhere permanent and double-click `setup-windows.bat`, as above.
2. At the first question, choose **2. Screen saver**. Setup leaves your power settings alone, offers to turn off the Windows screen saver so the two don't overlap, and turns the display's screen saver on each time you sign in.

**What to know:**

- **When it doesn't appear:** while a full-screen window is in front (a slideshow, a video call, a full-screen video) or while the PC is locked.
- **When the screen turns off:** at the time set under Settings → System → Power → "Turn off my screen after".
- **If the PC locks itself after a while** (Settings → Accounts → Sign-in options → "If you've been away"), the lock screen covers the display at that point.
- **Changing the wait:** set `screensaver_minutes` in `settings.json`, then sign out and back in.
- **Starting and stopping it by hand:** `start-screensaver.bat` turns it on and `stop-display.bat` turns it off.

## On an iPad, as a second screen

An iPad can't run the display itself, but it can show the one running on your PC or Pi over Wi-Fi. It needs iPadOS 14.5 or later (iPad Air 2, iPad mini 4, iPad 5th generation, or newer).

1. On the computer running the display, set `"bind": "0.0.0.0"` in `settings.json` and restart the display. On Windows, allow TCP port 8765 in the firewall for the local network:
   `New-NetFirewallRule -DisplayName "Shabbat Display (local network)" -Direction Inbound -Protocol TCP -LocalPort 8765 -RemoteAddress LocalSubnet -Action Allow` (in an administrator PowerShell).
2. On the iPad, open `http://<computer's IP address>:8765` in Safari. Then tap Share → **Add to Home Screen** and open it from the home screen, which shows it full screen.
3. Set **Auto-Lock** to Never (Settings → Display & Brightness), turn on **Do Not Disturb**, and turn off automatic iPadOS updates. Optionally, use **Guided Access** (Settings → Accessibility) so nobody can leave the page.

**What to know:**

- **Fixed address:** give the computer a fixed IP address in your router (a "DHCP reservation"), so the address doesn't change.
- **Who can see it:** anyone on your home Wi-Fi can open the page, agenda included.
- **If the computer restarts,** the iPad shows an error until someone reloads the page.
- **The battery:** an old iPad left plugged in all the time can develop a swollen battery. Check it now and then.

## Setup on a Raspberry Pi

**What you need:** a Raspberry Pi 4 (2 GB or more) or Pi 5, its official power supply, a microSD card of 16 GB or more, and an HDMI cable for the monitor or TV.

1. **Install Raspberry Pi OS.** In Raspberry Pi Imager, choose **Raspberry Pi OS (64-bit)**, the version with the desktop. Under the settings (gear icon), set a username and password and your Wi-Fi, and turn on SSH if you want to manage it from another computer.
2. **Copy this folder to the Pi**, into the home folder. Either:
   - put it on a USB stick and drag it across in the Pi's file manager, or
   - from another computer: `scp -r shabbat-display <user>@<pi-name>.local:~/`
3. **Run the setup.** Open a terminal on the Pi (or SSH in) and run:

   ```
   cd ~/shabbat-display
   bash setup-pi.sh
   ```

   It asks before each change:
   - installs Chromium if needed (Python is already on the Pi)
   - creates `settings.json`
   - sets the Pi's time zone to the one in `settings.json`
   - tests every data source
   - boots straight to the desktop and logs in, with screen blanking off
   - makes the display start when the desktop starts
   - reboots to check that it comes up on its own

**Starting and stopping:** `./start-display.sh` and `./stop-display.sh` (run these from the Pi's own desktop, not over SSH). `./check-feeds.sh` tests the data sources.

**The clock:** a Pi 4 has no clock battery and sets its time from the internet at boot. If it starts up with no network after a power cut, the time, zmanim and Shabbat mode are wrong until it reconnects. A Pi 5 keeps time if you add its clock battery.

The same script works on other Debian or Ubuntu desktops, such as a mini PC. There it skips the Pi-only steps and tells you which settings to change by hand.

## Keeping it running unattended

**Both:**

- **Power failures:** the display comes back on its own once the computer boots and logs in. A Pi does this by itself. On a PC, see below.
- **Network:** wired Ethernet is the most reliable. On Wi-Fi, make sure it connects automatically.
- If a browser window is closed or crashes, the launcher reopens it within a minute. To stop the display entirely, run `stop-display.bat` (Windows) or `./stop-display.sh` (Pi).

**Windows, by hand:**

- **Windows Update:** set active hours to cover Shabbat, or pause updates before Shabbat, so it doesn't restart itself.
- **Notifications:** turn on Do Not Disturb.
- **Power failures:** run `netplwiz` and untick "Users must enter a user name and password". If the BIOS has a "power on after AC loss" option, turn it on.
- **Laptop lid:** setup sets lid close to "do nothing", but keep it plugged in. If you lower the lid partway, make sure it doesn't trip the lid sensor. Cover the keyboard so nobody bumps a key.

## Settings

Edit `settings.json` (Notepad on Windows, or `nano settings.json` on the Pi), then restart the display. Setup creates it from `settings.example.json`. Anything you leave out uses the default in `server.py`, and updating the program never overwrites your settings.

- **Location:** `location_name`, `lat`, `lon`, `zip` (used for Hebcal) and `tzid`. The computer's own time zone must match `tzid`.
- **Candle lighting minutes:** `candle_minutes` (default 18).
- **Havdalah method:** `"M=on"` is tzeit at 8.5°; `"m=50"` is 50 minutes after sunset.
- **Zmanim labels:** `"hebrew"` or `"english"`.
- **Dimming:** `dim_start`, `dim_end`, and `dim_level` (0 = no dimming, 0.8 = very dark).
- **Rotation:** `rotation_seconds`, how long each screen stays up.
- **Agenda:** `agenda_ics`, a list of private calendar links. Use more than one to merge calendars. The link is a secret, so keep it only in `settings.json`, which is never uploaded to GitHub.
  - **LPM:** the calendar feed link (`/calendar/feed/<token>.ics`). Entries tagged `CATEGORIES:deadline` or `court_date` get a Deadline or Court label.
  - **Outlook / Microsoft 365:** in Outlook on the web, go to Settings → Calendar → Shared calendars → Publish a calendar. Choose **Can view titles and locations**, click Publish, and copy the **ICS** link.
  - **Google:** Settings → your calendar → Integrate calendar → **Secret address in iCal format**.
- **Screen saver:** `screensaver_minutes`, the minutes without mouse or keyboard input before the display appears (screen saver mode only; default 10).
- **Other devices:** set `"bind": "0.0.0.0"` to view the dashboard from another device on your network, such as a tablet in another room, at `http://<computer-name-or-ip>:8765`.
- **Team:** `team_id`, `team_abbr`, `division_id`, `division_name`, `league_id` (not in the example file; defaults are the Yankees and the AL East).

## Previewing and testing

Open `index.html` directly (without the server) to see the layout with preview data.

With the server running, you can add these to the address:

- `?at=2026-10-30T15:10`: pretend it's a given time. Use this to see the Friday countdown or Shabbat mode before Shabbat.
- `?scene=yankees&hold=1`: show one screen without rotating. The others are `agenda`, `mlb`, `news` and `israel`.

## Files

| File | What it does |
|---|---|
| `setup-windows.bat`, `setup-pi.sh` | One-time setup. Safe to run again. |
| `start-display.*`, `stop-display.*` | Start or stop the display (`.bat` on Windows, `.sh` on the Pi). |
| `start-screensaver.bat` | Turns on screen saver mode (Windows). `stop-display.bat` turns it off. |
| `check-feeds.*` | Tests every data source once. |
| `settings.example.json` | Template for `settings.json`, your settings. |
| `server.py` | Data server. Uses only the Python standard library; nothing to install. |
| `index.html` | The dashboard page. |
| `launcher.pyw` | Keeps the server and the full-screen browser running, on Windows and Linux. |
| `setup-windows.ps1` | The Windows setup steps; `setup-windows.bat` runs it. |
| `fonts/` | Archivo, Newsreader and Frank Ruhl Libre, bundled so the page looks right offline. All are under the SIL Open Font License. |
| `settings.json`, `cache.json`, `*.log`, `browser-profile*/` | Created when it runs. All but `settings.json` are safe to delete. |
