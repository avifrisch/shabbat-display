# Windows Screen Saver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A real Windows screen saver, `ShabbatDisplay.scr`, that shows the always-on PC's display on every monitor. It is set up and managed from the Display Manager app, and it stays up and unlocked over Shabbat and Yom Tov.

**Architecture:**
- **The server** keeps each PC's screen-saver options: minutes, lock and shabbat, plus a new mode `off`. Its `/api/screen-settings` answer adds the coming Shabbat/Yom Tov spans, computed from the Hebcal calendar.
- **The launcher** stops opening kiosk browsers in screen-saver mode. Instead it writes Windows' own screen-saver settings (HKCU and `SystemParametersInfo`), and writes `saver\saver.json` next to the `.scr`. It also keeps the PC awake on the day Shabbat or Yom Tov starts.
- **The `.scr`** is a small WinForms + WebView2 program with one borderless window per monitor. Each window shows the page with `?saver=1&shift=N`, so each monitor is on a different scene. It closes on any input, except during a holy span, when it ignores input and holds the screens on.

**Tech Stack:**
- Python 3 stdlib: `server.py`, `launcher.pyw`, `winreg` and `ctypes`; tests with unittest.
- .NET 10 WinForms with `Microsoft.Web.WebView2`, sharing the existing `Manager.Core` and its xUnit tests.
- The WinUI 3 app (`manager/App`), PowerShell and batch.

**Spec:** `docs/superpowers/specs/2026-11-08-windows-screensaver-design.md`

## Global Constraints

**Project rules:**
- Python standard library only on the server and launcher. No CI and no GitHub Actions.
- Secrets never go to the screen saver. The access code, nyt_cookie and agenda_ics never appear in `saver.json`, in `/api/screen-settings` or in the `.scr`. The `.scr` reads only the public page.
- The installer zip never contains settings.json.

**Limits on what it may change:**
- Never change brightness, display layout, resolution or any display setting. The one exception is the plugged-in screen-off timeout, and only as the spec allows. See Task 5.
- Nothing changes on a PC until Avi saves that screen in the app. Until then, the server echoes the launcher's own settings back.

**Behavior:**
- Closing is instant: hide the windows, then `Environment.Exit(0)`. No browser window, taskbar or "restore pages" bubble may flash.
- Holy span: from the first candle lighting to the next havdalah. This is the same span as the page's `body.holy`.

**Wording and paths:**
- Exact copy:
  - `Display not reachable`
  - `Shabbat Display` (the preview)
  - `The Shabbat Display screen saver is managed from the Shabbat Display Manager app.` (the `/c` message box)
  - `Keep the screens on over Shabbat and Yom Tov`
  - `Don't lock this PC (Win+L) on Erev Shabbat: the screen saver can't show over the lock screen.`
- The screen saver file is `<install dir>\saver\ShabbatDisplay.scr`, with `saver\saver.json` beside it. `saver/` is gitignored.

**Pushing and deploying:**
- No push to GitHub. Deploying to the always-on PC, the Surface or the Acer needs Avi's OK (Task 8).

## Review Focus

1. **The server is unreachable for days before Shabbat.** The launcher must keep the holy spans it was last sent: the cached `screen-settings.json` holds them, and `saver.json` keeps them. They must not be emptied. Test: Task 5, `test_holy_spans_survive_unreachable_server`.
2. **Havdalah passes while it shows.** Touches made during Shabbat must not close it at havdalah; only new input after havdalah does. Test: Task 3, `InputGate_after_havdalah_needs_new_input`.
3. **A path with spaces in `SCRNSAVE.EXE`.** Windows can fail to start a screen saver whose path has spaces, so the launcher writes the 8.3 short path when there is a space. Test: Task 5, `test_scr_path_with_spaces_uses_short_path`.
4. **A PC upgraded from the old launcher saver.** Its cached `screen-settings.json` and `household.json` still say `keep_awake` and `screens`. The Shabbat switch must come from `keep_awake`, and `screens` must be dropped. Tests: Task 1, `test_old_keep_awake_becomes_shabbat`; Task 5, `test_old_cache_keep_awake_means_shabbat`.
5. **Someone changes Windows' screen-saver settings by hand,** or a different screen saver is chosen while the mode is "off". In "saver" mode the launcher puts the settings back within a minute. In "off" or "always" mode it never touches another screen saver. Test: Task 5, `test_off_only_undoes_our_own_saver`.

---

### Task 1: Server: new screen-saver options, mode `off`, holy spans

**Files:**
- Modify: `server.py`: `default_saver()`, `_fill_household()`, `screen_settings_route()`, `_save_screen()`; new `_fix_saver()` and `holy_spans()`.
- Test: `tests/test_screens.py`

**Interfaces:**
- Produces:
  - **`default_saver()`** returns `{"minutes": 10, "lock": True, "shabbat": False}`.
  - **Modes** are `"always" | "saver" | "off"`.
  - **`holy_spans(items=None, n=None) -> list[dict]`** returns `[{"start": "<Hebcal date string>", "end": "<Hebcal date string>"}]`.
    - It reads `store.get("calendar")["items"]` and returns only spans whose end is after `n`, which defaults to `now()`.
    - A span starts at a `candles` item and ends at the next `havdalah`. Later `candles` before that `havdalah` belong to the same span.
  - **The `/api/screen-settings` query** is `screen, mode, minutes, lock, shabbat`. Old launchers send `awake`, which is used when `shabbat` is absent.
  - **The answer** is `{"ok", "screen", "mode", "saver": {"minutes", "lock", "shabbat"}, "saved", "holy": holy_spans()}`.
  - **POST `/api/manage/screen`** takes the body `{"name", "mode", "saver": {"minutes": int 1-240, "lock": bool, "shabbat": bool}}`.

- [ ] **Step 1: Write the failing tests** in `ScreenTests`:
  - Rewrite `test_launcher_first_checkin_echoes_its_own_settings` to use `shabbat=1`. It asserts `j["saver"] == {"minutes": 10, "lock": True, "shabbat": True}`.
  - Rewrite `test_bad_screen_settings_query` with the same 400 and the same fallback to 10.
  - Add the new tests:

```python
    def test_old_launcher_awake_means_shabbat(self):
        j = self.get("/api/screen-settings?screen=Ariela&mode=saver&minutes=10&lock=1&screens=external&awake=1")[1]
        self.assertEqual(j["saver"], {"minutes": 10, "lock": True, "shabbat": True})

    def test_old_keep_awake_becomes_shabbat(self):
        h = server.household()
        h["screens"]["Acer"] = dict(server._new_screen(), saver={"minutes": 15, "lock": False, "screens": "external", "keep_awake": True})
        server.save_household(h)
        self.assertEqual(server.household()["screens"]["Acer"]["saver"], {"minutes": 15, "lock": False, "shabbat": True})

    def test_save_screen_off_and_shabbat(self):
        code, _ = self.post("/api/manage/screen", {"name": "Acer", "mode": "off", "saver": {"minutes": 12, "lock": True, "shabbat": True}})
        self.assertEqual(code, 200)
        s = server.household()["screens"]["Acer"]
        self.assertEqual((s["mode"], s["saver"]), ("off", {"minutes": 12, "lock": True, "shabbat": True}))

    def test_save_screen_rejects_bad_minutes(self):
        for m in (0, 241, 1.5, True):
            self.assertEqual(self.post("/api/manage/screen", {"name": "Acer", "mode": "saver", "saver": {"minutes": m}})[0], 400)

    def test_holy_spans_from_calendar(self):
        items = [{"category": "havdalah", "date": "2026-11-07T17:25:00-05:00"},
                 {"category": "candles", "date": "2026-11-13T16:17:00-05:00"},
                 {"category": "havdalah", "date": "2026-11-14T17:20:00-05:00"},
                 {"category": "candles", "date": "2026-11-20T16:12:00-05:00"},   # Erev Yom Tov
                 {"category": "candles", "date": "2026-11-21T17:16:00-05:00"},   # second day
                 {"category": "havdalah", "date": "2026-11-22T17:15:00-05:00"}]
        n = server.parse_dt("2026-11-10T09:00:00-05:00")
        self.assertEqual(server.holy_spans(items, n), [
            {"start": "2026-11-13T16:17:00-05:00", "end": "2026-11-14T17:20:00-05:00"},
            {"start": "2026-11-20T16:12:00-05:00", "end": "2026-11-22T17:15:00-05:00"}])
        self.assertEqual(len(server.holy_spans(items, server.parse_dt("2026-11-14T18:00:00-05:00"))), 1)

    def test_screen_settings_carries_holy_spans(self):
        server.store.data["calendar"] = {"items": [{"category": "candles", "date": "2099-01-02T16:00:00-05:00"},
                                                   {"category": "havdalah", "date": "2099-01-03T17:00:00-05:00"}]}
        j = self.get("/api/screen-settings?screen=Ariela&mode=saver")[1]
        self.assertEqual(j["holy"], [{"start": "2099-01-02T16:00:00-05:00", "end": "2099-01-03T17:00:00-05:00"}])
```

  If `ManageCase` has no `post` helper, add one next to `get` in `tests/test_manage.py`. It sends the `X-Manage-Key` header the way the existing manage tests do.

- [ ] **Step 2: Run the tests and watch them fail**
  - Run: `C:\msys64\mingw64\bin\python.exe -m unittest tests.test_screens -v`
  - Expected: the new tests fail with KeyError `shabbat`, AttributeError `holy_spans`, and 400 for mode `off`.

- [ ] **Step 3: Implement**
  - **`_fix_saver(sv) -> dict`:**
    - `minutes`: an int from 1 to 240, else 10. A float from a launcher is rounded, then clamped.
    - `lock`: a bool, default True.
    - `shabbat`: `sv.get("shabbat", sv.get("keep_awake", False))`.
    - Any other keys are dropped.
  - **Where it's used:**
    - `_fill_household` repairs every screen's `saver` and its `local.saver` with it, and accepts mode `off`.
    - `screen_settings_route` builds `local` with it and passes the saver through it.
    - `_save_screen`:
      - It validates minutes as a non-bool int from 1 to 240, with the existing error sentence.
      - A bad mode gets "The mode must be always on, screen saver or off."
      - It drops the `screens` check.
  - **`holy_spans()`** uses `parse_dt` for the comparisons, and returns the date strings exactly as Hebcal gave them.

- [ ] **Step 4: Run the whole server suite**
  - Run: `C:\msys64\mingw64\bin\python.exe -m unittest discover -s tests`
  - Expected: OK. Fix any older test in `test_manage.py`/`test_household.py` that asserted the old `screens`/`keep_awake` shape, so it asserts the new one.

- [ ] **Step 5: Commit**

```bash
git add server.py tests/
git commit -m "Server: screen saver options are minutes, lock and Shabbat; mode off; holy spans for launchers"
```

### Task 2: Page: `?shift=N` starts the rotation N scenes in

**Files:**
- Modify: `index.html` (in `renderAll()`, the `if (!current)` branch, around line 1439)

**Interfaces:**
- Produces: `?shift=N`, where N is a non-negative integer. With no usable `?scene=`, the first scene is `order[N % order.length]`. A missing or bad value means 0.

- [ ] **Step 1: Check today's behavior.** Open `index.html` as a file (demo data) with Playwright at 1920×1080: `file:///C:/ShabbatDisplay/index.html?shift=1&hold=1`. Expected: `#stitle` is the same as without `shift`, which is the first scene. Note that title.
- [ ] **Step 2: Implement.** When `order.indexOf(Q.get("scene"))` is −1, set `idx` from `shift`.
- [ ] **Step 3: Verify**
  - Reload with `?shift=1&hold=1`, then `?shift=2&hold=1`, then `?shift=99&hold=1`.
  - Expected: the second scene, then the third, then `order[99 % order.length]`. `?scene=news&shift=2` still shows news.
- [ ] **Step 4: Commit:** `git commit -am "Page: ?shift=N starts the rotation N scenes in (each screen-saver monitor on a different scene)"`

### Task 3: Manager.Core: screen-saver options and the `.scr`'s logic

**Files:**
- Modify: `manager/Manager.Core/Models.cs:15`
- Create: `manager/Manager.Core/Saver.cs`
- Modify: `manager/Manager.Tests/ClientTests.cs`, lines 51, 72, 78 and 94
- Create: `manager/Manager.Tests/SaverTests.cs`

**Interfaces:**
- Consumes: the JSON shapes from Task 1, and `saver.json` from Task 5: `{"url": "http://100.98.145.119:8765/", "screen": "Ariela's Acer", "shabbat": true, "holy": [{"start": "...", "end": "..."}]}`.
- Produces:
  - **The options record:** `public record SaverOptions(int Minutes, bool Lock, bool Shabbat);`
  - **Launch arguments:**
    - `public enum SaverAction { Show, Preview, Configure }`
    - `public record SaverLaunch(SaverAction Action, nint Parent)`
    - `static SaverLaunch SaverLaunch.Parse(string[] args)`:
      - `/s` or `-s` → Show.
      - `/p 123` or `/p:123` → Preview with parent 123.
      - `/c`, `/c:123` or no arguments → Configure.
      - Case-insensitive.
  - **Holy spans:** `public record HolySpan(DateTimeOffset Start, DateTimeOffset End);`
  - **The config record:** `public record SaverConfig(Uri Url, string Screen, bool Shabbat, List<HolySpan> Holy)`
    - `static SaverConfig? Load(string json)` returns null when the JSON is bad or has no absolute http(s) `url`.
    - `bool IsHoly(DateTimeOffset now)`: `Shabbat` is on and now is inside a span.
    - `bool HoldScreens(DateTimeOffset now)`: `Shabbat` is on and now is from midnight of the span start's date (in the start's own offset) until its end.
    - `Uri PageUrl(int shift)` returns `{Url}?screen=<escaped>&saver=1&shift=N`.
  - **The input gate:** `public sealed class InputGate(uint startTick)` with `bool ShouldClose(uint tick, bool holy)`.
    - During holy it takes the new tick as its baseline and returns false.
    - Otherwise it returns `tick != baseline`.

- [ ] **Step 1: Write the failing tests**
  - Update `ClientTests` to the new `SaverOptions(Minutes, Lock, Shabbat)`:
    - Its household JSON fixtures use `"shabbat": true` in place of `"screens"`/`"keep_awake"`.
    - Line 51 asserts `.Saver.Shabbat`.
    - The `SaveScreenAsync` test asserts the sent body has `"saver":{"minutes":15,"lock":true,"shabbat":true}`.
  - In `SaverTests.cs`:

```csharp
[Theory]
[InlineData(new string[0], SaverAction.Configure, 0)]
[InlineData(new[] { "/s" }, SaverAction.Show, 0)]
[InlineData(new[] { "/S" }, SaverAction.Show, 0)]
[InlineData(new[] { "-s" }, SaverAction.Show, 0)]
[InlineData(new[] { "/p", "1234" }, SaverAction.Preview, 1234)]
[InlineData(new[] { "/P:1234" }, SaverAction.Preview, 1234)]
[InlineData(new[] { "/c:99" }, SaverAction.Configure, 0)]
public void Parse_reads_windows_arguments(string[] args, SaverAction action, long parent) =>
    Assert.Equal(new SaverLaunch(action, (nint)parent), SaverLaunch.Parse(args));

const string Json = """{"url":"http://100.98.145.119:8765/","screen":"Ariela's Acer","shabbat":true,
  "holy":[{"start":"2026-11-13T16:17:00-05:00","end":"2026-11-14T17:20:00-05:00"}]}""";
static DateTimeOffset T(string s) => DateTimeOffset.Parse(s);

[Fact] public void Load_rejects_bad_files()
{ Assert.Null(SaverConfig.Load("{}")); Assert.Null(SaverConfig.Load("not json")); Assert.Null(SaverConfig.Load("""{"url":"file:///c:/x"}""")); }

[Fact] public void PageUrl_has_screen_saver_and_shift() =>
    Assert.Equal("http://100.98.145.119:8765/?screen=Ariela%27s%20Acer&saver=1&shift=1", SaverConfig.Load(Json)!.PageUrl(1).AbsoluteUri);

[Fact] public void Holy_only_inside_the_span_and_with_the_switch_on()
{
    var c = SaverConfig.Load(Json)!;
    Assert.False(c.IsHoly(T("2026-11-13T16:00:00-05:00")));
    Assert.True(c.IsHoly(T("2026-11-14T12:00:00-05:00")));
    Assert.False(c.IsHoly(T("2026-11-14T17:21:00-05:00")));
    Assert.False((c with { Shabbat = false }).IsHoly(T("2026-11-14T12:00:00-05:00")));
}

[Fact] public void Screens_held_from_midnight_of_the_candle_lighting_day()
{
    var c = SaverConfig.Load(Json)!;
    Assert.False(c.HoldScreens(T("2026-11-12T23:30:00-05:00")));
    Assert.True(c.HoldScreens(T("2026-11-13T00:30:00-05:00")));
    Assert.False(c.HoldScreens(T("2026-11-14T17:21:00-05:00")));
}

[Fact] public void InputGate_closes_on_input_outside_shabbat()
{ var g = new InputGate(100); Assert.False(g.ShouldClose(100, false)); Assert.True(g.ShouldClose(101, false)); }

[Fact] public void InputGate_after_havdalah_needs_new_input()
{
    var g = new InputGate(100);
    Assert.False(g.ShouldClose(250, true));   // touched on Shabbat: ignored
    Assert.False(g.ShouldClose(250, false));  // havdalah: that old touch doesn't count
    Assert.True(g.ShouldClose(251, false));
}
```

- [ ] **Step 2: Run the tests and watch them fail**
  - Run: `dotnet test manager\Manager.Tests`, with the .NET 10 SDK picked as in `build-manager.bat`.
  - Expected: a compile failure on `SaverLaunch`, `SaverConfig`, `InputGate` and the new `SaverOptions`.
- [ ] **Step 3: Implement** `Saver.cs` and the `Models.cs` change. Parse with `System.Text.Json` and snake_case, as `ManageClient` does. The App will not compile until Task 6; that's expected here.
- [ ] **Step 4: Run the tests**
  - Run: `dotnet test manager\Manager.Tests`
  - Expected: all pass. That is the 41 earlier tests plus the new ones.
- [ ] **Step 5: Commit:** `git commit -m "Manager.Core: screen saver options with the Shabbat switch; .scr arguments, config and input gate"`

### Task 4: The `.scr` itself

**Files:**
- Create: `manager/Saver/ShabbatSaver.csproj`, `manager/Saver/Program.cs`, `manager/Saver/SaverForm.cs`, `manager/Saver/PreviewWindow.cs`
- Create: `build-saver.bat` (CRLF)
- Modify: `manager/Manager.slnx` (add the project), `build-manager.bat` (call `build-saver.bat` after the tests), `.gitignore` (add `saver/`), `.gitattributes` (add `build-saver.bat export-ignore`)

**Interfaces:**
- Consumes: `SaverLaunch`, `SaverConfig`, `InputGate` from Task 3, and `?shift=` from Task 2.
- Produces: `saver\ShabbatDisplay.scr`, built by `build-saver.bat`.

**The project:**
- WinExe with `net10.0-windows` and `UseWindowsForms`. Settings:
  - `AssemblyName` ShabbatDisplay
  - `ApplicationHighDpiMode` PerMonitorV2
  - `Nullable`/`ImplicitUsings` on
  - `RuntimeIdentifier` win-x64
  - `SelfContained`, `PublishSingleFile`, `IncludeNativeLibrariesForSelfExtract` and `PublishReadyToRun` all true
- References `..\Manager.Core`, and the current stable `Microsoft.Web.WebView2` from nuget.org, pinned to an exact version.

**`build-saver.bat`:**
- Picks the .NET 10 SDK exactly as `build-manager.bat` does. Move that loop into this file and have `build-manager.bat` call it, so the code isn't duplicated.
- Runs `dotnet publish manager\Saver\ShabbatSaver.csproj -c Release -o dist\saver`.
- Copies `dist\saver\ShabbatDisplay.exe` to `saver\ShabbatDisplay.scr`.
- Exits non-zero on any failure.

**What `Program.cs` does by action:**

*Configure:*
- Shows a `MessageBox` with the exact copy from Global Constraints, then exits.

*Preview:*
- `PreviewWindow` is a borderless form made a `WS_CHILD` of the given HWND with `SetParent`, sized to the parent's client area.
- It is painted navy (#0D1726) with `Shabbat Display` in gold (#E5BA5E).
- It exits when `IsWindow(parent)` turns false, checked every 500 ms.

*Show:*
- **Single instance:** a mutex named `Local\ShabbatDisplaySaver`. A second copy exits.
- **The config:** load `saver.json` from `Path.GetDirectoryName(Environment.ProcessPath)`. If it is missing or bad, every window shows the fallback.
- **The windows:**
  - One `SaverForm` per `Screen.AllScreens`, primary first, then by `Bounds.Left`. Form *i* shows `PageUrl(i)`.
  - Each form is borderless and `TopMost`, with no taskbar entry, `Bounds = screen.Bounds` and a #0D1726 background.
  - Call `Cursor.Hide()`.
- **WebView2:**
  - One shared `CoreWebView2Environment`, with its data folder at `%LOCALAPPDATA%\ShabbatDisplay\SaverWebView2`.
  - Default context menus, dev tools, zoom control, browser accelerator keys and the status bar are all off.
- **The fallback:**
  - It is a panel inside each form: a large clock (`h:mm`, warm off-white) and `Display not reachable` beneath it in a small, dim style.
  - The clock shows from the start. The words show only after a failed navigation, or after 10 s without a successful one.
  - A successful `NavigationCompleted` shows the WebView2.
  - A failed navigation or `ProcessFailed` shows the fallback again and retries every 30 s.
- **The 50 ms timer:**
  - Reads `GetLastInputInfo().dwTime` and calls `gate.ShouldClose(tick, config?.IsHoly(DateTimeOffset.Now) == true)`.
  - On true it hides every form, then calls `Environment.Exit(0)`.
- **The 1 s timer:**
  - Calls `SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED)` while `HoldScreens(now)` holds, else `ES_CONTINUOUS`.
  - Reloads `saver.json` every 60 s, keeping the old config if the new one is bad.
- **Closing during holy:** `FormClosing` cancels a `UserClosing` (Alt+F4) while `IsHoly(now)`. It never cancels Windows shutting down or signing out.

- [ ] **Step 1: Build**
  - Run: `build-saver.bat`
  - Expected: `saver\ShabbatDisplay.scr` exists. `git status` doesn't list it.
- [ ] **Step 2: Check configure and preview**
  - Run `saver\ShabbatDisplay.scr /c`. Expected: the message box with the exact copy.
  - Run `saver\ShabbatDisplay.scr` with no arguments. Expected: the same message box.
- [ ] **Step 3: Check the weekday behavior** against this PC's server.
  - Write `saver\saver.json` by hand: `{"url":"http://127.0.0.1:8765/","screen":"Surface-Studio","shabbat":false,"holy":[]}`.
  - Start the saver with a 5 s delay so the starting keypress isn't counted: `Start-Sleep 5; saver\ShabbatDisplay.scr /s`, run from PowerShell.
  - Take a screenshot of each monitor without touching the mouse, with a PowerShell `CopyFromScreen` of each `Screen.Bounds` from a second shell.
  - Expected:
    - Every monitor shows the display, each on a different scene.
    - There's no cursor.
    - Moving the mouse closes it within a moment, and Task Manager shows no `ShabbatDisplay` processes left.
- [ ] **Step 4: Check the holy behavior.**
  - Set `"shabbat":true` with a span from 1 hour ago to 1 hour ahead, then start it.
  - Expected:
    - Mouse moves, clicks, keys and Alt+F4 don't close it.
    - Edit the span's end to 1 minute from now. The saver reloads the file within 60 s, and after the end passes, a new mouse move closes it.
  - Close it with `taskkill /im ShabbatDisplay.scr /f` if needed.
- [ ] **Step 5: Check the fallback.** Set `"url":"http://127.0.0.1:9/"` and start it. Expected: a dark screen with the clock, and `Display not reachable` within about 10 s on every monitor.
- [ ] **Step 6: Commit**

```bash
git add manager/Saver manager/Manager.slnx build-saver.bat build-manager.bat .gitignore .gitattributes
git commit -m "ShabbatDisplay.scr: a real Windows screen saver, every monitor on a different scene, held over Shabbat"
```

### Task 5: Launcher: Windows' screen-saver settings in place of the kiosk saver

**Files:**
- Modify: `launcher.pyw`
- Test: `tests/test_launcher.py`

**What to remove:** retire the old saver and its tests.
- `saver_loop`, `screens`, `pick_screens` and `internal_displays`.
- `saver_profiles`, `lock_screen`, `awake_flags` and `keep_pc_awake`.
- `last_input`, `idle_from`, `idle_seconds` and `screen_busy`.
- Any test classes for these, such as `ScreenChoiceTests` and `AwakeFlagsTests`, and the idle tests.

**What to keep:**
- `restore_brightness()` and `set_internal_brightness()`. Restore once at launcher start, as today, and make sure `brightness-before-saver.txt` is deleted afterwards, so no panel is left dimmed.
- The `--screensaver` flag still picks the mutex and log file, as today.

**Interfaces:**
- Consumes: the Task 1 answer (`mode`, `saver.minutes/lock/shabbat`, `holy`).
- Produces:
  - **Paths:** `SAVER_DIR = os.path.join(HERE, "saver")`, `SCR = os.path.join(SAVER_DIR, "ShabbatDisplay.scr")`, `SAVER_CONFIG = os.path.join(SAVER_DIR, "saver.json")`.
  - **Settings from the cache:**
    - `LOCAL_KEYS = {"minutes": "screensaver_minutes", "lock": "screensaver_lock", "shabbat": "keep_pc_awake"}`.
    - In a cached saver with no `shabbat`, `screen_setting("shabbat", False)` reads `keep_awake`.
  - **`local_report()`** returns `{"mode", "minutes", "lock", "shabbat"}`.
    - `mode` is `saver` with the `--screensaver` flag, else `always`.
    - `minutes` is a whole number.
  - **Holy spans:**
    - `cached_holy() -> list[dict]` returns `holy` from `screen-settings.json`, or `[]`.
    - `holy_now(spans, now) -> bool` and `shabbat_day(spans, now) -> bool` follow the same rules as `SaverConfig.IsHoly`/`HoldScreens` in Task 3, but without the switch. `now` is an aware datetime, parsed with `datetime.fromisoformat`.
  - **`scr_registry_path(path, shorten=None) -> str`** uses `GetShortPathNameW` when the path has a space. `shorten` is injected for tests.
  - **`saver_registry(mode, minutes, lock, holy, scr) -> dict[str, str]`:**
    - For `saver` it returns `{"SCRNSAVE.EXE": scr, "ScreenSaveActive": "1", "ScreenSaveTimeOut": str(minutes*60), "ScreenSaverIsSecure": "0" if holy else ("1" if lock else "0")}`.
    - Otherwise it returns `{"ScreenSaveActive": "0"}`.
  - **`registry_changes(desired, current, mode, scr) -> dict`** returns only the values that differ.
    - For `off`/`always` it returns `{}` unless the current `SCRNSAVE.EXE` is ours, compared case-insensitively and after `os.path.normcase`/`normpath`.
  - **`apply_registry_changes(changes)`:**
    - `SCRNSAVE.EXE` is written with `winreg` to `HKCU\Control Panel\Desktop` as `REG_SZ`.
    - The other three values go through `SystemParametersInfoW` with `SPIF_UPDATEINIFILE | SPIF_SENDCHANGE`: `SPI_SETSCREENSAVEACTIVE` 0x0011, `SPI_SETSCREENSAVETIMEOUT` 0x000F and `SPI_SETSCREENSAVESECURE` 0x0077.
    - `read_saver_registry() -> dict` reads the four values.
  - **`write_saver_config(url, screen, shabbat, holy) -> bool`** writes `SAVER_CONFIG` atomically, only when the content changed, and returns whether it wrote.
  - **`screen_off_target(off_minutes, wait_minutes) -> int | None`** returns `wait_minutes + 20` when `0 < off_minutes <= wait_minutes`, else None.
  - **`windows_saver_loop(server, mode) -> server`** replaces `saver_loop`. It handles mode `saver` and mode `off`; its steps are below.
  - **`main()`** runs `windows_saver_loop` for mode `saver` or `off` on Windows, and `always_loop` otherwise. A non-Windows PC with mode `saver` or `off` runs `always_loop` and logs one line saying so.

**What `windows_saver_loop` does every 30 s:**
- Fetches the settings once a minute, as `always_loop` does. Then:
  1. Computes `holy = shabbat and holy_now(cached_holy(), now)`.
  2. Applies `registry_changes(saver_registry(...), read_saver_registry(), ...)`.
  3. In mode `saver`, writes the config with `write_saver_config(URL, screen_name(), shabbat, cached_holy())`.
  4. Calls `SetThreadExecutionState`:
     - `ES_CONTINUOUS | ES_SYSTEM_REQUIRED` while `shabbat and shabbat_day(...)`, else `ES_CONTINUOUS`.
     - Never `ES_DISPLAY_REQUIRED`, which would stop Windows from ever starting the screen saver.
- It never opens a browser.
- With the Shabbat switch on:
  - If `screen_off_target()` gives a value, it runs `powercfg /change monitor-timeout-ac <n>` once and logs it.
  - It logs once if `SCR` is missing ("saver\ShabbatDisplay.scr is missing; rebuild or reinstall").
  - It logs once if any `ScreenSave*` or `SCRNSAVE.EXE` value exists under `HKCU\Software\Policies\Microsoft\Windows\Control Panel\Desktop`. That means a policy controls the screen saver, which is the management check the spec asks for.
- It keeps a local server alive as `always_loop` does, when the PC is not `REMOTE`.
- It returns when the mode changes.

- [ ] **Step 1: Write the failing tests**

```python
SPANS = [{"start": "2026-11-13T16:17:00-05:00", "end": "2026-11-14T17:20:00-05:00"}]
def at(s): return datetime.fromisoformat(s)
SCR = r"C:\ShabbatDisplay\saver\ShabbatDisplay.scr"

class WindowsSaverTests(unittest.TestCase):
    def test_saver_registry_points_windows_at_the_scr(self):
        self.assertEqual(launcher.saver_registry("saver", 10, True, False, SCR),
                         {"SCRNSAVE.EXE": SCR, "ScreenSaveActive": "1", "ScreenSaveTimeOut": "600", "ScreenSaverIsSecure": "1"})

    def test_holy_turns_lock_off(self):
        self.assertEqual(launcher.saver_registry("saver", 10, True, True, SCR)["ScreenSaverIsSecure"], "0")

    def test_only_changed_values_are_written(self):
        want = launcher.saver_registry("saver", 10, True, False, SCR)
        self.assertEqual(launcher.registry_changes(want, dict(want, ScreenSaveTimeOut="300"), "saver", SCR), {"ScreenSaveTimeOut": "600"})
        self.assertEqual(launcher.registry_changes(want, want, "saver", SCR), {})

    def test_off_only_undoes_our_own_saver(self):
        off = launcher.saver_registry("off", 10, True, False, SCR)
        mystify = {"SCRNSAVE.EXE": r"C:\Windows\system32\Mystify.scr", "ScreenSaveActive": "1"}
        self.assertEqual(launcher.registry_changes(off, mystify, "off", SCR), {})
        ours = {"SCRNSAVE.EXE": SCR.lower(), "ScreenSaveActive": "1"}
        self.assertEqual(launcher.registry_changes(off, ours, "off", SCR), {"ScreenSaveActive": "0"})

    def test_scr_path_with_spaces_uses_short_path(self):
        self.assertEqual(launcher.scr_registry_path(SCR, shorten=lambda p: "X"), SCR)
        self.assertEqual(launcher.scr_registry_path(r"C:\dev\shabbat display\saver\ShabbatDisplay.scr", shorten=lambda p: r"C:\dev\SHABBA~1\saver\SHABBA~1.SCR"),
                         r"C:\dev\SHABBA~1\saver\SHABBA~1.SCR")

    def test_holy_now_and_shabbat_day(self):
        cases = {"2026-11-12T23:00:00-05:00": (False, False), "2026-11-13T09:00:00-05:00": (False, True),
                 "2026-11-13T16:30:00-05:00": (True, True), "2026-11-14T17:30:00-05:00": (False, False)}
        for t, (holy, day) in cases.items():
            self.assertEqual((launcher.holy_now(SPANS, at(t)), launcher.shabbat_day(SPANS, at(t))), (holy, day), t)

    def test_screen_off_raised_only_when_too_soon(self):
        self.assertEqual(launcher.screen_off_target(10, 10), 30)
        self.assertIsNone(launcher.screen_off_target(0, 10))    # never turns off
        self.assertIsNone(launcher.screen_off_target(45, 10))
```

  Also, using the existing tests' temp-dir pattern for `SETTINGS_CACHE`/`SAVER_CONFIG`, add these to the settings tests:
  - **`test_write_saver_config_only_when_changed`:** the first call returns True; the same content again returns False. The file's JSON equals `{"url", "screen", "shabbat", "holy"}`, with no other keys.
  - **`test_holy_spans_survive_unreachable_server`:**
    - Write the cache with `holy: SPANS`.
    - Make `fetch_screen_settings` fail by pointing `URL` at `http://127.0.0.1:9/`.
    - `cached_holy()` still returns SPANS.
  - **`test_old_cache_keep_awake_means_shabbat`:** with a cache of `{"mode": "saver", "saver": {"minutes": 10, "lock": True, "screens": "all", "keep_awake": True}}`, `screen_setting("shabbat", False)` is True.
  - **`test_local_report_sends_shabbat`:** the keys are `{"mode", "minutes", "lock", "shabbat"}`.

- [ ] **Step 2: Run the tests and watch them fail**
  - Run: `C:\msys64\mingw64\bin\python.exe -m unittest tests.test_launcher -v`
  - Expected: AttributeError on the new functions.
- [ ] **Step 3: Implement** the Interfaces above, and remove the retired code and its tests.
- [ ] **Step 4: Run the whole suite**
  - Run: `C:\msys64\mingw64\bin\python.exe -m unittest discover -s tests`
  - Expected: OK.
  - Then run `C:\msys64\mingw64\bin\python.exe -c "import ast,sys; ast.parse(open('launcher.pyw').read())"` and grep for any leftover use of a removed name: `grep -n "saver_loop\|pick_screens\|awake_flags\|idle_seconds" launcher.pyw`. Expected: no output.
- [ ] **Step 5: Commit:** `git commit -am "Launcher: set Windows' own screen saver to the Shabbat Display; keep the PC awake on Erev Shabbat; old kiosk saver retired"`

### Task 6: App: Screens page shows the new options

**Files:**
- Modify: `manager/App/Pages/ScreensPage.xaml.cs` (Draft at line 21, line 97, the mode/saver block at lines 220-275)
- Check: any other compile errors from `SaverOptions`, which `dotnet build` reports.

**Interfaces:**
- Consumes: `SaverOptions(int Minutes, bool Lock, bool Shabbat)` from Task 3; `SaveScreenAsync` is unchanged.

**Changes:**
- **Defaults:** `new SaverOptions(10, true, false)` in both places.
- **The mode ComboBox** items are `Always on`, `Screen saver`, `Off`, with index 0, 1, 2 ↔ `always`, `saver`, `off`.
- **The saver panel,** visible only for `saver`:
  - The existing minutes NumberBox, renamed to "Wait (minutes)".
  - The CheckBox `Lock Windows when it closes (never over Shabbat and Yom Tov)`.
  - The CheckBox `Keep the screens on over Shabbat and Yom Tov`.
  - Under that switch, a wrapped TextBlock with the exact Win+L sentence, visible while it's checked.
  - The "which monitor" ComboBox and the old keep-awake CheckBox are gone.
- **Accessibility:** every control keeps an automation name.

- [ ] **Step 1: Build.** Run `build-manager.bat`. Expected: tests pass, then the publish succeeds. Fix the compile errors the `SaverOptions` change causes here.
- [ ] **Step 2: Check the app against a test server**
  - Run the request handler on another port with a temporary household. Follow the recipe in CLAUDE.md "Testing → Display Manager app", with one launcher screen `Acer` in mode `saver`.
  - Drive the app with UIA (`uia.ps1`): open Screens → Acer, set Off, then Screen saver, tick the Shabbat switch, and Save.
  - Expected:
    - The Win+L note appears when the switch is ticked.
    - After Save, the temporary `household.json` has `"mode": "saver"` and `"saver": {"minutes": 10, "lock": true, "shabbat": true}`.
    - A PrintWindow capture shows no monitor picker.
- [ ] **Step 3: Commit:** `git commit -am "Display Manager: screen saver on/off, wait, lock and the Shabbat switch per PC"`

### Task 7: Installer, setup and docs

**Files:**
- Modify: `make-installer.ps1`, `setup-windows.ps1` (the `if ($saver)` block, around lines 247-280, and the update-copy path that stops the old copy), `server.py` (only if `LAUNCHER_SETTINGS` needs the new keys; `screensaver_screens` stays tolerated), `CLAUDE.md`

**make-installer.ps1:**
- After `git archive`, run `cmd /c build-saver.bat`. Stop with "The screen saver didn't build; the zip was not made." on a non-zero exit, and delete the half-made zip.
- Add `saver\ShabbatDisplay.scr` to the zip as `ShabbatDisplay/saver/ShabbatDisplay.scr` with `System.IO.Compression.ZipFile.Open($zip, 'Update')`.
- Print the size as today.

**setup-windows.ps1, screen-saver branch:**
- **Replace** the "turn off the Windows screen saver" question and the plugged-in-monitor question with this:
  - **Explain:** "The Shabbat Display becomes this PC's Windows screen saver. Change it from the Display Manager app."
  - **Check the file:** if `saver\ShabbatDisplay.scr` is missing, warn: "This copy has no screen saver file; download the latest ShabbatDisplay.zip."
  - **Ask** `Keep the screens on over Shabbat and Yom Tov?` and save the answer as `keep_pc_awake`.
  - **Ask** `Lock Windows when the screen saver closes?` (default yes) and save the answer as `screensaver_lock`, written only when false.
  - **Print** the Win+L sentence.
  - **Warn** if the policy key from Task 5 has screen-saver values.
- **Keep** the screen-off check.
- **Update path:** also stop any running `ShabbatDisplay.scr` process (`Get-Process ShabbatDisplay -ErrorAction SilentlyContinue | Stop-Process -Force`) before copying, because a running `.scr` locks the file.

**CLAUDE.md:**
- Replace the `--screensaver` bullet block under `launcher.pyw` with the new behavior.
- Add `manager/Saver` and `build-saver.bat` to the `manager/` bullet.
- Note `?shift=` under Testing → URL parameters.
- Note `holy` and mode `off` in the household/screen-settings bullets.
- Move "Never tested on real hardware" items as Task 8 verifies them.

- [ ] **Step 1: Build the zip**
  - Run `make-installer.bat`, then `powershell -NoProfile -Command "Add-Type -A System.IO.Compression.FileSystem; [IO.Compression.ZipFile]::OpenRead('dist\ShabbatDisplay.zip').Entries.FullName | Select-String 'saver/|settings'"`.
  - Expected: `ShabbatDisplay/saver/ShabbatDisplay.scr` and `ShabbatDisplay/settings.example.json` are there; `settings.json` is not.
- [ ] **Step 2: Check the setup script parses:** `powershell -NoProfile -Command "$null = [scriptblock]::Create((Get-Content setup-windows.ps1 -Raw)); 'ok'"`. Expected: `ok`.
- [ ] **Step 3: Run the full test suites.** Server: `C:\msys64\mingw64\bin\python.exe -m unittest discover -s tests`. App: `dotnet test manager\Manager.Tests`. Expected: both OK.
- [ ] **Step 4: Commit:** `git commit -am "Installer carries the screen saver; setup asks about Shabbat and locking; docs"`

### Task 8: Deploy and verify on the real PCs (stop for Avi's OK before each outward step)

No code. Each numbered item is a step that needs Avi's OK, using the deploy method that's already established: git bundle, then scp to `100.98.145.119`, then `git pull --ff-only` over ssh with `-EncodedCommand`, then POST `/api/manage/restart`.

1. **The always-on PC first,** because launchers on the new code expect `holy`.
   - Deploy Tasks 1 and 2 and restart.
   - Check `curl "http://100.98.145.119:8765/api/screen-settings?screen=Test-Probe&mode=always"` shows a `holy` list with the coming Shabbat. Then delete `Test-Probe` from the screens list, with the app or the API.
2. **This Surface:**
   - Add `"server_url": "http://100.98.145.119:8765"` to its settings.json.
   - Run `build-manager.bat`, which also builds the `.scr`.
   - Run `stop-display.bat`, then start the launcher again with the Startup shortcut's command.
   - Confirm no local `server.py` process is running.
   - In the app: Screens → Surface-Studio → Screen saver, with the wait, lock and Shabbat switch as Avi chooses → Save.
   - Within a minute, check `HKCU\Control Panel\Desktop` has `SCRNSAVE.EXE` pointing at the `.scr`.
   - Open `control desk.cpl,,@screensaver` and check it shows "ShabbatDisplay".
   - If Windows' dialog doesn't list it, record a ruling. Copying it to System32 needs admin, so ask Avi.
   - Let it start by itself, check both monitors and the built-in panel each show a different scene, then move the mouse. It closes and locks per the setting.
3. **Ariela's Acer,** when it answers on Tailscale:
   - Over ssh, check the policy key from Task 5 and `dsregcmd /status` (domain/Entra/MDM).
   - Then build the zip with `make-installer.bat` for Avi to upload. Ariela or Avi runs setup there; it needs a person at the PC.
4. **Push** main to GitHub only if Avi asks.
