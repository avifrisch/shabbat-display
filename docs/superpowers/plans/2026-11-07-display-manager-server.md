# Display Manager, part 1: server, page and launcher — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Everything the screens need for the Display Manager, built so that it works with no app at all. That means:
- household config with live reload;
- a management API behind an access code;
- per-screen rotations, with the agenda kept private;
- every major league as sports scenes;
- a business scene;
- launchers that take their mode from the server.

**Architecture:**
- `server.py` stays one stdlib file. It gains:
  - a `household.json` layer, read live and written only by the server;
  - `/api/manage/*` routes, checked against `manage-key.txt`;
  - one `SOURCES` thread per ESPN league, plus `markets` and two business feeds;
  - a `?screen=`-aware `/api/state`.
- `index.html` builds its rotation from the state, and renders every league from one normalized game shape.
- `launcher.pyw` polls `/api/screen-settings` every minute, caches the answer, and switches between always-on and screen saver without a restart.

**Tech Stack:** Python 3 standard library, plain HTML/JS, unittest, and Playwright for checking the page in demo mode.

**Spec:** `docs/superpowers/specs/2026-11-07-display-manager-design.md`. Part 2, the WinUI app, is `docs/superpowers/plans/2026-11-07-display-manager-app.md`. It consumes the API this plan produces.

## Global Constraints

- Python standard library only on the server and launcher. Nothing to pip install.
- No GitHub Actions or CI.
- Secrets are never logged, never sent to the page, and never returned by the management API (only `*_set: true/false`). The secrets are `nyt_cookie`, `agenda_ics` and the access code.
- Every new outside request uses `OWN_UA = "ShabbatDisplay/1.0 (personal home display)"`. Never a browser User-Agent.
  - The single exception is the SEC ticker list: `ShabbatDisplay/1.0 (personal home display; frischa@avifrischlaw.com)`. It goes to `www.sec.gov` only, at most weekly.
- A refusal or failure keeps the last good data and is recorded in `meta`. Never work around it.
- `settings.json` is never written by the server. `household.json` overrides it, value by value.
- Shabbat behavior (`holyState()`, `body.holy`, the shul fetch rules) is unchanged.
- Test command: `C:\msys64\mingw64\bin\python.exe -m unittest discover -s tests`. All tests must pass at every commit; the baseline is 94.
- Page checks: serve the repo with `C:\msys64\mingw64\bin\python.exe -m http.server 8799`. The page then runs in demo mode, because `/api/state` 404s.
  - Use Playwright at 1920×1080.
  - Screenshots go in `C:\ShabbatDisplay\.playwright-mcp\`; delete them afterwards.
- Commits end with the attribution lines from the session's system reminder.

## Review Focus

1. **A `household.json` that is corrupt or half-written** (power cut mid-save). The server keeps running on its last good copy, and on defaults if it has none. The display never goes blank, and nothing is overwritten without a log line. *Test: Task 1, `test_corrupt_household_keeps_last_good`.*
2. **A screen name that is odd, unknown or hostile** (`?screen=../x`, 300 characters, an emoji). It gets the house default. It is never stored when invalid, and never echoed unescaped. *Test: Task 3, `test_invalid_screen_name_gets_default_and_is_not_stored`.*
3. **ESPN games with missing pieces**: TBD opponents, no `linescores`, postponed games, a score as a string in one endpoint and an object in another. The game still normalizes, and nothing raises. *Test: Task 5, `test_norm_espn_game_tolerates_missing_fields`.*
4. **The server unreachable from a launcher, or `screen-settings.json` corrupt.** The launcher keeps its cached mode, else `settings.json`, else its startup flag. *Test: Task 9, `test_corrupt_cache_falls_back_to_settings`.*
5. **A secret leaking through the new routes.** No management response, state response or log line contains the secrets: a `nyt_cookie` set from the app, an `agenda_ics` URL, or the access code. *Test: Task 2, `test_manage_responses_never_contain_secrets`.*

---

### Task 1: Household config and access code

**Files:**
- Modify: `server.py`. Add a `# ---- household` section after `Store`.
- Modify: `.gitignore`. Add `household.json`, `household.json.tmp`, `manage-key.txt`, `screen-settings.json`, `sec-tickers.json`.
- Test: `tests/test_household.py` (new; reuse the `Isolated` pattern from `tests/test_server.py`).

**Interfaces:**
- Produces:
  - `HOUSEHOLD_FILE`, `KEY_FILE` (paths in `HERE`).
  - `LEAGUES`: an ordered dict of league key → `{"name", "sport", "path", "groups"}`. ESPN leagues only; MLB is separate.
  - `household() -> dict`: a deep copy of the current config. It reloads when the file's mtime changes, and migrates on first call when there's no file.
  - `save_household(h: dict) -> None`: an atomic write (`.tmp` then `os.replace`), under `_household_lock`.
  - `default_household() -> dict`.
  - `manage_key() -> str`: creates `manage-key.txt` with `secrets.token_urlsafe(24)` if it's missing.
  - `nyt_cookie() -> str`: the household secret if set, else `CONFIG["nyt_cookie"]`.
  - `SCENE_SECONDS_RANGE = (5, 300)`.

The `household.json` shape (version 1) is fixed here. Later tasks and the app rely on it:

```json
{
  "version": 1,
  "sports": {"mlb":  {"on": true,  "teams": [{"id": 147, "abbr": "NYY", "name": "New York Yankees"}], "favorite": 147},
             "nba":  {"on": false, "teams": [], "favorite": null}},
  "business": {"on": true, "watchlist": [{"symbol": "AAPL", "name": "Apple Inc."}], "news": {"biz_nyt": true, "biz_cnbc": true}},
  "default_rotation": [{"scene": "shul", "seconds": 30, "on": true}],
  "screens": {"DESKTOP-H72VKDJ": {"rotation": [{"scene": "agenda", "seconds": 25, "on": true}],
                                   "launcher": true, "saved": false,
                                   "mode": "always", "saver": {"minutes": 10, "lock": true, "screens": "all", "keep_awake": false},
                                   "local": null}},
  "secrets": {"nyt_cookie": ""}
}
```

- A screen's `"rotation": null` means it uses the house default.
- Teams and stocks are stored with their names, so the app and the page never need a lookup to label them.
- The default `LEAGUES` keys and ESPN paths:

  | Key | Name | ESPN path | Groups |
  |---|---|---|---|
  | `nba` | NBA | `basketball/nba` | |
  | `wnba` | WNBA | `basketball/wnba` | |
  | `nfl` | NFL | `football/nfl` | |
  | `nhl` | NHL | `hockey/nhl` | |
  | `mls` | MLS | `soccer/usa.1` | |
  | `ncaam` | Men's college basketball | `basketball/mens-college-basketball` | 50 |
  | `ncaaw` | Women's college basketball | `basketball/womens-college-basketball` | 50 |
  | `ncaaf` | College football | `football/college-football` | 80 |

- [ ] **Step 1: Write the failing tests** in `tests/test_household.py`. Each test patches `HOUSEHOLD_FILE` and `KEY_FILE` into a `tempfile.TemporaryDirectory()`, and resets `server._household_cache = None`.

```python
def test_migration_matches_todays_display(self):
    h = server.household()
    self.assertEqual(h["sports"]["mlb"], {"on": True, "teams": [{"id": 147, "abbr": "NYY", "name": "New York Yankees"}], "favorite": 147})
    self.assertEqual(h["business"]["watchlist"], [])
    self.assertTrue(all(not h["sports"][k]["on"] for k in server.LEAGUES))
    self.assertEqual([r["scene"] for r in h["default_rotation"]],
                     ["shul", "yankees", "mlb", "news", "israel", "business"])
    self.assertEqual(h["default_rotation"][0]["seconds"], 30)          # from CONFIG rotation_seconds
    self.assertNotIn("agenda", [r["scene"] for r in h["default_rotation"]])
    rot = h["screens"]["DESKTOP-H72VKDJ"]["rotation"]
    self.assertEqual(rot[0], {"scene": "agenda", "seconds": 25, "on": True})
    self.assertEqual(rot[1:], h["default_rotation"])
    self.assertTrue(os.path.exists(server.HOUSEHOLD_FILE))

def test_reload_on_change(self):
    h = server.household(); h["business"]["watchlist"] = [{"symbol": "AAPL", "name": "Apple Inc."}]; server.save_household(h)
    self.assertEqual(server.household()["business"]["watchlist"][0]["symbol"], "AAPL")

def test_corrupt_household_keeps_last_good(self):
    server.household()
    with open(server.HOUSEHOLD_FILE, "w") as f: f.write('{"version": 1, "spo')
    os.utime(server.HOUSEHOLD_FILE, (time.time() + 5, time.time() + 5))
    logged = []
    with mock.patch.object(server, "log", logged.append):
        self.assertTrue(server.household()["sports"]["mlb"]["on"])
    self.assertTrue(any("household.json" in m for m in logged))

def test_manage_key_created_once(self):
    k = server.manage_key()
    self.assertGreaterEqual(len(k), 30)
    self.assertEqual(server.manage_key(), k)

def test_nyt_cookie_household_overrides_settings(self):
    server.CONFIG["nyt_cookie"] = "from-settings"
    self.assertEqual(server.nyt_cookie(), "from-settings")
    h = server.household(); h["secrets"]["nyt_cookie"] = "from-app"; server.save_household(h)
    self.assertEqual(server.nyt_cookie(), "from-app")
```

- [ ] **Step 2: Run the tests and watch them fail.**
  - Run: `C:\msys64\mingw64\bin\python.exe -m unittest tests.test_household -v`
  - Expected: errors with `AttributeError: module 'server' has no attribute 'household'`.

- [ ] **Step 3: Implement the household section.**
  - `default_household()` reads `CONFIG["rotation_seconds"]` and `CONFIG["team_id"]`. Business gets 30 seconds.
  - `household()` keeps `_household_cache` and `_household_mtime`.
  - On a parse error it logs `household.json can't be read (<err>); using the last good copy` once per mtime, and returns the cache, or `default_household()` without writing when there's no cache.
  - Fill in missing top-level keys and missing leagues from `default_household()`, so a file written by an older version still loads.
  - Change `article_headers()` to use `nyt_cookie()` in place of `CONFIG["nyt_cookie"]`.
  - In `main()`, call `manage_key()` and `household()` before serving.

- [ ] **Step 4: Run the tests.**
  - Run: `C:\msys64\mingw64\bin\python.exe -m unittest tests.test_household -v`, then the full suite.
  - Expected: 5 new passes, and the full suite green.

- [ ] **Step 5: Commit**: `git add server.py .gitignore tests/test_household.py` with the message "Household config: household.json with live reload, migration from today's display, access code".

---

### Task 2: Management API

**Files:**
- Modify: `server.py`. Add a `# ---- management API` section before `Handler`, and add `do_POST` to `Handler`.
- Test: `tests/test_manage.py` (new). It uses a real `ThreadingHTTPServer` on port 0, like `RouteTests`.

**Interfaces:**
- Consumes (from Task 1): `household()`, `save_household()`, `manage_key()`, `LEAGUES`, `SCENE_SECONDS_RANGE`.
- Produces:
  - `manage_route(method: str, path: str, query: str, key: str|None, body: bytes) -> tuple[int, str]`. The status code, and a JSON string.
  - `scene_catalog() -> list[dict]`: `[{"scene", "label"}]` for every scene that can go in a rotation.
    - The built-in scenes are `agenda`, `shul`, `yankees`, `mlb`, `news`, `israel` and `business`.
    - Each league in `LEAGUES` adds two: `<key>_team` (label "<League> team") and `<key>` (label "Around the <League>").
  - `seen: dict[str, dict]`, in memory: screen name → `{"last": epoch, "launcher": bool}`. Task 3 fills it.
  - The routes. Every one needs the header `X-Manage-Key`, compared with `hmac.compare_digest`; without it the answer is 401 `{"ok": false, "error": "access code needed"}`. A bad body is 400 with a plain-English `error`.

| Method and path | Body / query | Answer |
|---|---|---|
| GET `/api/manage/status` | | `{"ok", "started", "feeds": {key: {"ok","updated","error","failed_at"}}, "shul": shul_status(), "screens": [{"name","last","launcher","mode","saved"}]}` |
| GET `/api/manage/household` | | the household without `secrets`, plus `"nyt_signed_in": bool`, `"agenda_set": bool`, `"leagues": LEAGUES names`, `"scenes": scene_catalog()` |
| POST `/api/manage/sports` | `{"<league or mlb>": {"on","teams":[{"id","abbr","name"}],"favorite": id or null}}`: at most 10 teams; favorite must be one of them | `{"ok": true}`. Switching a league on adds its pair to `default_rotation` (`on: true`, 30 s, before `business`) and to each custom rotation with `on: false`, if they aren't already there. |
| POST `/api/manage/business` | `{"on","watchlist":[{"symbol","name"}],"news":{...}}` | `{"ok": true}`. Symbols must match `^[A-Z][A-Z0-9.\-]{0,9}$`, at most 30 of them. |
| POST `/api/manage/rotation` | `{"screen": name or null, "rotation": [...] or null}` | `null` screen = the house default. `null` rotation = use the house default. Scenes must be in `scene_catalog()`, seconds within `SCENE_SECONDS_RANGE`. |
| POST `/api/manage/screen` | `{"name","mode":"always"/"saver","saver":{...}}` | Sets `saved: true`. `minutes` from 1 to 240, `screens` in `{"all","external"}`. |
| POST `/api/manage/nyt` | `{"cookie": "..."}` (`""` = sign out) | `{"ok": true, "nyt_signed_in": bool}` |
| POST `/api/manage/shul-update` | | the same as `/api/shul-update` (200, 409 or 503), plus `"shul": shul_status()` |
| GET `/api/manage/log` | `?lines=N` (at most 500) | `{"lines": [...]}`: the tail of `server.log` |
| POST `/api/manage/restart` | | `{"ok": true}`, then `os._exit(0)` from a timer 0.5 s later. The launcher restarts the server. |
| GET `/api/manage/teams` | `?league=nba&q=kni` | Task 6 |
| GET `/api/manage/stocks` | `?q=apple` | Task 7 |

`shul_status() -> dict` has this shape:
- `chart`: `{"file", "date", "this_week"}`.
- `bulletin`: `{"file", "date", "this_shabbat", "rows"}`. `rows` is None when the times couldn't be read.
- `calendars`: `[{"file", "this_month"}]`.
- `meta`: `{"ok", "updated", "error"}`.
- `problem`: None or one plain sentence. It's computed from the stored `shul` value with the same date rules as `shul_due()`/`upcoming_shabbat()`.

- [ ] **Step 1: Write the failing tests** in `tests/test_manage.py`. A helper `call(method, path, body=None, key=VALID)` returns `(status, json)`.

```python
def test_no_key_is_401(self):
    self.assertEqual(self.call("GET", "/api/manage/status", key=None)[0], 401)
    self.assertEqual(self.call("GET", "/api/manage/status", key="wrong")[0], 401)

def test_switching_a_league_on_adds_its_pair(self):
    self.call("POST", "/api/manage/rotation", {"screen": "Kitchen", "rotation": [{"scene": "news", "seconds": 30, "on": True}]})
    code, _ = self.call("POST", "/api/manage/sports", {"nba": {"on": True, "teams": [{"id": 18, "abbr": "NY", "name": "New York Knicks"}], "favorite": 18}})
    self.assertEqual(code, 200)
    h = server.household()
    names = [r["scene"] for r in h["default_rotation"]]
    self.assertLess(names.index("nba_team"), names.index("business"))
    kitchen = {r["scene"]: r["on"] for r in h["screens"]["Kitchen"]["rotation"]}
    self.assertEqual((kitchen["nba_team"], kitchen["nba"]), (False, False))

def test_bad_rotation_is_400(self):
    code, j = self.call("POST", "/api/manage/rotation", {"screen": None, "rotation": [{"scene": "nope", "seconds": 30, "on": True}]})
    self.assertEqual(code, 400); self.assertIn("nope", j["error"])
    code, _ = self.call("POST", "/api/manage/rotation", {"screen": None, "rotation": [{"scene": "news", "seconds": 2, "on": True}]})
    self.assertEqual(code, 400)

def test_bad_ticker_is_400(self):
    self.assertEqual(self.call("POST", "/api/manage/business", {"on": True, "watchlist": [{"symbol": "AAPL; rm", "name": "x"}], "news": {}})[0], 400)

def test_screen_save_marks_saved(self):
    self.call("POST", "/api/manage/screen", {"name": "Ariela", "mode": "saver", "saver": {"minutes": 15, "lock": True, "screens": "external", "keep_awake": True}})
    s = server.household()["screens"]["Ariela"]
    self.assertTrue(s["saved"]); self.assertEqual(s["mode"], "saver"); self.assertEqual(s["saver"]["minutes"], 15)

def test_manage_responses_never_contain_secrets(self):
    server.CONFIG["agenda_ics"] = ["https://example.com/feed/secret456.ics"]
    self.call("POST", "/api/manage/nyt", {"cookie": "secret123"})
    bodies = [json.dumps(self.call("GET", p)[1]) for p in ("/api/manage/status", "/api/manage/household", "/api/manage/log?lines=500")]
    for b in bodies:
        for s in ("secret123", "secret456", server.manage_key()):
            self.assertNotIn(s, b)
    j = self.call("GET", "/api/manage/household")[1]
    self.assertTrue(j["nyt_signed_in"]); self.assertTrue(j["agenda_set"])

def test_nyt_sign_out(self):
    self.call("POST", "/api/manage/nyt", {"cookie": "abc"})
    self.assertEqual(self.call("POST", "/api/manage/nyt", {"cookie": ""})[1]["nyt_signed_in"], False)
    self.assertEqual(server.nyt_cookie(), server.CONFIG["nyt_cookie"])

def test_shul_status_flags_unreadable_bulletin(self):
    server.store.data["shul"] = {"bulletin": {"file": "7Nov-ChayeiSarah.pdf", "shabbat": "2026-11-07", "times": None}, "chart": None, "calendars": []}
    with mock.patch.object(server, "now", return_value=datetime(2026, 11, 6, 14, 0).astimezone()):
        st = server.shul_status()
    self.assertIsNone(st["bulletin"]["rows"])
    self.assertIn("couldn't be read", st["problem"])
```

- [ ] **Step 2: Run them and watch them fail.**
  - Run: `C:\msys64\mingw64\bin\python.exe -m unittest tests.test_manage -v`
  - Expected: FAIL. The routes 404, and `shul_status` doesn't exist.

- [ ] **Step 3: Implement `manage_route`, `scene_catalog`, `shul_status` and `log_tail(n)`.**
  - `Handler.do_GET` sends `/api/manage/*` to `manage_route`. The new `do_POST` reads `Content-Length` (cap 64 KB, else 413) and does the same.
  - `started` is set in `main()`.
  - Each write is read-modify-write under `_household_lock` (household() → change → `save_household`).

- [ ] **Step 4: Run the tests.** `tests.test_manage`, then the full suite. Expected: all pass.

- [ ] **Step 5: Commit** with the message "Management API: access code, sports/business/rotation/screen/NYT/shul/log/restart routes".

---

### Task 3: Screens: check-in, launcher settings, per-screen rotation, private agenda

**Files:**
- Modify: `server.py`. `state_json()` gets a `screen` argument. Add `screen_settings_route()` and change the `/api/state` routing.
- Test: `tests/test_screens.py` (new).

**Interfaces:**
- Consumes: `household()`, `save_household()`, `seen`.
- Produces:
  - `valid_screen(name: str) -> bool`: `^[A-Za-z0-9][A-Za-z0-9 ._'-]{0,39}$`.
  - `check_in(name: str, launcher: bool, local: dict|None) -> None`. It updates `seen`. An unknown valid name is added to `household()["screens"]` with `rotation: null`, `saved: false` and `local`, and that's saved once. While `saved` is false, a launcher's `local` is replaced on each check-in.
  - `effective_rotation(name: str|None) -> list[dict]`: the screen's `on` items in order, else the house default's `on` items.
  - `state_json(screen: str|None = None) -> str`. Its `config` gains these keys:
    - `rotation` (`[{"scene","seconds"}]`);
    - `screen` (the name, or null);
    - `sports` (`{league: {"name","favorite_abbr","favorite_name","teams":[ids]}}` for leagues switched on, including `mlb`; names come from the stored team objects);
    - `business_news` (`{"biz_nyt": bool, "biz_cnbc": bool}`).

    `data.agenda` is dropped when `agenda` isn't in `effective_rotation(screen)`.
  - `GET /api/screen-settings?screen=NAME&mode=saver&minutes=10&lock=1&screens=external&awake=1`. No key is needed. It records the check-in (`launcher=True`, with `local` from the query), and answers `{"ok": true, "screen": name, "mode", "saver": {...}, "saved": bool}`.
    - Values come from the household when `saved`, else they echo `local`.
    - An invalid name is 400.
- The `/api/state?screen=NAME` route calls `check_in(name, False, None)` when the name is valid.

- [ ] **Step 1: Write the failing tests.**

```python
def test_unknown_screen_registers_with_house_default(self):
    s = json.loads(server.state_json("Kitchen iPad"))
    self.assertEqual([r["scene"] for r in s["config"]["rotation"]][:2], ["shul", "yankees"])
    self.assertIn("Kitchen iPad", server.household()["screens"])

def test_agenda_only_on_screens_that_have_it(self):
    server.store.data["agenda"] = {"days": [{"date": "2026-11-09", "events": [{"title": "Smith deposition"}]}]}
    self.assertNotIn("agenda", json.loads(server.state_json("Kitchen iPad"))["data"])
    self.assertNotIn("agenda", json.loads(server.state_json(None))["data"])
    self.assertIn("agenda", json.loads(server.state_json("DESKTOP-H72VKDJ"))["data"])

def test_invalid_screen_name_gets_default_and_is_not_stored(self):
    for bad in ("../x", "x" * 300, "<script>", "\U0001F600"):
        s = json.loads(server.state_json(bad))
        self.assertIsNone(s["config"]["screen"])
        self.assertNotIn(bad, server.household()["screens"])

def test_launcher_first_checkin_echoes_its_own_settings(self):
    code, j = self.get("/api/screen-settings?screen=Ariela&mode=saver&minutes=10&lock=1&screens=external&awake=1")
    self.assertEqual(code, 200)
    self.assertEqual((j["mode"], j["saver"]["screens"], j["saver"]["keep_awake"], j["saved"]), ("saver", "external", True, False))

def test_saved_settings_win_over_local(self):
    self.get("/api/screen-settings?screen=Ariela&mode=saver&minutes=10&lock=1&screens=all&awake=0")
    h = server.household(); h["screens"]["Ariela"].update(saved=True, mode="always"); server.save_household(h)
    self.assertEqual(self.get("/api/screen-settings?screen=Ariela&mode=saver&minutes=10&lock=1&screens=all&awake=0")[1]["mode"], "always")

def test_screen_settings_has_nothing_secret(self):
    server.CONFIG["agenda_ics"] = ["https://example.com/secret456.ics"]
    code, j = self.get("/api/screen-settings?screen=Ariela&mode=always")
    self.assertNotIn("secret456", json.dumps(j)); self.assertNotIn("rotation", j)
```

- [ ] **Step 2: Run them and watch them fail.** `tests.test_screens`. Expected: FAIL (`state_json()` takes no arguments).

- [ ] **Step 3: Implement it as specified above.**
  - The existing `test_state_has_no_secrets` must stay green.
  - Keep `config.rotation_seconds` in the state, so a page still cached in a browser works until it reloads.

- [ ] **Step 4: Run the tests.** The new file, then the full suite. Expected: green.

- [ ] **Step 5: Commit** with the message "Screens: per-screen rotation in /api/state, launcher settings endpoint, agenda only where chosen".

---

### Task 4: MLB from the household (favorite and other teams)

**Files:**
- Modify: `server.py` (`fetch_team`, `fetch_standings`, `team_poll_seconds`).
- Test: `tests/test_mlb_household.py` (new).

**Interfaces:**
- Consumes: `household()["sports"]["mlb"]`.
- Produces:
  - `mlb_team_info(team_id: int) -> dict`: `{"id", "abbr", "name", "division_id", "division_name", "league_id"}` from `GET {MLB}/teams/{id}?hydrate=division`. Cached for 7 days with `cached()`.
  - `mlb_favorite() -> dict`: the info for `household()["sports"]["mlb"]["favorite"]`, falling back to `CONFIG`'s Yankees values when it's missing or the lookup fails.
- `fetch_team()` and `fetch_standings()` use `mlb_favorite()` in place of `CONFIG["team_id"]`, `division_id` and `league_id`.
- The state's `config.team_abbr` and `config.division_name` come from `mlb_favorite()`.
- With MLB switched off, `fetch_team` returns `{"off": True}` and the team and mlb scenes leave the rotation (Task 8 on the page).
- The scene key stays `yankees`, so old `?scene=yankees` links keep working; its tab label becomes the favorite's name.

- [ ] **Step 1: Write the failing tests.** Patch `get_json` with a fake that returns `{"teams": [{"id": 121, "abbreviation": "NYM", "teamName": "Mets", "division": {"id": 204, "name": "National League East"}, "league": {"id": 104}}]}` for `/teams/121`.

```python
def test_favorite_comes_from_household(self):
    h = server.household(); h["sports"]["mlb"]["favorite"] = 121; h["sports"]["mlb"]["teams"] = [{"id": 121, "abbr": "NYM", "name": "New York Mets"}]; server.save_household(h)
    self.assertEqual(server.mlb_favorite()["division_id"], 204)

def test_lookup_failure_falls_back_to_yankees(self):
    with mock.patch.object(server, "get_json", side_effect=OSError("down")):
        self.assertEqual(server.mlb_favorite()["id"], 147)

def test_mlb_off(self):
    h = server.household(); h["sports"]["mlb"]["on"] = False; server.save_household(h)
    self.assertEqual(server.fetch_team(), {"off": True})
```

- [ ] **Step 2: Run them and watch them fail.** Expected: `AttributeError: mlb_favorite`.
- [ ] **Step 3: Implement it as specified.**
- [ ] **Step 4: Run the tests.** The new file and the full suite: green.
- [ ] **Step 5: Commit** with the message "MLB: favorite team and division from household.json".

---

### Task 5: ESPN leagues source

**Files:**
- Modify: `server.py`. Add a `# ---- other leagues (ESPN)` section after the MLB code, and add entries to `SOURCES`.
- Modify: `http_get(url, accept="*/*", timeout=20, ua=UA)`. Add the `ua` parameter, and define `OWN_UA = SHUL_UA`. Move the `SHUL_UA` definition up to the helpers.
- Test: `tests/test_espn.py` (new). It uses hand-built dicts in ESPN's structure, built by a helper `espn_event(...)` in the test file.

**Interfaces:**
- Consumes: `LEAGUES`, `household()`, `cached()`, `parse_dt`, `now`, `clean_text`.
- Produces:
  - `ESPN = "https://site.api.espn.com/apis"`. The URLs:
    - scoreboard: `{ESPN}/site/v2/sports/{path}/scoreboard[?dates=YYYYMMDD][&groups=G]`
    - schedule: `{ESPN}/site/v2/sports/{path}/teams/{id}/schedule`
    - standings: `{ESPN}/v2/sports/{path}/standings`
    - news: `{ESPN}/site/v2/sports/{path}/news[?team=ID]`

    A date range in `dates=` answers 400 (checked 2026-11-07), so ask for one day at a time.
  - `norm_espn_game(ev: dict, chosen: set[int]) -> dict`. The page's game shape:
    - top level: `{"id", "start", "state", "detail", "period", "clock", "venue", "away", "home", "chosen": bool}`;
    - each side: `{"id", "abbr", "name", "full", "score", "record", "winner", "lines": [numbers]}`.
    - `state` maps `pre`→`Preview`, `in`→`Live`, `post`→`Final`. `status.type.name` containing `POSTPONED`, `CANCELED` or `SUSPENDED` → `Off`.
    - `detail` = `status.type.shortDetail`.
    - `score` is an int when the event has one. It may come as `"102"` or `{"value": 102.0, "displayValue": "102"}`; otherwise None.
    - `name` = `shortDisplayName`, `full` = `displayName`, `record` = `records[0].summary`.
  - `espn_in_season(calendar: list, today: date) -> bool`. True if a calendar day (a string date) or a week entry (a dict with `startDate`/`endDate`, nested under `entries`, whose label isn't "Off Season") falls in `[today-3, today+7]`.
  - `norm_espn_standings(j: dict, sport: str, favorite: int|None) -> dict|None`: `{"group", "cols": [...], "rows": [{"abbr","name","vals":[...],"is_team"}]}`.
    - It uses the deepest group whose `standings.entries` contains the favorite, else the first group.
    - Columns:
      - basketball: W L GB Strk (`wins`, `losses`, `gamesBehind`, `streak`)
      - football: W L T Strk (`wins`, `losses`, `ties`, `streak`)
      - hockey: W L OTL PTS (`wins`, `losses`, `otLosses`, `points`)
      - soccer: W D L PTS (`wins`, `ties`, `losses`, `points`)
    - Each value is the stat's `displayValue`. Rows are in the order given.
  - `fetch_league(key: str) -> dict`, which returns one of:
    - `{"off": True}` when the league isn't switched on;
    - `{"on": True, "in_season": bool, "team": {"live","last","next","recent"} or None, "scores": {"label": "Today"/"Yesterday", "games": [...]}, "standings": ... or None, "team_news": {"items"}, "news": {"items"}}`.

    The requests, and how often each is made:
    - The scoreboard is one request; with no games today, also yesterday's.
    - The schedule is one request per chosen team. The favorite gives `team`, and the other chosen teams' games from today are merged into `scores.games`. Chosen-team games sort first, then Live, Preview, Final.
    - Standings are cached for 1 h.
    - The favorite's news and the league news are cached for 15 min. Items are `{"title", "summary", "link", "time"}` from `headline`, `description`, `links.web.href` and `published`.
  - `league_poll_seconds(key) -> int`:
    - 600 when off;
    - 30 when a chosen team's game is Live or starts within 15 minutes;
    - 3600 when out of season;
    - otherwise 180.
  - `SOURCES` gains `("sport_" + key, fetcher, poll)` for every key in `LEAGUES`.
    - One thread runs per league whether it's on or off. A switched-off league costs nothing but a sleep, so a league switched on in the app starts within 10 minutes and needs no restart.
    - `check()` prints `off` for leagues that are switched off.
- `ARTICLE_FEEDS` lookup: `feed_item_for(url)` also searches the `news` and `team_news` items of every `sport_*` value, with source name "ESPN". `article_headers()` sends `OWN_UA` to espn.com.

- [ ] **Step 1: Write the failing tests.**

```python
def test_norm_espn_live_game(self):
    g = server.norm_espn_game(espn_event(state="in", short="Q3 4:12", period=3, clock="4:12",
                                         away=("NYK", 18, "Knicks", "88", [30, 28, 30]), home=("BOS", 2, "Celtics", "80", [20, 30, 30])), {18})
    self.assertEqual((g["state"], g["detail"], g["away"]["score"], g["away"]["lines"], g["chosen"]), ("Live", "Q3 4:12", 88, [30, 28, 30], True))

def test_score_object_form(self):
    ev = espn_event(state="post", away=("NYK", 18, "Knicks", {"value": 102.0, "displayValue": "102"}, []), home=("BOS", 2, "Celtics", "99", []))
    self.assertEqual(server.norm_espn_game(ev, set())["away"]["score"], 102)

def test_norm_espn_game_tolerates_missing_fields(self):
    ev = espn_event(state="pre", away=("TBD", None, "TBD", None, None), home=("BOS", 2, "Celtics", None, None))
    del ev["competitions"][0]["venue"]; ev["status"]["type"]["name"] = "STATUS_POSTPONED"
    g = server.norm_espn_game(ev, set())
    self.assertEqual((g["state"], g["away"]["score"], g["away"]["lines"], g["venue"]), ("Off", None, [], None))

def test_in_season_by_days(self):
    self.assertTrue(server.espn_in_season(["2026-11-05T07:00Z", "2027-04-11T07:00Z"], date(2026, 11, 7)))
    self.assertFalse(server.espn_in_season(["2026-10-31T07:00Z"], date(2026, 11, 7)))   # WNBA after its finals

def test_in_season_by_weeks_skips_off_season(self):
    cal = [{"label": "Regular Season", "entries": [{"startDate": "2026-11-04T08:00Z", "endDate": "2026-11-11T07:59Z"}]},
           {"label": "Off Season", "entries": [{"startDate": "2027-02-16T08:00Z", "endDate": "2027-07-31T07:59Z"}]}]
    self.assertTrue(server.espn_in_season(cal, date(2026, 11, 7)))
    self.assertFalse(server.espn_in_season(cal, date(2027, 3, 1)))

def test_standings_pick_favorites_group(self):
    st = server.norm_espn_standings(espn_standings(), "hockey", favorite=18)
    self.assertEqual(st["cols"], ["W", "L", "OTL", "PTS"])
    self.assertTrue(next(r for r in st["rows"] if r["is_team"])["abbr"] == "NYR")

def test_league_off_makes_no_requests(self):
    with mock.patch.object(server, "http_get", side_effect=AssertionError("fetched")):
        self.assertEqual(server.fetch_league("nba"), {"off": True})

def test_espn_requests_use_own_user_agent(self):
    seen = []
    def fake(url, accept="*/*", timeout=20, ua=server.UA): seen.append(ua); return json.dumps({"events": [], "leagues": [{"calendar": []}]})
    h = server.household(); h["sports"]["nba"] = {"on": True, "teams": [], "favorite": None}; server.save_household(h)
    with mock.patch.object(server, "http_get", fake):
        server.fetch_league("nba")
    self.assertTrue(seen and all(u == server.OWN_UA for u in seen))
```

- [ ] **Step 2: Run them and watch them fail.** `tests.test_espn`. Expected: `AttributeError: norm_espn_game`.

- [ ] **Step 3: Implement the section.**

- [ ] **Step 4: Run the tests.** The new file and the full suite: green.

- [ ] **Step 5: Live check.** This is a real request, with the honest UA.
  - Turn NBA on in a scratch `household.json` copy (patch `HOUSEHOLD_FILE` in a one-off script in the scratchpad), then call `fetch_league("nba")`.
  - Expected:
    - `in_season: True`;
    - `scores.games` has entries, each with `lines`;
    - `standings.cols == ["W","L","GB","Strk"]`;
    - news items have `link`s.
  - Do the same for `ncaaf`: expect `in_season: True` in November.

- [ ] **Step 6: Commit** with the message "Sports: every major league from ESPN's public API, with honest User-Agent and off-season detection".

---

### Task 6: Team search

**Files:**
- Modify: `server.py` (the management API section).
- Test: `tests/test_manage.py` (add to it).

**Interfaces:**
- Consumes: `LEAGUES`, `cached()`, `OWN_UA`.
- Produces:
  - `league_teams(league: str) -> list[dict]`: `[{"id": int, "abbr", "name"}]`, sorted by name.
    - ESPN: `{ESPN}/site/v2/sports/{path}/teams?limit=1000`, using `sports[0].leagues[0].teams[].team`. `name` = `displayName`.
    - MLB: `{MLB}/teams?sportId=1`. The `name` is the team's `name`.
    - Cached for 7 days.
  - `team_search(league: str, q: str) -> list[dict]`: case-insensitive, at most 20 results. Prefix matches on abbr or name word come first, then substring matches. An empty `q` returns the first 20.
  - Route: `GET /api/manage/teams?league=<key|mlb>&q=...`. An unknown league is 400.

- [ ] **Step 1: Write the failing test.** Patch `league_teams` to return `[{"id": 18, "abbr": "NY", "name": "New York Knicks"}, {"id": 17, "abbr": "BKN", "name": "Brooklyn Nets"}, {"id": 2, "abbr": "BOS", "name": "Boston Celtics"}]`.

```python
def test_team_search(self):
    self.assertEqual([t["id"] for t in server.team_search("nba", "kni")], [18])
    self.assertEqual([t["id"] for t in server.team_search("nba", "n")], [17, 18])   # prefix on a word: Nets, New York
    self.assertEqual(self.call("GET", "/api/manage/teams?league=xfl&q=a")[0], 400)
```

- [ ] **Step 2: Run it and watch it fail.**
- [ ] **Step 3: Implement it as specified.**
- [ ] **Step 4: Run the full suite.**
- [ ] **Step 5: Commit** with the message "Management API: team search for every league".

---

### Task 7: Markets, business news, ticker search

**Files:**
- Modify: `server.py`. Add a `# ---- business` section, plus `FEEDS` additions and `SOURCES` entries.
- Test: `tests/test_business.py` (new).

**Interfaces:**
- Consumes: `household()["business"]`, `parse_feed()`, `feed_fetcher()`, `cached()`, `OWN_UA`.
- Produces:
  - Feeds:
    - `FEEDS["biz_nyt"] = ["https://rss.nytimes.com/services/xml/rss/nyt/Business.xml"]`
    - `FEEDS["biz_cnbc"] = ["https://www.cnbc.com/id/10001147/device/rss/rss.html"]`

    Both are in `ARTICLE_FEEDS`; `ARTICLE_SOURCES` names them "New York Times" and "CNBC". `feed_fetcher()` gets an optional `ua` argument; these two use `OWN_UA`. Both answered 200 on 2026-11-07.
  - `INDICES = [("SPX", "S&P 500", ".SPX", "^GSPC"), ("DJI", "Dow Jones", ".DJI", "^DJI"), ("IXIC", "Nasdaq", ".IXIC", "^IXIC")]`. Each tuple is (our symbol, name, CNBC symbol, Yahoo symbol).
  - `cnbc_quotes(symbols: list[str]) -> dict[str, dict]`.
    - The request: `https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols=<|-joined>&requestMethod=itv&noform=1&output=json`.
    - It reads `FormattedQuoteResult.FormattedQuote[]` fields `symbol`, `shortName`/`name`, `last`, `change`, `change_pct` and `last_time`. `code != 0` means not found.
    - Numbers are parsed from strings like `"7,376.86"`, `"+23.13"` and `"+0.31%"`.
    - It returns `{cnbc_symbol: {"last", "change", "pct", "name", "time"}}`.
  - `yahoo_quote(symbol: str) -> dict`: the fallback, one symbol per call.
    - The request: `https://query1.finance.yahoo.com/v8/finance/chart/<urlquoted>?range=1d&interval=1d`.
    - `last` = `meta.regularMarketPrice`, and change is computed against `meta.chartPreviousClose`.
    - Yahoo writes share classes with a dash, so `BRK.B` becomes `BRK-B`.
  - `fetch_markets() -> dict`:
    - The shape: `{"indices": [{"symbol","name","last","change","pct"}], "watch": [{"symbol","name","last","change","pct"}], "as_of": iso, "source": "CNBC"|"Yahoo", "market": "open"|"closed", "missing": [symbols]}`.
    - It makes one CNBC request for the indices plus the watchlist. Anything CNBC lacks goes to Yahoo. If both fail for every symbol it raises, so the store keeps the last good copy.
    - With business off it returns `{"off": True}`.
  - `market_wait(n: datetime, last_as_of: datetime|None) -> int`, in local time (the house is on Eastern):
    - weekdays from 9:30 to 16:00: 300;
    - after 16:00 on a weekday, while `last_as_of` is before 16:05 that day: 300;
    - otherwise the seconds until the next weekday 9:30, plus 60 s.

    Market holidays aren't tracked; a holiday just fetches unchanged quotes.
  - `SOURCES` gains:
    - `("markets", fetch_markets, markets_poll)`, where `markets_poll()` calls `market_wait(now(), stored as_of)`;
    - `("biz_nyt", feed_fetcher("biz_nyt", ua=OWN_UA), 900)`;
    - `("biz_cnbc", ..., 900)`.
  - `SEC_UA = "ShabbatDisplay/1.0 (personal home display; frischa@avifrischlaw.com)"`.
  - `SEC_FILE = os.path.join(HERE, "sec-tickers.json")`.
  - `sec_tickers() -> list[dict]`: `[{"symbol","name"}]` from `https://www.sec.gov/files/company_tickers.json` (values have `ticker` and `title`).
    - It downloads only when `SEC_FILE` is missing or older than 7 days, and only from a stock search, never at startup.
    - On failure it uses the old file, else returns `[]`.
    - Use `http_get(url, ua=SEC_UA)`. This is the only place `SEC_UA` appears.
  - `stock_search(q: str) -> list[dict]`: at most 15 results. An exact ticker comes first, then ticker prefixes, then name words.
  - Route: `GET /api/manage/stocks?q=...`.

- [ ] **Step 1: Write the failing tests.**

```python
def test_cnbc_numbers(self):
    body = json.dumps({"FormattedQuoteResult": {"FormattedQuote": [
        {"symbol": ".SPX", "shortName": "S&P 500", "last": "7,376.86", "change": "+23.13", "change_pct": "+0.31%", "last_time": "2026-11-06", "code": 0},
        {"symbol": "ZZZZ", "code": 1}]}})
    with mock.patch.object(server, "http_get", return_value=body):
        q = server.cnbc_quotes([".SPX", "ZZZZ"])
    self.assertEqual(q[".SPX"]["last"], 7376.86); self.assertEqual(q[".SPX"]["pct"], 0.31); self.assertNotIn("ZZZZ", q)

def test_missing_symbols_fall_back_to_yahoo(self):
    h = server.household(); h["business"]["watchlist"] = [{"symbol": "AAPL", "name": "Apple Inc."}]; server.save_household(h)
    with mock.patch.object(server, "cnbc_quotes", return_value={}), \
         mock.patch.object(server, "yahoo_quote", return_value={"last": 10.0, "change": 1.0, "pct": 11.1, "name": "X", "time": None}):
        m = server.fetch_markets()
    self.assertEqual(m["source"], "Yahoo"); self.assertEqual(m["watch"][0]["symbol"], "AAPL")

def test_market_wait(self):
    mon_open = datetime(2026, 11, 9, 10, 0).astimezone()
    self.assertEqual(server.market_wait(mon_open, None), 300)
    after = datetime(2026, 11, 9, 16, 30).astimezone()
    self.assertEqual(server.market_wait(after, datetime(2026, 11, 9, 15, 58).astimezone()), 300)
    w = server.market_wait(after, datetime(2026, 11, 9, 16, 6).astimezone())
    self.assertEqual(w, int((datetime(2026, 11, 10, 9, 30).astimezone() - after).total_seconds()) + 60)
    sat = datetime(2026, 11, 7, 12, 0).astimezone()
    self.assertEqual(server.market_wait(sat, None), int((datetime(2026, 11, 9, 9, 30).astimezone() - sat).total_seconds()) + 60)

def test_sec_only_gets_the_email(self):
    seen = []
    def fake(url, accept="*/*", timeout=20, ua=server.UA): seen.append((url, ua)); return json.dumps({"0": {"ticker": "AAPL", "title": "Apple Inc."}})
    with mock.patch.object(server, "http_get", fake):
        self.assertEqual(server.stock_search("apple")[0]["symbol"], "AAPL")
    self.assertTrue(all(url.startswith("https://www.sec.gov/") for url, ua in seen if "frischa@" in ua))
    with open(os.path.join(server.HERE, "server.py"), encoding="utf-8") as f:
        self.assertEqual(f.read().count("frischa@avifrischlaw.com"), 1)

def test_business_off(self):
    h = server.household(); h["business"]["on"] = False; server.save_household(h)
    self.assertEqual(server.fetch_markets(), {"off": True})
```

  Patch `SEC_FILE` into a temp dir for the SEC test.

- [ ] **Step 2: Run them and watch them fail.**
- [ ] **Step 3: Implement the section.**
- [ ] **Step 4: Run the full suite.**
- [ ] **Step 5: Live check.** Call `fetch_markets()` once with the watchlist AAPL and BRK.B (patched). Expected:
  - three indices with numbers;
  - two watch rows;
  - `source` "CNBC".

  Don't call `stock_search` live here: the first live SEC request happens when Avi uses the app.
- [ ] **Step 6: Commit** with the message "Business: market indices and watchlist (CNBC, Yahoo backup), business headlines, SEC ticker search".

---

### Task 8: Page: rotation per screen, every league, simple score panel, business scene

**Files:**
- Modify: `index.html`.
- Verify: with Playwright in demo mode. There's no JS test harness in this repo, and the checks below are the gate.

**Interfaces:**
- Consumes the state's `config.rotation`, `config.screen`, `config.sports` and `config.business_news`; `data["sport_<key>"]` (the Task 5 shape); `data.markets`, `data.biz_nyt`, `data.biz_cnbc`; and `data.team` `{"off": true}`.
- Produces:
  - `screenParam()`: `Q.get("screen")`. `poll()` fetches `/api/state` + (`?screen=` + encodeURIComponent when set).
  - `rotationList()`: `CFG().rotation` when present, else today's built-in `[["agenda",25],["shul",30],["yankees",30],["mlb",30],["news",30],["israel",25]]` with `rotation_seconds`. `duration(name)` reads it.
  - `withLive(seq, live)`: an algorithm the page must match exactly.
    ```js
    // live team scenes repeat every other turn: L1 s1 L2 s2 L1 s3 ...
    function withLive(seq, live) {
      if (!live.length) return seq;
      const out = [], rest = seq.filter((s) => !live.includes(s));
      rest.forEach((s, i) => { out.push(live[i % live.length]); out.push(s); });
      return out;
    }
    ```
    The live scenes are `yankees` when `D("team").live`, plus `<key>_team` when `D("sport_"+key).team.live`.
  - Scenes:
    - `SCENES` gains `business`, and, for each league key in `CFG().sports` other than `mlb`, `<key>_team` and `<key>`. These are made from `sportTeamScene(key)` and `sportLeagueScene(key)`, registered by `registerSports()` on each `renderAll()`.
    - Titles: the team scene is the favorite's `name`, and its tab is the favorite's abbreviation. The league scene is titled "Around the <League>"; its tab is the league's short name (NBA, WNBA, NFL, NHL, MLS, NCAAM, NCAAW, NCAAF).
    - `yankees`'s title and tab come from `CFG().team_abbr`/the favorite's name instead of "Yankees". Its news column stays `yankees_news` (the MLB.com Yankees feed); with another favorite that column is hidden.
  - `buildOrder()`:
    - `ok` per scene:
      - the current rules for the existing scenes;
      - `yankees`/`mlb` false when `D("team")` is `{off: true}`;
      - sport scenes only when `on && in_season`;
      - `business` when `D("markets")` exists and isn't `off`.
    - The order is `withLive(rotationList().map(first), live)`, filtered by `ok`.
  - The team scene layout mirrors `sceneTeam()`:
    - left: `sportCard(live)`, or `sportCard(last)` + `sportCard(next)`;
    - right: the standings table (`st.cols` headers, the favorite's row `.me`);
    - below in two columns: the team's news and the league news.
  - The league scene mirrors `sceneMLB()`: a `.mini-grid` of up to 8 `sportMini(g)` (chosen teams first), then news below.
  - `sportCard(g)`:
    - the head is the status: `g.detail`, or for Preview the day and time;
    - a row per side with abbr, name, score;
    - a by-period row (the `lines` numbers; columns 1…n with "OT" past 4 for basketball/football and past 3 for hockey);
    - the venue in the foot.
  - Tapping a sport game is `data-tap="score" data-key="<key>" data-id="<id>"`.
  - `PANELS.score` renders from the game already in the state (no request):
    - the teams with their scores;
    - a period table;
    - the state and clock (`detail`);
    - the venue;
    - "Final", or the start time.
  - Chips: `#chip` becomes `#chips`, holding one chip per live favorite: the MLB live game, then each league's live favorite.
    - Each chip opens its panel: `game` for MLB, `score` for the other leagues.
    - Hidden on the live team's own scene.
  - `sceneBusiness()`:
    - top: three index tiles (name, level, change, percent, up green / down red);
    - left column: the watchlist table (Symbol, Name, Last, Chg, %), at most 12 rows;
    - right column: headlines from whichever of `biz_nyt`/`biz_cnbc` are on in `CFG().business_news`, interleaved by time, through `headlines()`-style rows with `tapArticle`;
    - the head note: `Delayed · <h:mm am/pm of as_of>`, plus " · Market closed" when `market == "closed"`.
  - `makeDemo()` gains:
    - `config.rotation` (the house default plus `nba_team`, `nba`);
    - `config.sports` (`mlb` and `nba` with Knicks favorite);
    - `data.sport_nba`: one live Knicks game with lines, two finals, standings with GB, and news;
    - `data.markets`: 3 indices and 4 stocks, mixed up and down;
    - `data.biz_nyt` and `data.biz_cnbc` with 4 items each.

- [ ] **Step 1: Baseline.**
  - Serve on 8799 and open `http://localhost:8799/index.html?scene=shul&hold=1`.
  - In `browser_evaluate`, record `buildOrder()`.
  - Expected: `["agenda","shul","yankees","mlb","news","israel"]` (demo, before any change).

- [ ] **Step 2: Implement the rotation, `withLive`, the sports scenes, `PANELS.score`, the chips and the business scene, plus the `makeDemo()` additions above.**

- [ ] **Step 3: Verify with Playwright.** Each check is one `browser_evaluate`, or a screenshot read by eye.
  - `withLive(["a","b","c"], ["L"])` → `["L","a","L","b","L","c"]`, and `withLive(["a","b"], ["L","M"])` → `["L","a","M","b"]`.
  - In demo mode (Knicks live), `buildOrder()` begins `["nba_team","shul","nba_team",…]` and contains `business`. `#chips` has one chip with "NYK".
  - `?scene=nba_team&hold=1`: screenshot.
    - It shows the live card with the by-quarter row and the standings with a GB column.
    - Nothing overflows the stage: `document.querySelector('.stage').scrollHeight <= .clientHeight`.
  - `?scene=nba&hold=1`: a mini grid of games, with the Knicks first.
  - Click a mini game: `#panel` shows the period table and the venue, with no network request (check `browser_network_requests` for no new `/api/` call).
  - `?scene=business&hold=1`: three index tiles, 4 watchlist rows with up/down colors, and the "Delayed ·" note. Headlines fit (`fitColumns` hides the overflow).
  - `?at=2026-11-07T12:00` (Shabbat): `body.holy`. No agenda in `buildOrder()`, and the business scene still in rotation. Tapping does nothing.
  - Repeat the nba_team and business screenshots at 1366×768 and 1440×900. They must fit.

- [ ] **Step 4: Run the Python suite** (unchanged, a sanity check). Delete the screenshots.

- [ ] **Step 5: Commit** with the message "Page: rotation per screen, scenes for every league with a simple score panel, business scene".

---

### Task 9: Launcher takes its mode from the server

**Files:**
- Modify: `launcher.pyw`.
- Test: `tests/test_launcher.py` (add to it).

**Interfaces:**
- Consumes: `GET /api/screen-settings` from Task 3.
- Produces:
  - `screen_name() -> str`: `setting("screen_name", "")`, stripped, else `os.environ.get("COMPUTERNAME")` or `socket.gethostname()`. Cut to 40 characters, with characters outside `[A-Za-z0-9 ._'-]` replaced by `-`.
  - `SETTINGS_CACHE = os.path.join(HERE, "screen-settings.json")`.
  - `local_report() -> dict`: `{"mode": "saver" if SAVER else "always", "minutes", "lock", "screens", "awake"}` from `settings.json`.
  - `fetch_screen_settings() -> dict|None`: a GET to `URL + "api/screen-settings?" + urlencode({"screen": screen_name(), **local_report()})` with a 5-second timeout.
    - On 200 it writes `SETTINGS_CACHE` (atomic) and returns the dict. Otherwise it returns None and logs a failure once per reason.
  - `screen_setting(key: str, default)`. The key is one of `mode`, `minutes`, `lock`, `screens`, `keep_awake`.
    - It reads the cached server answer: `mode` at the top level, the others under `saver`.
    - It falls back to `settings.json` (`screensaver_minutes`, `screensaver_lock`, `screensaver_screens`, `keep_pc_awake`).
    - For `mode` the last fallback is `"saver" if SAVER else "always"`.
    - A corrupt cache is ignored, and logged once.
  - `page_url(saver: bool) -> str`: `URL + "?" + urlencode({"screen": screen_name(), **({"saver": 1} if saver else {})})`. `start_browser` uses it.
  - Mode switching: `main()` runs `while True: mode = screen_setting("mode", ...)`, then `always_loop(...)` or `saver_loop(...)`.
    - Each loop returns `server` when `screen_setting("mode")` changes. They check after each `fetch_screen_settings()`, called every 60 s.
    - On leaving, a loop closes its own browser windows. Saver mode also restores brightness and calls `keep_pc_awake()`.
    - The profile is chosen per mode, not at import: `profile_for(mode)` returns `browser-profile` or `browser-profile-saver`.
    - The mutex and `LOG_FILE` stay decided by the startup flag, so a Startup shortcut never runs two launchers.
  - The `saver_loop` setting reads move from `setting("screensaver_*")`/`setting("keep_pc_awake")` to `screen_setting(...)`.

- [ ] **Step 1: Write the failing tests.** Patch `launcher.HERE`/`SETTINGS_CACHE` into a temp dir with a `settings.json`.

```python
def test_screen_name_from_settings_or_pc(self):
    write_settings({"screen_name": "Ariela's Acer"})
    self.assertEqual(launcher.screen_name(), "Ariela's Acer")
    write_settings({})
    with mock.patch.dict(os.environ, {"COMPUTERNAME": "ARIELA-ACER"}):
        self.assertEqual(launcher.screen_name(), "ARIELA-ACER")

def test_server_answer_overrides_settings(self):
    write_settings({"screensaver_minutes": 10, "keep_pc_awake": False})
    write_cache({"mode": "saver", "saver": {"minutes": 20, "lock": True, "screens": "external", "keep_awake": True}})
    self.assertEqual(launcher.screen_setting("minutes", 10.0), 20.0)
    self.assertTrue(launcher.screen_setting("keep_awake", False))

def test_corrupt_cache_falls_back_to_settings(self):
    write_settings({"screensaver_minutes": 12})
    with open(launcher.SETTINGS_CACHE, "w") as f: f.write("{not json")
    self.assertEqual(launcher.screen_setting("minutes", 10.0), 12.0)

def test_no_answer_ever_uses_startup_flag(self):
    with mock.patch.object(launcher, "SAVER", True):
        self.assertEqual(launcher.screen_setting("mode", None), "saver")

def test_unreachable_server_keeps_cache(self):
    write_cache({"mode": "always", "saver": {}})
    with mock.patch.object(launcher.urllib.request, "urlopen", side_effect=OSError("down")):
        self.assertIsNone(launcher.fetch_screen_settings())
    self.assertEqual(launcher.screen_setting("mode", None), "always")

def test_page_url_carries_screen(self):
    write_settings({"screen_name": "Den"})
    self.assertTrue(launcher.page_url(True).endswith("?screen=Den&saver=1"))
```

- [ ] **Step 2: Run them and watch them fail.**
- [ ] **Step 3: Implement it as specified.**
  - The existing `AwakeFlagsTests` and screen tests must stay green.
  - `launcher.pyw` imports `urllib.request`, `urllib.parse` and `socket`.

- [ ] **Step 4: Run the full suite.**

- [ ] **Step 5: Local smoke test** on Avi's PC. The server is running locally with this branch.
  - Start `pythonw launcher.pyw --screensaver` with `screensaver_minutes` 0.5 in a scratch copy of the settings.
  - Confirm `screensaver.log` shows the check-in, and that `screen-settings.json` appears.
  - Then `POST /api/manage/screen` with `mode: "always"`. Within about 70 s the kiosk window opens and stays open. Then set it back to `saver`: the window closes.
  - Stop it with `stop-display.bat`.

- [ ] **Step 6: Commit** with the message "Launcher: screen name, settings from the server every minute, switch modes without a restart".

---

### Task 10: Setup, docs, deploy

**Files:**
- Modify: `setup-windows.ps1`. On the server PC (`$isServer`), after the server check, print:
  `Display Manager access code: <contents of manage-key.txt>`
  `(Type it into the Display Manager app once. Keep it private.)`
  If the file doesn't exist yet, start `server.py --setting port` once; that creates it through `manage_key()`, which `main()` calls before `--setting` returns. Move the `manage_key()` call above the `--setting` early return.
- Modify: `settings.example.json`. Add `"_screen_help"` and `"screen_name": ""`, with the help text "The name this PC's screen has in the Display Manager app. Leave empty to use the PC's name."
- Modify: `server.py`. Add `screen_name` to `LAUNCHER_SETTINGS`.
- Modify: `CLAUDE.md`, `README.md`. Document:
  - `household.json` and the access code;
  - `/api/manage/*` (a table);
  - `/api/screen-settings`;
  - `?screen=`, and the iPad bookmark `http://<ip>:8765/?screen=iPad`;
  - the ESPN, CNBC/Yahoo and SEC sources in the data-sources table, with their quirks: the ESPN date range answers 400, and Stooq now needs JavaScript, so it isn't used;
  - the sports and business scenes, `withLive`, and `#chips`.
- Modify: `.gitattributes`. Export-ignore `manager/` and `build-manager.bat`, which Part 2 creates.

- [ ] **Step 1: Write the failing test.** In `tests/test_server.py` `SettingsTests`, add `screen_name` to the launcher keys in `test_launcher_settings_are_not_reported_as_unknown`. Run it. Expected: FAIL, with "unknown setting 'screen_name'".
- [ ] **Step 2: Make the changes above.** Run the full suite: green. Run `C:\msys64\mingw64\bin\python.exe server.py --check`. Expected: every source OK except leagues switched off, which print `off`.
- [ ] **Step 3: Commit** with the message "Setup prints the Display Manager access code; docs for household config, screens, sports and business".
- [ ] **Step 4: Deploy to DESKTOP-H72VKDJ.** Ask Avi first, because it changes the live display.
  - Use the bundle → scp → `git pull --ff-only` route, then kill `server.py` so the launcher restarts it.
  - Restart the launcher too, so the new `launcher.pyw` runs. It's under the user's Startup shortcut, so use a scheduled task with an Interactive principal.
  - Verify:
    - `/api/state?screen=DESKTOP-H72VKDJ` has `agenda` in its rotation;
    - `/api/state` with no screen has none;
    - `household.json` and `manage-key.txt` exist;
    - the screen shows the business scene in turn.
  - Read the access code over SSH, for Avi to type into the app. Never paste it into a commit or a log.
