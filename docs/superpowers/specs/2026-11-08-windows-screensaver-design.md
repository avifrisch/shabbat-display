# A real Windows screen saver for the Shabbat Display

Date: 2026-11-08. Status: approved by Avi on 2026-11-08.

## Why

On Ariela's Acer and Avi's Surface Studio, the display runs as a screen saver today through the launcher's own screen-saver mode (`launcher.pyw --screensaver`). Avi's verdict: "it is not a real screen saver". It only works on one screen. It messes with the display settings: it sets the built-in panel's brightness to 0 and keeps a restore file. Coming back to the lock screen is slow and janky: it kills a kiosk browser, then calls `LockWorkStation`. He wants the one Windows already has, picked in Windows' own Screen Saver Settings, because "using the built in settings should function better", while still managing it from the Display Manager app.

## What it is

- A Windows screen saver (`ShabbatDisplay.scr`) that shows the house display. Windows decides when it starts and closes it. Windows does the locking ("On resume, display logon screen").
- It's on two PCs: Ariela's Acer and Avi's Surface Studio. Both show the **always-on PC's display** (DESKTOP-H72VKDJ, found as the setup script finds it today: Tailscale 100.98.145.119, then the name, then 192.168.4.109). The Surface stops running its own separate display server; Avi chose "always on display".
- **Every screen joins in**, the Surface's built-in screen included. Each screen shows the full display, and each is on a different scene at the same moment (for example the shul chart on one, scores on another), all rotating. *Avi's words were "show two of the screens at once", then "join in" for the laptop screen. Reading that as different scenes on each screen was my guess, played back to him, and he said "perfect".*
- **It never touches brightness or any display setting.**
- **Coming back is instant on weekdays:** any mouse move, click or key closes it at once, and Windows shows the sign-in screen if locking is on. Over Shabbat and Yom Tov it doesn't close and nothing locks (see below).
- In screen-saver mode the display is look-only: taps and swipes don't open panels. That matches today's screen-saver mode, where any input closes it.

## Managed from the app

On the app's Screens page, each PC with a launcher gets screen-saver settings that the PC applies within a minute, with nobody at it:

- **Screen saver on/off.** On means Windows' screen saver is set to the Shabbat Display.
- **Wait time** in minutes. This is Windows' own "Wait".
- **Lock when it closes.** This is Windows' "On resume, display logon screen".
- **Keep the screens on over Shabbat and Yom Tov.** This is a per-PC switch; Avi: "Shabbat is an app option". While the screen saver shows during Shabbat or Yom Tov (candle lighting to havdalah, from the server's calendar), it holds the screens on and the PC awake. The rest of the week, Windows' power settings apply as usual.

These replace the old screen-saver options for these PCs: "which monitor" goes (every screen joins in), "keep awake" becomes the Shabbat switch, and brightness dimming goes.

Avi never opens Control Panel. A helper on each PC writes these values into Windows' own per-user screen-saver settings and points Windows at the `.scr`. Today the launcher already asks `/api/screen-settings` every minute, and it can be that helper.

## Shabbat

The hard requirement comes from what already happened on Ariela's Acer. A modern-standby laptop turned its screens off 30 minutes after the screen saver opened, went to sleep, and locked on waking, so the display was dark all Shabbat. With the Shabbat switch on, the PC must still be awake and showing the display from candle lighting until havdalah, untouched. The screen saver must start, or already be showing, by candle lighting, even if the PC was left alone since Friday morning. If Windows' power plan would turn the screen off or sleep before the screen saver starts, setup or the helper deals with it; today's setup already offers to move the screen-off time.

### Over Shabbat and Yom Tov it doesn't close, and nothing locks

Windows doesn't run a screen saver while the PC sits at the lock screen. The lock screen turns the display off after about a minute. So a screen saver that closes on Shabbat with locking on means dark screens until havdalah. That could be a bumped desk, a drifting mouse or a child at the keyboard. It's the same failure the Acer had.

Avi agreed to this: over Shabbat and Yom Tov (candle lighting to havdalah, the same span as the page's `body.holy`), on a PC with the Shabbat switch on:

- **It doesn't close on touch.** Mouse movement, clicks and keys are ignored while it shows. Avi's words: "Doesn't kick over shabbat". *Reading that as "doesn't close" as well as "doesn't lock" is my interpretation.* Ctrl+Alt+Del still reaches Windows, which can't be blocked and shouldn't be.
- **The PC doesn't lock.** The helper turns "On resume, display logon screen" off at candle lighting and back to Avi's setting at havdalah. If the screen saver does close somehow, the desktop shows and the screen saver comes back by itself after the wait time.
- **Already locked at candle lighting** (Win+L on Friday): the screen saver can't show over the lock screen. The helper can't fix that, but setup and the app should make it unlikely; don't lock a PC on Erev Shabbat. The builder notes it in the app, next to the Shabbat switch.

The rest of the week everything behaves as Avi set it: any touch closes it, and Windows locks if locking is on.

## Checked before writing

- **Avi's Surface Studio:** the account is a local administrator. It isn't domain-joined, Entra-joined or MDM-enrolled (a work account is only added as "workplace joined"). There's no screen-saver policy, and today no screen saver is set.
- **Ariela's Acer:** it couldn't be checked on 2026-11-08 (no answer over Tailscale SSH). Check for admin rights and management before installing there.
- **The always-on PC** already holds the real `household.json`, `manage-key.txt` and settings; the app has managed it since 2026-11-07. Nothing moves from the Surface. The Surface stops starting `server.py` at sign-in (*my call*), and `start-display.bat`/running `server.py` by hand still works for development.

## Goals

- It behaves like any Windows screen saver: it's listed in Screen Saver Settings, Windows starts and closes it, and Windows locks.
- It's on every monitor, with different scenes.
- It's set entirely from the app.
- It survives Shabbat on the Acer.
- It's quick to close.

## Non-goals

- Any PC other than these two. The always-on PC stays always on, and the iPad stays a web page. Nothing should stop a third PC from using it later.
- Interaction inside the screen saver.
- A settings dialog in Windows (the `.scr` "Settings…" button). It can just say "Managed from the Shabbat Display Manager app".

## Anti-goals: a failure even if it works

- Changing brightness, display layout, resolution or any display setting.
- A close that takes more than a moment, or flashes a browser window, a taskbar or a "restore pages" bubble.
- A dark screen on Shabbat because the PC slept.
- Avi having to visit either PC or open Control Panel to change a setting.
- Showing the wrong house's data, preview data, or a blank white screen when the server can't be reached. Show the display's dark background with a clock and a quiet "Display not reachable" line instead (*my call*).

## Constraints (standing project rules)

- Python standard library only on the server; no CI or GitHub Actions.
- The access code and secrets never go to the screen saver: it reads the same public page and `/api/state` that any screen does.
- It checks in under its PC's screen name, like any screen, so it shows up on Status and Screens with its own rotation.
- It's installed with the existing tools: the Display Manager's build on Avi's PC, and `setup-windows.ps1` from the installer zip on Ariela's Acer. The zip is built with `git archive`, so a built `.scr` has to reach it some other way. That's left to the builder; Avi uploads the zip to avifrischlaw.com as today.
- Honest requests only; nothing about the existing sources changes.

## Left to the builder

- **How the `.scr` is built.** WebView2 is the obvious engine (it's already used by the app). The UI framework, .NET version and single-file packaging are the builder's call, but it must start fast; Windows also hands it a preview window (`/p`) and settings (`/c`).
- **How each screen gets a different scene.** For example, a page parameter that offsets where the rotation starts, so screen 2 is one scene ahead of screen 1.
- **How the launcher changes on these PCs.** It stops opening kiosk browsers there, and stops holding the PC awake when it shouldn't. A PC that holds the display on blocks Windows' screen saver from ever starting.
- **How Shabbat keep-awake is done.** For example, `SetThreadExecutionState` from the screen saver while it shows during Shabbat, plus whatever keeps the PC awake before it starts on Friday.
- **The server's screen settings shape**, and how the app shows these options in place of the old ones, keeping the rule that nothing changes on a PC until Avi saves it in the app.
- **Retiring the old launcher screen-saver mode.** Whether it goes entirely, and what happens to `brightness-before-saver.txt` on a PC that still has a dimmed panel.
