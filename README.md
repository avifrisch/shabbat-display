# Shabbat Display

A full-screen dashboard for a spare Windows PC or laptop, or a Raspberry Pi on a wall monitor. It updates itself on fixed timers and needs no one to touch it, from candle lighting through havdalah. On weekdays you can also tap it (on an iPad) or click it (with a mouse) to read more; see [Tapping and swiping](#tapping-and-swiping).

**What it shows**

- **Always on screen:** clock, English and Hebrew date, current weather, the next 8 hours, a 5-day forecast, and a zmanim bar for the day. The bar marks where the sun is right now and highlights the next zman. After tzeit it switches to tomorrow's times.
- **Bottom left:** this week's Shabbat or Yom Tov, with candle lighting, havdalah, and a countdown on Friday afternoon. From candle lighting to havdalah the screen switches to a warm Shabbat theme.
- **Rotating panel:** screens that alternate:
  - **Agenda** (weekdays, once you add your calendar): today's events and the next day's, with deadlines and court dates labeled. A "Next" line under the clock shows the next event and how many deadlines are due today. Both disappear from candle lighting until havdalah.
  - **Shul** (Congregation Bnai Yeshurun): on weekdays, the shul's weekly davening chart, with buttons for the monthly calendar and the bulletin. On Shabbat and Yom Tov, the Shabbat Times from the weekly bulletin: candle lighting, every minyan and shiur, Mincha, Shabbat ends and next week's candle lighting. See [The Shul screen](#the-shul-screen).
  - **Yankees:** live or last game, AL East standings, roster moves, Yankees news.
  - **MLB:** today's scores, league transactions, MLB.com news.
  - **Headlines:** The New York Times and CNN.
  - **Israel:** The Times of Israel.
- **During a live Yankees game:** the Yankees screen comes up every other turn, and a live score chip stays in the corner of the other screens.
- **Overnight:** the screen dims, 11 pm to 6:30 am by default.

## Tapping and swiping

On the iPad, tap. On the PC, click with the mouse (the pointer appears when you move it).

- **A headline** opens the article as text in a reading panel.
- **The weather** (the current conditions, the hourly row or the 5-day list) opens a detailed forecast: conditions right now with air quality, a 48-hour graph of temperature and rain, the radar loop, and 7 days. Tap a day for the Weather Service's written forecast.
- **A game** (or the live score chip) opens the line score and box score for both teams. During a live game it updates every 30 seconds.
- **Swipe left or right** to change screens. With a mouse, drag, or use the left and right arrow keys. Tap a screen name at the top right to jump to it.
- **Close a panel** with ✕ (or Escape).
- **Two minutes after the last touch,** any open panel closes, the pointer hides, and the normal rotation resumes.
- **On Shabbat and Yom Tov,** from candle lighting until havdalah, tapping and swiping do nothing, and an open panel closes when Shabbat begins.

**Articles:** CNN and MLB.com articles open in full. The New York Times and the Times of Israel sometimes block requests that don't come from a browser; then the panel shows the article's summary and says the full article couldn't be loaded.

**Reading full NYT articles with your subscription:**

1. In Chrome or Edge on any computer, sign in at nytimes.com.
2. Press F12, open **Application** → **Cookies** → `https://www.nytimes.com`, and find the cookie named `NYT-S`.
3. Copy its **Value** into `settings.json` as `"nyt_cookie": "<value>"`, then restart the display.

It lasts for months. When it runs out, an NYT article shows only its first paragraphs, with a note saying so; repeat the steps. The cookie is a password to your NYT account: it stays in `settings.json`, is sent only to nytimes.com, and is never logged or shown on the page.

## The Shul screen

The shul posts its weekly davening chart, its Shabbat bulletin and a monthly calendar on bnaiyeshurun.org. The display fetches them itself every Friday (and the day before Yom Tov) from noon, once an hour until it has this week's bulletin, and stops at candle lighting. If the chart is more than a week old, it also checks once an hour during the day until the new one is up. To fetch them now (say the shul posted something late), double-click `update-shul.bat` (`./update-shul.sh` on a Pi) on the display machine. It lists what it got.

- **Weekdays:** the chart fills the screen. Tap it to see it bigger, or tap **October calendar**, **November calendar** or **Bulletin**. On the PC the bulletin opens in the panel; on the iPad it opens in Safari's own viewer, so every page shows.
- **Shabbat:** the Shabbat Times box, read from the bulletin and laid out like the rest of the display.
- **Old information is marked:** if the chart is from an earlier week, or this week's bulletin isn't posted yet, the screen says so. On Shabbat, if this week's bulletin isn't in yet or its times can't be read, it shows candle lighting and havdalah from Hebcal and says to see the bulletin. It never shows last week's times as this week's.

Every request names itself (`ShabbatDisplay/1.0 (personal home display)`) and only files that changed are downloaded. If the site ever refuses those requests, the display keeps the last files it has.

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
| Shul davening chart, bulletin, monthly calendar | bnaiyeshurun.org | Fridays from noon until this week's bulletin is in, or `update-shul` |
| Other sports (NBA, WNBA, NFL, NHL, MLS, college basketball and football) | ESPN's public site API | 30 sec around your teams' games, 3 min otherwise, hourly out of season |
| Market indices and your stocks (delayed) | CNBC's quote service, Yahoo as backup | 5 min while the market is open, once after the close |
| Business headlines | NYT Business and CNBC RSS | 15 min |
| Article text, box scores, detailed forecast, radar | The news sites, MLB Stats API, Open-Meteo (forecast and air quality), National Weather Service (forecast and Upton, NY radar) | Only when a panel is open |

If a source fails, the screen keeps showing the last good data, notes how old it is, and the server keeps retrying. Everything is also saved to `cache.json`, so a restart comes back with data right away.

## The Display Manager

The Display Manager is a Windows app on Avi's PC that runs the whole house's display: which sports and teams, the stock watchlist, each screen's rotation, whether a PC shows the display all the time or as a screen saver, the shul's files, the server's health, and the NYT sign-in. It talks to the server on the always-on PC. Its settings live there in `household.json`, so the screens never need the app, including on Shabbat.

- **Access code:** setup prints it at the end on the always-on PC (it's in `manage-key.txt`). The app asks for it once.
- **Screens:** every PC's launcher checks in under its own name (the PC's name, or `screen_name` in `settings.json`). Until you save a screen in the app, it keeps doing what its own settings say. After a save, the change reaches it within a minute.
- **Agenda:** only on screens where you turn it on. The others get no agenda data at all.
- **The iPad:** add `?screen=iPad` to its address (`http://<ip>:8765/?screen=iPad`) so it gets its own rotation.

### Building and using the app

Run `build-manager.bat` in `C:\ShabbatDisplay`. It runs the app's tests, builds it into `dist\manager` (with its own copy of .NET, so nothing else needs installing), and adds **Shabbat Display Manager** to the Start menu. It needs the .NET SDK (8 or later), which is already on Avi's PC.

On first start the app looks for the server: the address that worked last time, then Tailscale (100.98.145.119), then DESKTOP-H72VKDJ, then 192.168.4.109. It then asks for the access code once and keeps it in Windows Credential Manager (`ShabbatDisplayManager`). Nothing changes on the screens until you press a page's **Save**. After a save the screens catch up within a minute.

- **Status:** "Everything is working", or each problem in a sentence (a feed failing for half an hour, the bulletin unreadable, a PC that stopped checking in), then every feed, the shul's files and every screen.
- **Sports:** each league on or off, its teams, and the favorite (★) whose games get their own scene. Switching a league on adds it to the house rotation.
- **Business:** the business scene on or off, the watchlist (search by ticker or company), and which headlines it shows.
- **Screens:** the house rotation, and for each screen either the house rotation or its own: which scenes, in what order, for how many seconds. For a PC, also always-on or screen saver and the screen-saver options.
- **Shul:** whether this week's chart, bulletin (and how many Shabbat times were read) and calendar came in. **Update now** checks the shul's site once.
- **NYT:** sign in on the NYT's own page inside the app, or paste the `NYT-S` cookie if that page doesn't work. Sign out removes it.
- **Server:** the feeds, the last 200 log lines, and **Restart server**.

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

On a PC you sit at, the display can come up as a screen saver instead of running full time. It appears after 10 minutes without mouse or keyboard input, on every monitor, and any mouse move or key press closes it and locks the PC, so you sign back in as you would after a Windows screen saver.

1. Copy this folder somewhere permanent and double-click `setup-windows.bat`, as above.
2. At the first question, choose **2. Screen saver**. Setup leaves your power settings alone, offers to turn off the Windows screen saver so the two don't overlap, and turns the display's screen saver on each time you sign in.

**What to know:**

- **When it doesn't appear:** while a full-screen window is in front (a slideshow, a video call, a full-screen video) or while the PC is locked.
- **When the screen turns off:** at the time set under Settings → System → Power → "Turn off my screen after".
- **If the PC locks itself after a while** (Settings → Accounts → Sign-in options → "If you've been away"), the lock screen covers the display at that point.
- **Changing the wait:** set `screensaver_minutes` in `settings.json`. It takes effect right away (the launcher reads its settings each time). If `settings.json` has a typo, every setting falls back to its default and `screensaver.log` says so.
- **Not locking:** set `"screensaver_lock": false` in `settings.json`. It takes effect the next time the screen saver closes.
- **A laptop with a monitor plugged in:** setup asks whether to use only the plugged-in monitor. With `"screensaver_screens": "external"` the display shows on the monitor and the laptop's own screen is turned all the way down while it shows (Windows can't switch off just one screen), then put back on any input. Without the monitor, it shows on the laptop screen.
- **Keeping the PC awake:** with `"keep_pc_awake": true` (setup asks) the PC never goes to sleep while the screen saver is on, and while the display shows its screens stay on (it dims itself overnight). Otherwise the screens turn off on the power plan's schedule. Closing a laptop's lid still does what the power plan says.
- **Updating:** download the new zip, extract it, and run its `setup-windows.bat`. It offers to update the copy in `C:\ShabbatDisplay` and keeps its settings.
- **Starting and stopping it by hand:** `start-screensaver.bat` turns it on and `stop-display.bat` turns it off.

## Another PC in the house

A second PC, full time or as a screen saver, can show the always-on PC's display instead of fetching everything itself. Your calendar link then stays on the one PC that has it, and there's nothing to configure.

**Making the download:** on the PC with this folder, double-click `make-installer.bat`. It builds `dist\ShabbatDisplay.zip` from the committed files, so `settings.json` and its secrets are never in it. Upload the zip to your website.

**On the other PC:**

1. Download the zip, right-click → **Extract All**, and double-click `setup-windows.bat` in the extracted folder. Setup offers to move itself to `C:\ShabbatDisplay`; say yes.
2. Choose **Full time** or **Screen saver**.
3. Setup looks for the always-on PC: first over Tailscale (if this PC has it and is connected), then by name on the home network, then by its home-network address. When it finds it, choose **1** to show that PC's display. If it doesn't find it, setup says why (Tailscale not installed or not connected, not on the home Wi-Fi), and you can type an address, run a separate copy with its own data, or stop and try later.

**What to know:**

- **The always-on PC** must be on, with the display server reachable from the network (`"bind": "0.0.0.0"` and the firewall rule; see the iPad section below). The firewall rule also needs the Tailscale range (`100.64.0.0/10`) for Tailscale to work.
- **The always-on PC's addresses** are at the top of `setup-windows.ps1` (`$ServerName`, `$ServerAddresses`). Change them there if that PC changes, and build the zip again.
- **If the always-on PC is off,** the full-time screen waits and opens once it answers, and the screen saver doesn't appear.
- **To switch a PC back to its own data,** run setup again and choose the separate copy. It takes `server_url` out of `settings.json`.
- **The download is public** unless your website protects it. It has no secrets in it, but anyone with the link can read the code.

## On an iPad, as a second screen

An iPad can't run the display itself, but it can show the one running on your PC or Pi over Wi-Fi. It needs iPadOS 14.5 or later (iPad Air 2, iPad mini 4, iPad 5th generation, or newer).

1. On the computer running the display, set `"bind": "0.0.0.0"` in `settings.json` and restart the display. On Windows, allow TCP port 8765 in the firewall for the local network:
   `New-NetFirewallRule -DisplayName "Shabbat Display (local network)" -Direction Inbound -Protocol TCP -LocalPort 8765 -RemoteAddress LocalSubnet -Action Allow` (in an administrator PowerShell).
2. On the iPad, open `http://<computer's IP address>:8765` in Safari. Then tap Share → **Add to Home Screen** and open it from the home screen, which shows it full screen.
3. Set **Auto-Lock** to Never (Settings → Display & Brightness), turn on **Do Not Disturb**, and turn off automatic iPadOS updates. Optionally, use **Guided Access** (Settings → Accessibility) so nobody can leave the page.

**What to know:**

- **Fixed address:** give the computer a fixed IP address in your router (a "DHCP reservation"), so the address doesn't change.
- **Size:** hold it in landscape. The display stretches to fill the iPad's screen, and panels you tap open full screen in larger type.
- **Who can see it:** anyone on your home Wi-Fi can open the page, agenda included.
- **If the computer restarts,** the iPad shows an error until someone reloads the page.
- **The battery:** an old iPad left plugged in all the time can develop a swollen battery. Check it now and then.

## The iPad app and its voice assistant

The iPad can also run the display as an app (`apple/`, built with Xcode on a Mac; iPadOS 17 or later). The app shows the same display, keeps the screen on, and comes back by itself after the computer restarts. On first run it asks for the computer's address. Hold the top-left corner for two seconds to open its settings again.

**Voice** is off until you switch on **Listen for requests** in the app's settings. Then say the wake phrase ("hey display" unless you change it) and a request:

- "Hey display, set a pasta timer for ten minutes." Timers show in the corner, ring and say their name. Say "stop" or tap the timer to quiet it.
- "Hey display, add milk and eggs to the shopping list." "What's on the list?" "Take the eggs off."
- "Hey display, play some quiet jazz." "Pause." "Next." "Stop the music." Music comes from Apple Music, so the iPad needs to be signed in to an Apple Music subscription. A bar in the corner shows what is playing, with pause, next and stop buttons. The music goes quiet while you talk to the display.
- "Hey display, turn off the kitchen lights." "Set the thermostat to 70." "Run Good Night." "Is the front door locked?" This is Apple Home: switch on **Control the Home** in the app's settings, and make sure the iPad's Apple ID is a member of your Home. Use the names your devices and scenes have in the Home app. The display will lock a door or close the garage, but it never unlocks or opens one.
- "Hey display, reorder from Walmart." A code appears on the display; scan it with your phone and Walmart opens with your usual items in the cart. You review the cart and check out on the phone. The display never orders or pays for anything.
- "Hey display, send the list to my phone." The code opens the shopping list page (below).
- "Hey display, when is candle lighting?" It knows the time, the weather and the Shabbat times on the display, and answers general questions from what Claude knows. It can't search the internet.

**On Shabbat and Yom Tov the microphone is off**, from candle lighting to havdalah, and so are speech and timers. It is also off whenever the iPad can't tell what day it is (no calendar from the computer yet, or one that has run out). The display itself carries on as always.

**Setting up the assistant** (once, on the display computer):

1. Get a Claude API key at console.anthropic.com. Leave auto-reload off there, so nothing can be charged beyond the credit you have.
2. Put it in `settings.json` as `"anthropic_api_key": "sk-ant-..."` and restart the display.

**What it costs.** Each request goes to Claude's smallest model and costs a small fraction of a cent. The computer keeps count in `assistant-budget.json` and stops for the rest of the month at `assistant_monthly_usd` (5 dollars unless you change it), and after `assistant_daily_requests` requests in a day (300). When it stops, the iPad says so. If that file is ever damaged the assistant stays off rather than start counting from zero; delete the file to start the month's count again.

**The shopping list page.** `http://<computer>:8765/shop`, on any phone on the home Wi-Fi (or scan the code the display shows). It lists what's on the shopping list, with a "Find at Walmart" link beside each item, and it is where you set up your **usual Walmart items**: a name, how many, and the product's link from walmart.com or the Walmart app (Share → Copy link). "Put the usual items in my Walmart cart" opens Walmart with every usual item that has a link. Items without a link are left out of the cart.

**MenuApp.** To have spoken items also appear in MenuApp's Grocery tab, copy the URL from MenuApp → Settings → Kitchen Display → Copy Display URL and put it in `settings.json` as `"menuapp_grocery_url"`. Items land in MenuApp's "Kitchen display" list the next time the app is opened.

**Apple Music, once.** The app has to be allowed to use Apple Music in your Apple developer account: developer.apple.com → Certificates, Identifiers & Profiles → Identifiers → `com.avifrischlaw.shabbatdisplay` → App Services → MusicKit. Until then the display says that Apple Music didn't answer.

The shopping list is kept on the display computer in `shopping.json`, and the usual items in `usuals.json`.

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
- **Screen saver:** `screensaver_minutes`, the minutes without mouse or keyboard input before the display appears (screen saver mode only; default 10). `screensaver_lock` (default `true`) locks Windows when input closes it.
- **NYT subscription:** `nyt_cookie`, for full NYT articles in the reading panel. See [Tapping and swiping](#tapping-and-swiping). Secret, like the agenda links.
- **Other devices:** set `"bind": "0.0.0.0"` to view the dashboard from another device on your network, such as a tablet in another room, at `http://<computer-name-or-ip>:8765`.
- **Team:** `team_id`, `team_abbr`, `division_id`, `division_name`, `league_id` (not in the example file; defaults are the Yankees and the AL East). The Display Manager's MLB favorite overrides these.
- **Screen name:** `screen_name`, this PC's name in the Display Manager (empty uses the PC's name).

What the Display Manager sets (sports, stocks, rotations, screen modes, the NYT sign-in) is kept in `household.json` and overrides the same things here.

## Previewing and testing

Open `index.html` directly (without the server) to see the layout with preview data.

With the server running, you can add these to the address:

- `?at=2026-10-30T15:10`: pretend it's a given time. Use this to see the Friday countdown or Shabbat mode before Shabbat.
- `?scene=yankees&hold=1`: show one screen without rotating. The others are `agenda`, `shul`, `mlb`, `news` and `israel`.
- `?debug=1`: lets you shorten the 2-minute return for testing, by typing `IDLE_MS_OVERRIDE = 5000` in the browser console.

The server's on-demand and shul code has automated tests (standard library only): `python -m unittest discover -s tests`.

## Files

| File | What it does |
|---|---|
| `setup-windows.bat`, `setup-pi.sh` | One-time setup. Safe to run again. |
| `start-display.*`, `stop-display.*` | Start or stop the display (`.bat` on Windows, `.sh` on the Pi). |
| `start-screensaver.bat` | Turns on screen saver mode (Windows). `stop-display.bat` turns it off. |
| `check-feeds.*` | Tests every data source once. |
| `update-shul.*` | Fetches the shul's chart, bulletin and calendar now. |
| `make-installer.bat` | Builds `dist\ShabbatDisplay.zip`, the download for another PC in the house. |
| `build-manager.bat`, `manager/` | Builds the Display Manager app into `dist\manager` (Avi's PC only; not in the installer zip). |
| `settings.example.json` | Template for `settings.json`, your settings. |
| `server.py` | Data server. Uses only the Python standard library; nothing to install. |
| `index.html` | The dashboard page. |
| `launcher.pyw` | Keeps the server and the full-screen browser running, on Windows and Linux. |
| `setup-windows.ps1` | The Windows setup steps; `setup-windows.bat` runs it. |
| `fonts/` | Archivo, Newsreader and Frank Ruhl Libre, bundled so the page looks right offline. All are under the SIL Open Font License. |
| `settings.json`, `cache.json`, `*.log`, `browser-profile*/`, `shul/` | Created when it runs. All but `settings.json` are safe to delete. |
