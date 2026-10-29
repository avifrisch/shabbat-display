# Touch and Click on the Permanent Display Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Avi tap (iPad) or click (mouse) headlines, the weather and game scores to open reading, forecast and box-score panels in the scene area, swipe between scenes, and have the display return to normal rotation on its own after 2 minutes, with all interaction off on Shabbat and Yom Tov.

**Architecture:** `server.py` gains three on-demand JSON endpoints (`/api/article`, `/api/game`, `/api/forecast`) and a radar image proxy (`/api/radar`), each behind a small in-memory TTL cache, plus one secret setting (`nyt_cookie`). `index.html` gains one interaction layer: event delegation on `data-tap` attributes, a panel element that covers the scene layers inside `.scene-wrap`, an idle timer, and swipe/key navigation. Nothing changes for an unattended display.

**Tech Stack:** Python 3 standard library (`http.server`, `urllib`, `html.parser`, `unittest`); a single inline-JS/CSS `index.html` (Safari 14.5+ compatible).

**Spec:** `docs/superpowers/specs/2026-10-29-interactive-display-design.md`

## Global Constraints

- Server: Python standard library only. Tests use `unittest`, nothing to pip install.
- On this PC `python` in PowerShell is the Store stub. Run Python as `C:\msys64\mingw64\bin\python.exe` (written `PY` below).
- `index.html` stays one file, inline CSS and JS, no build step, and must still render from `file://` with `makeDemo()` data, panels included.
- Safari on iPadOS 14.5+ must work. Nothing newer than Safari 14.5 without a fallback (no `structuredClone`, no `:has()`, no top-level `await`, no `Array.prototype.at`).
- Fixed 120 × 67.5 rem canvas. The left column and bottom band never move.
- Secrets (`nyt_cookie`, `agenda_ics`) are never logged, never in `/api/state`, never in any response or error text.
- Return to rotation after exactly **2 minutes** (120 000 ms) without touch, click or key.
- With no input at all, the display must behave exactly as it does today.
- Design language: `--bg #0D1726`, warm off-white text, gold `#E5BA5E`, sky blue for weather, serif (`--serif`) for headlines and article text.

## Review Focus

1. **Backup-feed links** (CNN and Times of Israel fall back to Google News, whose links are redirect pages): opening one must show the feed summary and "The full article couldn't be loaded", never an error or a blank panel. Pinned in Task 1 (`test_no_paragraphs_falls_back`).
2. **Expired or missing NYT cookie**: the NYT returns the first few paragraphs only. The panel must show them plus the "cut off" note with the refresh hint. Pinned in Task 1 (`test_nyt_short_article_marked_truncated`).
3. **The 20-second poll while a panel is open** must not repaint over the panel, reset its scroll, or advance the scene. Pinned in Task 4, step 6.
4. **Shabbat starting while a panel is open** (or someone tapping on Shabbat): the panel closes and nothing reacts. Pinned in Task 4, step 7.
5. **A game that hasn't started, was postponed, or an id that's no longer in today's data**: the box score shows probable pitchers and start time (Preview) or the status line (Postponed), and a non-numeric id gets a 404. Pinned in Task 2 (`test_preview_game_has_probables`, `test_game_route_rejects_non_numeric`).

---

## File Structure

- `server.py` (modify): new section `# ---------------------------------------------------------------- on demand` before `# ---------------------------------------------------------------- scheduler`, holding the cache helper, article, game and forecast code; new routes in `Handler.do_GET`; `nyt_cookie` in `CONFIG`.
- `tests/test_server.py` (create): `unittest` tests for the on-demand code. Imports `server` with `sys.path` set to the repo root.
- `tests/fixtures/` (create): `article_nyt.html`, `article_redirect.html`, `game_final.json`, `game_preview.json`, `openmeteo.json`, `airquality.json`, `nws_forecast.json`. Real responses, trimmed.
- `index.html` (modify): CSS block `/* ---------- interaction ---------- */` after the standings CSS; `<div class="panel" id="panel" hidden></div>` inside `.scene-wrap` after `#layerB`; JS section `// ------------------------------------------------------------------ interaction` before `// ------------------------------------------------------------------ misc`; panel renderers; demo data in `makeDemo()`.
- `settings.example.json`, `README.md`, `CLAUDE.md` (modify): documented in Task 8.

---

### Task 1: Article endpoint (server)

**Files:**
- Modify: `server.py` (`CONFIG`, new on-demand section, `Handler.do_GET`)
- Create: `tests/test_server.py`, `tests/fixtures/article_nyt.html`, `tests/fixtures/article_redirect.html`

**Interfaces:**
- Produces:
  - `CONFIG["nyt_cookie"] = ""` (string; either the `NYT-S` value alone or a whole `Cookie:` header value. If it contains `=`, send it as-is; otherwise send `NYT-S=<value>`).
  - `cached(key: str, ttl: float, fn: Callable[[], T]) -> T`: thread-safe in-memory TTL cache. Exceptions are not cached.
  - `ARTICLE_FEEDS = ("nyt", "cnn", "toi", "yankees_news", "mlb_news")`
  - `feed_item_for(url: str) -> dict | None`: the feed item whose `link` equals `url` in any of `ARTICLE_FEEDS` in `store`, else `None`.
  - `article_headers(url: str) -> dict`: request headers; includes `Cookie` only when the host is `nytimes.com` or ends with `.nytimes.com` and `nyt_cookie` is set.
  - `extract_article(page: str) -> list[str]`: paragraph texts.
  - `article_json(url: str) -> dict`: `{"ok": True, "title", "source", "time", "paragraphs": [...], "truncated": bool}` or `{"ok": False, "title", "source", "time", "summary", "message": "The full article couldn't be loaded."}`. Raises `LookupError` when `feed_item_for(url)` is `None`.
  - Route `GET /api/article?url=<urlencoded>` → 200 with `article_json`, or 404 `{"ok": false, "message": "not found"}` on `LookupError`.

- [ ] **Step 1: Save fixtures.** `article_nyt.html`: fetch one current NYT article URL from the `nyt` feed without a cookie and save it (it will be paywall-short). `article_redirect.html`: a page with a title and links but no `<p>` of 40+ characters (save a `news.google.com/rss/articles/...` link response).

- [ ] **Step 2: Write the failing tests** in `tests/test_server.py`:

```python
class ArticleTests(unittest.TestCase):
    def setUp(self):
        server.store.data["nyt"] = {"items": [{"title": "T", "summary": "S", "time": None,
                                               "link": "https://www.nytimes.com/2026/10/29/a.html", "source": "nyt"}]}
        server.CONFIG["nyt_cookie"] = "secret123"

    def test_unknown_url_rejected(self):
        with self.assertRaises(LookupError):
            server.article_json("https://evil.example/x")

    def test_cookie_only_for_nytimes(self):
        self.assertEqual(server.article_headers("https://www.nytimes.com/a")["Cookie"], "NYT-S=secret123")
        self.assertNotIn("Cookie", server.article_headers("https://www.cnn.com/a"))
        self.assertNotIn("Cookie", server.article_headers("https://nytimes.com.evil.example/a"))

    def test_extract_paragraphs(self):
        paras = server.extract_article(fixture("article_nyt.html"))
        self.assertGreaterEqual(len(paras), 1)
        self.assertTrue(all(len(p) >= 40 for p in paras))

    def test_no_paragraphs_falls_back(self):
        with mock.patch.object(server, "http_get_with", return_value=fixture("article_redirect.html")):
            j = server.article_json("https://www.nytimes.com/2026/10/29/a.html")
        self.assertFalse(j["ok"]); self.assertEqual(j["summary"], "S")
        self.assertEqual(j["message"], "The full article couldn't be loaded.")

    def test_nyt_short_article_marked_truncated(self):
        with mock.patch.object(server, "http_get_with", return_value="<article>" + "<p>%s</p>" % ("x" * 60) * 3 + "</article>"):
            self.assertTrue(server.article_json("https://www.nytimes.com/2026/10/29/a.html")["truncated"])

    def test_secret_not_in_error(self):
        with mock.patch.object(server, "http_get_with", side_effect=OSError("boom")):
            j = server.article_json("https://www.nytimes.com/2026/10/29/a.html")
        self.assertNotIn("secret123", json.dumps(j))
```

`fixture(name)` reads `tests/fixtures/<name>` as UTF-8. Each test class restores `CONFIG` and `store.data` in `tearDown`.

- [ ] **Step 3: Run to verify they fail**

Run: `PY -m unittest discover -s tests -v`
Expected: errors, `module 'server' has no attribute 'article_json'`.

- [ ] **Step 4: Implement** in `server.py`:
  - `http_get_with(url: str, headers: dict, timeout=15, limit=3_000_000) -> str`: like `http_get`, but with the given headers, reading at most `limit` bytes.
  - `extract_article`: an `html.parser.HTMLParser` subclass collecting the text of each `<p>` (whitespace-collapsed, `html.unescape`d). Prefer `<p>`s inside the first `<article>`, or for the NYT inside `<section name="articleBody">`. If none, use all `<p>`s in the page. Keep paragraphs of 40+ characters and drop exact duplicates. Skip `<p>`s inside `<script>`, `<style>`, `<nav>`, `<footer>`, `<aside>`, `<figure>`.
  - `article_json`: `cached("article:" + url, 600, ...)`. On any fetch or parse exception, or zero paragraphs, return the `ok: False` shape using the feed item's `summary`. `truncated` is true when the host is a NYT host and there are fewer than 5 paragraphs. Never put exception text or headers in the result. Log failures as `article: <host> failed` (host only, no path or query).
  - Route in `do_GET`: parse `url` from the query string with `urllib.parse.parse_qs`.

- [ ] **Step 5: Run to verify they pass**

Run: `PY -m unittest discover -s tests -v`
Expected: all `ArticleTests` OK.

- [ ] **Step 6: Live check.** Start `PY server.py`, wait 30 s, take the first `link` from `http://localhost:8765/api/state` → `data.cnn.items[0]`, then open `http://localhost:8765/api/article?url=<urlencoded link>`. Expected: `"ok": true` with several paragraphs. Do the same for `toi` and `yankees_news`. If one site comes back `ok: false` from its primary feed, add a site-specific container rule for it in `extract_article` and a fixture test, then repeat.

- [ ] **Step 7: Commit** `server.py tests/` with the message "Serve article text on demand for the reading panel".

---

### Task 2: Box score endpoint (server)

**Files:**
- Modify: `server.py` (on-demand section, `Handler.do_GET`)
- Modify: `tests/test_server.py`
- Create: `tests/fixtures/game_final.json`, `tests/fixtures/game_preview.json`

**Interfaces:**
- Consumes: `cached` (Task 1), `get_json`, `MLB`.
- Produces:
  - `norm_boxscore(feed: dict) -> dict`, where `feed` is `https://statsapi.mlb.com/api/v1.1/game/{pk}/feed/live`:
    ```
    {"id", "state": "Preview"|"Live"|"Final"|"Off", "detail", "start", "venue",
     "inning", "inning_state", "outs", "balls", "strikes", "bases": [b1, b2, b3],
     "innings": [{"num", "away": int|None, "home": int|None}],
     "decisions": {"w": "Rodón (14-8)", "l": ..., "s": ... or None},
     "homers": ["Judge (49)", ...],
     "away": TEAM, "home": TEAM}
    TEAM = {"abbr", "name", "r", "h", "e", "is_team": bool, "probable": str|None,
            "batters":  [{"name", "pos", "ab", "r", "h", "rbi", "bb", "k", "avg"}],
            "pitchers": [{"name", "note", "ip", "h", "er", "bb", "k", "era"}]}
    ```
    `state` follows `norm_game()`'s rule (Postponed/Cancelled/Suspended → `"Off"`). `batters` are in batting order with substitutes after the player they replaced. `note` is the decision letter (`W`, `L`, `S`, `H`, `BS`) or `""`. `is_team` is true for `CONFIG["team_id"]`.
  - `game_json(pk: int) -> dict`: `cached(f"game:{pk}", 25 if live else 600, ...)`. Live means the last result's `state == "Live"`; first fetch uses 25.
  - Route `GET /api/game?id=<digits>` → 200 `game_json`, or 404 when `id` isn't all digits or the MLB request fails with HTTP 404.

- [ ] **Step 1: Save fixtures.** `game_final.json`: the live feed of a recent completed Yankees game (any `team.last.id` from `/api/state`), trimmed to `gameData` (`status`, `datetime`, `venue`, `teams`, `probablePitchers`) and `liveData` (`linescore`, `boxscore`, `decisions`, `plays.allPlays` filtered to home runs). `game_preview.json`: the feed of `team.next.id`, trimmed the same way.

- [ ] **Step 2: Write the failing tests:**

```python
class GameTests(unittest.TestCase):
    def test_final_box(self):
        b = server.norm_boxscore(json.loads(fixture("game_final.json")))
        self.assertEqual(b["state"], "Final")
        self.assertGreaterEqual(len(b["innings"]), 9)
        self.assertEqual(sum(i["away"] or 0 for i in b["innings"]), b["away"]["r"])
        self.assertGreaterEqual(len(b["away"]["batters"]), 9)
        self.assertTrue(any(p["note"] == "W" for p in b["away"]["pitchers"] + b["home"]["pitchers"]))
        self.assertTrue(b["away"]["is_team"] or b["home"]["is_team"])

    def test_preview_game_has_probables(self):
        b = server.norm_boxscore(json.loads(fixture("game_preview.json")))
        self.assertEqual(b["state"], "Preview")
        self.assertEqual(b["away"]["batters"], [])
        self.assertIn("probable", b["home"])

    def test_game_route_rejects_non_numeric(self):
        self.assertIsNone(server.game_id_from_query("id=12ab"))
        self.assertEqual(server.game_id_from_query("id=778899"), 778899)
```

`game_id_from_query(query: str) -> int | None` is the route's parser.

- [ ] **Step 3: Run to verify they fail.** `PY -m unittest discover -s tests -v` → `GameTests` error, no attribute `norm_boxscore`.

- [ ] **Step 4: Implement** `norm_boxscore`, `game_json`, `game_id_from_query` and the route.

- [ ] **Step 5: Run to verify they pass.** Same command → all OK.

- [ ] **Step 6: Live check.** `http://localhost:8765/api/game?id=<team.last.id>` returns both teams' batters and pitchers. `http://localhost:8765/api/game?id=abc` returns 404.

- [ ] **Step 7: Commit** with the message "Serve box scores on demand".

---

### Task 3: Forecast endpoint and radar proxy (server)

**Files:**
- Modify: `server.py` (on-demand section, `Handler.do_GET`)
- Modify: `tests/test_server.py`
- Create: `tests/fixtures/openmeteo.json`, `tests/fixtures/airquality.json`, `tests/fixtures/nws_forecast.json`

**Interfaces:**
- Consumes: `cached`, `get_json`, `compass`, `_nws_forecast_url` (set by `fetch_nws_forecast`; look it up the same way if it's still `None`), `store.get("alerts")`, `store.get("calendar")`.
- Produces:
  - `RADAR_URL = "https://radar.weather.gov/ridge/standard/KOKX_loop.gif"`
  - `aqi_word(aqi: int | None) -> str`: 0–50 "Good", 51–100 "Moderate", 101–150 "Unhealthy for sensitive groups", 151–200 "Unhealthy", 201–300 "Very unhealthy", above that "Hazardous", `None` → "".
  - `pressure_trend(values: list[float]) -> str`: `"rising"` if the last value minus the value 3 entries earlier is ≥ 0.6 hPa, `"falling"` if ≤ −0.6, else `"steady"`.
  - `build_forecast(om: dict, aq: dict | None, nws: dict | None) -> dict`:
    ```
    {"now": {"temp", "feels", "humidity", "dew", "aqi", "aqi_word", "wind_mph", "wind_dir", "gust_mph",
             "uv", "pressure_inhg", "pressure_trend"},
     "hours": [48 x {"time", "temp", "precip", "amount_in", "code", "is_day"}],
     "days":  [7 x {"date", "hi", "lo", "code", "precip", "amount_in"}],
     "periods": [{"name", "start", "is_day", "short", "text"}],   # all NWS periods (about 14)
     "alerts": [... same shape as the alerts source ...],
     "marks":  [{"label": "Candles"|"Havdalah", "time"}]}         # from the calendar source, within the 48 hours
    ```
    `hours` starts at the current hour. `pressure_inhg` = hPa × 0.02953, rounded to 2 places. `amount_in` is inches (`precipitation_unit=inch`).
  - `forecast_json() -> dict`: `cached("forecast", 600, ...)`. The air-quality and NWS failures are tolerated (their parts come back `None` or empty). An Open-Meteo failure raises.
  - Routes: `GET /api/forecast` → 200 `forecast_json` or 503 `{"ok": false}`. `GET /api/radar` → 200 `image/gif` with bytes from `cached("radar", 300, ...)`, or 503.

- [ ] **Step 1: Save fixtures** from the live APIs: Open-Meteo (`current=temperature_2m,apparent_temperature,relative_humidity_2m,dew_point_2m,weather_code,wind_speed_10m,wind_direction_10m,wind_gusts_10m,uv_index,pressure_msl,is_day`, `hourly=temperature_2m,precipitation_probability,precipitation,weather_code,is_day,pressure_msl`, `daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum`, `temperature_unit=fahrenheit`, `wind_speed_unit=mph`, `precipitation_unit=inch`, `timezone=auto`, `forecast_days=8`), `https://air-quality-api.open-meteo.com/v1/air-quality?latitude=..&longitude=..&current=us_aqi`, and the NWS forecast URL.

- [ ] **Step 2: Write the failing tests:**

```python
class ForecastTests(unittest.TestCase):
    def test_aqi_word(self):
        self.assertEqual(server.aqi_word(32), "Good")
        self.assertEqual(server.aqi_word(51), "Moderate")
        self.assertEqual(server.aqi_word(None), "")

    def test_pressure_trend(self):
        self.assertEqual(server.pressure_trend([1015.0, 1014.6, 1014.2, 1013.9]), "falling")
        self.assertEqual(server.pressure_trend([1015.0, 1015.1, 1015.0, 1015.2]), "steady")

    def test_build_forecast_shape(self):
        f = server.build_forecast(json.loads(fixture("openmeteo.json")),
                                  json.loads(fixture("airquality.json")),
                                  json.loads(fixture("nws_forecast.json")))
        self.assertEqual(len(f["hours"]), 48)
        self.assertEqual(len(f["days"]), 7)
        self.assertGreaterEqual(len(f["periods"]), 10)
        self.assertIn(f["now"]["pressure_trend"], ("rising", "falling", "steady"))

    def test_build_forecast_without_extras(self):
        f = server.build_forecast(json.loads(fixture("openmeteo.json")), None, None)
        self.assertIsNone(f["now"]["aqi"]); self.assertEqual(f["periods"], [])
```

`build_forecast` reads "now" from the server clock. The test only checks counts, so a fixture captured today stays valid as long as the fixture has 8 days of hourly data. Pass `start` explicitly if you need to: `build_forecast(om, aq, nws, start=None)`, where `start` defaults to the current hour key.

- [ ] **Step 3: Run to verify they fail** → no attribute `aqi_word`.
- [ ] **Step 4: Implement** the functions and both routes.
- [ ] **Step 5: Run to verify they pass.**
- [ ] **Step 6: Live check.** `/api/forecast` has 48 hours, 7 days, ~14 periods. `/api/radar` shows a moving GIF in the browser.
- [ ] **Step 7: Commit** with the message "Serve a detailed forecast and the radar loop on demand".

---

### Task 4: Interaction layer (client)

**Files:**
- Modify: `index.html` (CSS, `.scene-wrap` markup, JS interaction section, `renderAll`, `tick`, `showScene`, `headlines`, the Israel and MLB list helpers, `gameCard`, `miniGame`, `renderChip`, `renderSide`)

**Interfaces:**
- Produces (JS globals later tasks use):
  - `const IDLE_MS = 120000` and `function idleMs(): number`, which returns `IDLE_MS` unless `?debug=1` is in the URL and `window.IDLE_MS_OVERRIDE` is set. Always use `idleMs()`, never `IDLE_MS` directly.
  - `function interactive(): boolean`: `!document.body.classList.contains("holy") && Q.get("saver") !== "1"`.
  - `const PANELS = {}`: the panel registry. Later tasks add `PANELS.article`, `PANELS.game` and `PANELS.forecast`, each `{load: (arg) => Promise<any>, render: (data, arg) => string, refreshMs?: number}`. In demo mode `load` resolves from `makeDemo()`'s `demo_panels`.
  - `function openPanel(kind: string, arg: object): void`: shows `#panel`, sets `panelOpen = {kind, arg}`, renders "Loading…", then `load`s and renders. A failed `load` renders `<div class="panel-msg">This couldn't be loaded right now.</div>`. If `refreshMs` is set, it re-loads and re-renders on that interval (keeping `scrollTop`) while still open.
  - `function closePanel(): void`
  - `function goScene(delta: number | string): void`: a number moves through `[...new Set(order)]`, a string jumps to that scene; it closes any panel, sets `sceneStart = Date.now()`, and calls `showScene(name, true)`.
  - Markup contract: tappable elements carry `data-tap="article"` with `data-key` (feed key) and `data-link` (escaped URL), or `data-tap="game"` with `data-id`, or `data-tap="forecast"`. Scene tabs carry `data-scene="<name>"`.

- [ ] **Step 1: Markup and CSS.** Add `#panel` inside `.scene-wrap` (`position:absolute; inset:0`, `--panel`-style background, `1px solid var(--line)` border, `1rem` radius, `overflow-y:auto`, `-webkit-overflow-scrolling:touch`). Inside it: a close button (`.panel-x`, top right, 3.2 rem hit area), the content, and a footer `.panel-count` ("Back to the display in 1:42"). `body.touchable [data-tap]` and `[data-scene]` get `cursor:pointer` and `:active { opacity:.6 }`. Without `body.touchable`, there's no visual change at all. Set `touch-action: pan-y` on `.scene-wrap`.

- [ ] **Step 2: Tag tappable elements.** Headline rows (`headlines()`, and the `li()` helpers in `sceneMLB`/`sceneIsrael`, and the Israel lead) get `data-tap="article" data-key data-link` when `it.link` is present. `gameCard` and `miniGame` get `data-tap="game" data-id="${g.id}"`. The chip gets `data-tap="game"` with the live game's id. `#wxnow`, `#nws`, `#hourly` and `#days` get `data-tap="forecast"` (static attributes in the markup). Scene tab spans in `showScene` get `data-scene`.

- [ ] **Step 3: Input handling** (one set of listeners on `document`, using Pointer Events; Safari 13+ has them):
  - Every `pointerdown`, `pointermove` with movement, `wheel` or `keydown` calls `touched()`. `touched()` does nothing unless `interactive()`. Otherwise it records `lastInput = Date.now()`, adds `body.touchable`, and for `pointerType === "mouse"` sets `body.style.cursor = "default"`.
  - A tap is a `pointerup` within 10 px and 500 ms of its `pointerdown`. On a tap: `.panel-x` → `closePanel()`; `[data-scene]` → `goScene(name)`; `[data-tap]` → `openPanel(kind, dataset)`; a tap on a day row inside the forecast panel is handled by Task 7.
  - A swipe is a `pointerup` that started inside `.scene-wrap` (or `.stage-head`), with |dx| ≥ 80 px and |dx| > 1.5 × |dy|. dx < 0 → `goScene(+1)`, dx > 0 → `goScene(-1)`. A mostly vertical drag over the panel scrolls it (set `scrollTop` from the drag for mouse; native scrolling for touch).
  - `ArrowRight` / `ArrowLeft` → `goScene(±1)`. `Escape` → `closePanel()`.
  - When not `interactive()`, all of the above do nothing.

- [ ] **Step 4: Idle timer and rotation pause.** In `tick()`: when `lastInput` is set and `Date.now() - lastInput >= IDLE_MS`, then `closePanel()`, clear `lastInput`, remove `body.touchable`, set `body.style.cursor = ""` (back to the stylesheet's `none`), and set `sceneStart = Date.now()`. While `panelOpen` or `lastInput` is set, `tick()` doesn't call `advance()`. The panel footer shows the remaining `IDLE_MS - (now - lastInput)` as `m:ss`.

- [ ] **Step 5: Polls don't disturb the panel.** In `renderAll()`, the `else` branch (`paint(front, current)`) still runs; the panel sits above the layers, so a repaint underneath doesn't touch it. The panel is never repainted by `renderAll`, only by `openPanel` and its own refresh timer. If `renderAll` finds `body.holy` while `panelOpen`, it calls `closePanel()`, clears `lastInput` and removes `body.touchable`.

- [ ] **Step 6: Verify the poll doesn't disturb an open panel.** Start the server. In Chrome at 1920×1080, open `http://localhost:8765/?scene=news&hold=1`, click the first NYT headline, scroll the panel down, and wait 45 s (two polls). Expected: the panel is still open at the same scroll position, the countdown keeps counting, and the stage title is unchanged. Run `document.getElementById("panel").scrollTop` before and after (equal).

- [ ] **Step 7: Verify holy mode turns interaction off.** Open `index.html` from the file (demo data) with `?at=<this Friday>T17:50` (after demo candle lighting at 17:38). Expected: `body.holy` is set, clicking a headline opens nothing, and `body.touchable` never appears. Then with `?at=<this Friday>T17:00`, open a panel, and run `offset += 50*60000; renderAll()` in the console. Expected: the panel closes.

- [ ] **Step 8: Verify swipe, keys and idle return.** Drag left across the stage with the mouse → next scene. Press `ArrowLeft` → previous scene. Click a tab → that scene. Reload with `&debug=1`, open a panel, and run `IDLE_MS_OVERRIDE = 5000` in the console. Wait 5 s → the panel closes, the cursor hides, and rotation resumes.

- [ ] **Step 9: Commit** with the message "Tap, click and swipe on the display, back to rotation after 2 minutes".

---

### Task 5: Article reading panel (client)

**Files:** Modify `index.html` (`PANELS.article`, CSS `.read`)

**Interfaces:**
- Consumes: `PANELS`, `openPanel` (Task 4); `/api/article` (Task 1).
- Produces: `PANELS.article = {load: ({link}) => fetch("/api/article?url=" + encodeURIComponent(link)).then(r => r.json()), render: (j, arg) => string}`

- [ ] **Step 1: Render.** Source label in caps with `rel(time)` ("NEW YORK TIMES · 2 HR AGO"; labels: nyt "New York Times", cnn "CNN", toi "Times of Israel", yankees_news "Yankees news", mlb_news "MLB news"). Headline at 2.6 rem in `--serif`, then paragraphs at 1.55 rem `--serif`, line-height 1.5, max width 60 rem. With `truncated`: after the text, `<p class="read-note">The rest of this article is for subscribers. To read it in full, refresh "nyt_cookie" in settings.json (see README).</p>`. With `ok: false`: the headline, the summary if there is one, and `<p class="read-note">The full article couldn't be loaded.</p>`.
- [ ] **Step 2: Verify.** With the server running, `?scene=news&hold=1`: click a CNN headline → full text. Click an NYT headline with no cookie → the first paragraphs plus the subscriber note. On the Israel scene → full text, or the summary and the note when the feed came from the Google News backup.
- [ ] **Step 3: Commit** with the message "Reading panel for headlines".

---

### Task 6: Box score panel (client)

**Files:** Modify `index.html` (`PANELS.game`, CSS `.box`)

**Interfaces:**
- Consumes: `PANELS` (Task 4); `/api/game` (Task 2); `diamond()`, `inningText`-style wording, `hmap`, `dayLabel`.
- Produces: `PANELS.game = {load: ({id}) => fetch("/api/game?id=" + id).then(...), render, refreshMs: 30000}`. The refresh is skipped (no fetch) unless the last result's `state === "Live"`.

- [ ] **Step 1: Render.** In order:
  - **Status line:** "Final" / "Top 7th · 2 outs" with `diamond(bases)` and outs dots when Live / "Postponed" / for Preview "Today 7:05 pm", then the venue.
  - **Line score:** innings, then R H E. The team with `is_team` is gold. Unplayed home ninth shows "x".
  - **Decisions and homers line.**
  - **Two columns,** away left and home right. Each has a batting table (Name Pos, AB R H RBI BB K AVG), then a pitching table (Name + note, IP H ER BB K ERA).
  - **Preview games:** the two probable pitchers and the start time instead of the tables.

  Tables use 1.15 rem tabular numbers so a nine-inning game fits in the stage at 1920×1080 without scrolling.
- [ ] **Step 2: Verify.** `?scene=yankees&hold=1`, click the last-game card: both teams' tables are visible without scrolling at 1920×1080, and at 1366×768 the panel scrolls. Click the next-game card: probable pitchers and start time.
- [ ] **Step 3: Commit** with the message "Box score panel".

---

### Task 7: Forecast panel (client)

**Files:** Modify `index.html` (`PANELS.forecast`, CSS `.fc`)

**Interfaces:**
- Consumes: `PANELS` (Task 4); `/api/forecast` and `/api/radar` (Task 3); `wxIcon`, `WX`, `hmap`.
- Produces: `PANELS.forecast = {load: () => fetch("/api/forecast").then(...), render, refreshMs: 600000}`; `function forecastGraph(hours, marks): string` (inline SVG).

- [ ] **Step 1: Render**, as in the approved mockup `boxscore-weather-v2.html`:
  - **Alerts** in full at the top, if any.
  - **Grid:** left column "Right now" (8 facts in a 4-column grid; air quality as "32 Good"; pressure with ↑, ↓ or →), then the 48-hour graph, then the 7-day list. Right column: the radar.
  - **Graph (`forecastGraph`):** `viewBox="0 0 480 140"`. Temperature as a gold smoothed path. Rain chance as sky-blue bars (`precip` %, scaled 0–100 to the bar area). The amount, as text above the tallest bar of each rainy stretch, when it's ≥ 0.05″. Hour labels every 6 hours, day names at midnight. Vertical dashed gold lines with labels for `marks`. Extreme temperatures labeled.
  - **Radar:** `<img src="/api/radar?t=<10-min bucket>">` with `onerror` swapping in "Radar unavailable", and a gold dot for Teaneck. Set its position as two constants `RADAR_X_PCT`, `RADAR_Y_PCT`: open the KOKX image, locate Teaneck (40.89 N, 74.02 W, just west of the Hudson across from upper Manhattan), and record its position as percentages of the image.
  - **7-day list:** like the left column's `.day` rows plus a precip amount column. Tapping a day row toggles that day's NWS `periods` (the day and its night, matched by `start` date) below it, in `--serif`.
- [ ] **Step 2: Verify.** Click the left column's weather: the panel shows all four parts at 1920×1080 without scrolling, and the radar animates. Tap Sunday → the NWS text for Sunday and Sunday night appears. Temporarily set `RADAR_URL` to `https://radar.weather.gov/ridge/standard/NOPE_loop.gif` and restart the server → the panel shows "Radar unavailable" and the rest still renders. Put `RADAR_URL` back.
- [ ] **Step 3: Commit** with the message "Detailed forecast panel with radar".

---

### Task 8: Demo data, screenshots and docs

**Files:** Modify `index.html` (`makeDemo()`), `settings.example.json`, `README.md`, `CLAUDE.md`

**Interfaces:**
- Consumes: `PANELS.*.render` shapes from Tasks 5–7 and the JSON shapes from Tasks 1–3.
- Produces: `makeDemo().demo_panels = {article: {...article_json shape}, game: {...norm_boxscore shape}, forecast: {...build_forecast shape}}`. `PANELS.*.load` returns these when `DEMO` is true. The radar image is replaced by a placeholder block when `DEMO`.

- [ ] **Step 1: Demo data.** Add `demo_panels`, with demo headlines carrying `link`s and demo games carrying `id`s so they're tappable from `file://`.
- [ ] **Step 2: Screenshots.** Open each panel from `file://.../index.html` and from the live server, at 1920×1080, 1366×768, 1440×900 and 1180×820 (iPad landscape). Expected: nothing overlaps the left column or the bottom band, the close button and countdown are visible, and long content scrolls.
- [ ] **Step 3: Docs.**
  - **`settings.example.json`:** add `"_nyt_help"` and `"nyt_cookie": ""`.
  - **README:** a "Tapping and swiping" section covering what's tappable, the 2-minute return, Shabbat behavior and mouse use, plus "Reading full NYT articles" steps: sign in at nytimes.com in Chrome or Edge, press F12, then Application → Cookies → https://www.nytimes.com → `NYT-S` → copy the Value into `"nyt_cookie"`, then restart the display. Mention that it lasts months and that the panel says when it has expired.
  - **CLAUDE.md:** replace "Nobody interacts with it, so there is no touch, mic, camera or motion input, and the display changes only on a schedule" with the new behavior. Add the four endpoints to the architecture list, the on-demand sources to the data table, `tests/` to Testing, and `nyt_cookie` to the secrets line.
- [ ] **Step 4: Full check.** `PY -m unittest discover -s tests -v` (all OK) and `PY server.py --check` (no new failures).
- [ ] **Step 5: Commit** with the message "Demo data and docs for the interactive panels".
