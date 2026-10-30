# Shul tab: Bnai Yeshurun davening times, bulletin and calendar

Date: 2026-10-30. Status: draft for Avi's approval.

## Why

Avi davens at Congregation Bnai Yeshurun (bnaiyeshurun.org, a ShulCloud site). The shul publishes:

- **Weekly davening chart**: a PNG on `/minyan`, Sunday–Friday, every minyan by room. The early Shacharit follows sunrise and the rest changes with the season, holidays and announcements, so it must be the shul's own chart, not times we compute.
- **Weekly bulletin** ("Weekly Shabbat Announcements"): a PDF, newest first on `/bulletin`. Page 2 has a "Shabbat Times / זמני שבת" box that is real text in the PDF: candle lighting, Friday Mincha minyanim, Shabbat morning minyanim, afternoon shiurim, Mincha, Maariv & Shabbat ends, next week's candle lighting.
- **Monthly calendar**: on `/monthlycalendar`, as a JPG and a PDF per month (the next month appears before the month starts).

He wants these on the display: weekly times on weekdays, Shabbat times on Shabbat, all in the normal rotation, because the display is mainly a passive news and sports screen.

## Goals

1. A new scene `shul` in the rotation.
   - **Weekdays** (not `body.holy`): the shul's weekly chart image, as large as the stage allows. Tap the chart → full-size chart in the panel. Two tap targets on the scene: "Calendar" (this month's calendar image in the panel; next month too if it has been posted) and "Bulletin" (the newest bulletin PDF).
   - **Shabbat and Yom Tov** (`body.holy`): the bulletin's Shabbat Times box rendered by the page in the display's own style (label, time, Hebrew label), no interaction. Normal rotation, normal dwell time.
2. The always-on machine fetches the three items itself on Fridays: starting 12:00 local time, once an hour, until it has a bulletin for this Shabbat, and stopping at candle lighting. Plus one fetch at server start if nothing is stored.
3. `update-shul.bat` / `update-shul.sh`: run the same fetch now and print what it got (e.g. `Davening: Oct25-weeklydavening.png · Bulletin: 24Oct-LechLecha.pdf · Calendar: October 2026, November 2026`).
4. Staleness is visible: if the stored bulletin is not for the coming/current Shabbat, or the chart is more than 7 days old, the scene says so in small text ("Bulletin from Lech Lecha — this week's not posted yet") instead of passing old times off as current.

## Non-goals

- No computed or rule-based minyan times. Only what the shul published.
- No OCR of the chart image. The weekday view shows the image.
- No parsing of the bulletin beyond the Shabbat Times box.
- No email reading, no Claude routine, no cloud anything.

## Anti-goals

- Never disguise the request. Every request sends `User-Agent: ShabbatDisplay/1.0 (personal home display)` and an ordinary `Accept`. If the site starts refusing that, the fetch fails, gets logged in `meta`, and the display keeps the last files. Do not change the User-Agent to a browser's to get around a refusal.
- Never more than the handful of requests per run (3 pages + at most 4 files, only files whose name changed), at most hourly, only on Fridays plus manual runs.
- Showing wrong times on Shabbat is worse than showing none. If the Shabbat Times box can't be parsed, show the Hebcal candle lighting and havdalah the display already has, plus "Shul times unavailable — see bulletin", not a guess.

## How it works (decided)

- **Server (`server.py`, stdlib only):** a `shul` entry in `SOURCES` with its own schedule (above), like the other source threads.
  - It reads `/minyan`, `/bulletin` and `/monthlycalendar` and takes:
    - the first `uploads/Weekly-Davening-Schedule/...png`;
    - the first `uploads/Bulletin/<year>/...pdf` on the bulletin page (newest is listed first);
    - every `uploads/Monthly-Calendars/...jpg` for this month and next.
  - Downloads only files whose URL changed since the last run, into `shul/` (gitignored), and keeps the previous ones until a new download succeeds.
  - Served at `/shul/<file>`. `/api/state` gets `shul: {chart, bulletin, calendars, shabbat_times, fetched}` where `shabbat_times` is a list of `{label, time, he}` plus `parsha` and the bulletin's date range.
- **PDF text:** a small stdlib reader (zlib + the PDF text operators + ToUnicode maps, which this bulletin uses) that pulls the Shabbat Times box text from page 2 and splits it into rows. The bulletin is made in Word and its layout repeats weekly; the parser keys on the "Shabbat Times" heading and stops at the parking notice or the end of the box.
- **`update-shul.bat` / `.sh`:** call `server.py --update-shul`, which runs one fetch and prints the result, then the running server picks up the new files on its next state build.
- **Page (`index.html`):** a `shul` scene with a weekday and a holy layout; `PANELS.shulimg` for the chart and calendar images; the bulletin opens in the panel in an `<iframe>` on the PC, and as a plain link (Safari's own PDF viewer) on a touch screen, because iPad Safari shows only the first page of an iframed PDF. `rotation_seconds.shul` defaults to 30.
- **Demo mode:** `makeDemo()` gets a made-up chart and Shabbat Times so the layout can be worked on with no server.

## Testing

- Unit tests (stdlib unittest) for: link picking from saved page HTML, "only download what changed", the Friday schedule (noon start, hourly, stop at candle lighting), the PDF text reader, and the Shabbat Times row parser, plus the "unparseable → fallback" path.
- Fixtures are **made-up** pages and a **made-up** PDF built by a test helper with the same structure (Word-style text objects, ToUnicode map, a Shabbat Times box), not copies of the shul's bulletin, which is their content.
- One manual check against the real current bulletin before shipping, with its rows compared to the PDF by eye.

## Left to the builder

- Exact scene layout, type sizes, and whether the weekday chart highlights today's column (only if it can be done reliably from the image's fixed layout; otherwise the whole chart).
- How "this Shabbat's bulletin" is recognized (date range in the file name or on page 1).
- How long the panel shows a calendar or bulletin (same 2-minute idle rule as other panels).

## Docs to update

CLAUDE.md (architecture, data-source table row, close open item 1 with what was decided and why), README (the tab and `update-shul`), `.gitignore` (`shul/`).
