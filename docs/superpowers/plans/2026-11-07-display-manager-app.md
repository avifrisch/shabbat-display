# Display Manager, part 2: the Windows app — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** "Shabbat Display Manager", a WinUI 3 app on Avi's PC. It drives the management API from part 1. Its pages are Status, Sports, Business, Screens, Shul, NYT and Server.

**Architecture:**
- A UI-free class library, `Manager.Core`, holds everything testable:
  - the API client, server discovery and the credential store;
  - the status sentences and the rotation editing rules.
- The WinUI app is thin pages bound to it.
- The app holds no data-source code. Team and stock search, and all data, come from the server.

**Tech Stack:**
- C# on .NET 8 (SDK 8.0.421 at `C:\Users\frisc\.dotnet`), with Windows App SDK 2.x and WinUI 3.
- Unpackaged (`WindowsPackageType=None`) and self-contained.
- WebView2 comes with the Windows App SDK. Tests use xUnit.
- Built with the `dotnet` CLI only; no Visual Studio.

**Spec:** `docs/superpowers/specs/2026-11-07-display-manager-design.md`. It depends on part 1, `docs/superpowers/plans/2026-11-07-display-manager-server.md`. Part 1's Task 2 route table is the contract.

## Global Constraints

- Everything lives under `manager/`. `build-manager.bat` is at the repo root. Both are export-ignored, so they're never in the installer zip.
- The access code is kept only in Windows Credential Manager, under target `ShabbatDisplayManager`.
  - It's never shown after entry and never written to a file or log.
  - The NYT cookie is never shown.
- Nothing changes on the screens until the page's Save. After a successful save, an InfoBar shows exactly "Saved. Screens update within a minute."
- Finding the server: first the remembered address (`%LOCALAPPDATA%\ShabbatDisplayManager\server.txt`), then `http://100.98.145.119:8765`, `http://DESKTOP-H72VKDJ:8765` and `http://192.168.4.109:8765`. Each is tried at `/health` with a 2-second timeout.
- Look: Mica backdrop, a left `NavigationView`, dark theme. The accent color is `#E5BA5E`.
- Test command: `dotnet test manager\Manager.Tests`, with `C:\Users\frisc\.dotnet` on PATH.
- The .NET 8 runtime reaches end of support on 2026-11-10. The self-contained build carries its own runtime and keeps working; it only talks to the house server. Moving to .NET 10 later is a one-line TargetFramework change.

## Review Focus

1. **The server unreachable, or answering 401, in the middle of a session** (the PC asleep, the code changed). Every page shows one plain sentence and keeps unsaved edits. Nothing crashes. *Test: Task 2, `Client_maps_errors_to_sentences`.*
2. **Saving while another device saved first.** The last save wins, and that's accepted. A save that fails (400) shows the server's own `error` text and keeps the edits. *Test: Task 2, `Bad_request_surfaces_server_error`.*
3. **A rotation edited down to nothing, or every scene switched off.** Save is refused in the app with "Choose at least one scene." *Test: Task 3, `Empty_rotation_cannot_be_saved`.*
4. **NYT sign-in refused inside WebView2.** The Paste box always works, and an empty or whitespace paste is refused. *Test: Task 2, `Cookie_paste_is_trimmed_and_required`.*
5. **A status response from an older server, missing fields** (the server not yet updated). The Status page still renders and says the server needs updating. *Test: Task 3, `Old_server_status_is_reported`.*

---

### Task 1: Scaffold and prove the build

**Files:**
- Create: `manager/Manager.sln`.
- Create: `manager/Manager.Core/Manager.Core.csproj` (`net8.0-windows`, nullable on).
- Create: `manager/Manager.Tests/Manager.Tests.csproj` (xUnit, referencing Core).
- Create: `manager/App/ShabbatManager.csproj`, `App.xaml(.cs)`, `MainWindow.xaml(.cs)`, `app.manifest`.
- Create: `build-manager.bat`.

**Interfaces:**
- Produces:
  - Project names that later tasks add files to.
  - `build-manager.bat`. It puts `%USERPROFILE%\.dotnet` on PATH, runs `dotnet test manager\Manager.Tests` (stopping on failure), then `dotnet publish manager\App\ShabbatManager.csproj -c Release -r win-x64 --self-contained -o dist\manager`. It then creates `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Shabbat Display Manager.lnk`, pointing at `dist\manager\ShabbatManager.exe`, through PowerShell `WScript.Shell`.
- `ShabbatManager.csproj` properties:
  - `OutputType` WinExe;
  - `TargetFramework` `net8.0-windows10.0.19041.0`;
  - `TargetPlatformMinVersion` 10.0.17763.0;
  - `UseWinUI` true;
  - `WindowsPackageType` None;
  - `WindowsAppSDKSelfContained` true;
  - `SelfContained` true;
  - `RuntimeIdentifier` win-x64;
  - `Platforms` x64.

  Packages: `Microsoft.WindowsAppSDK` (the newest stable 2.x from `dotnet package search Microsoft.WindowsAppSDK --exact-match`; 2.6.5 on 2026-11-07) and `Microsoft.Windows.SDK.BuildTools` (the newest).

- [ ] **Step 1: Write a placeholder test,** `Smoke.Core_loads()`. It asserts `typeof(Manager.Core.ManageClient)` isn't null. Run `dotnet test`. Expected: a compile FAIL, because `ManageClient` doesn't exist.
- [ ] **Step 2: Create the projects.** Add an empty `ManageClient` class, and a `MainWindow` with a `NavigationView` holding the seven items (Status, Sports, Business, Screens, Shul, NYT, Server) and Mica.
- [ ] **Step 3: Run `build-manager.bat`.**
  - Expected: the test passes, the publish succeeds, `dist\manager\ShabbatManager.exe` exists, and the shortcut exists.
  - Launch the exe, and take a screenshot with PowerShell `CopyFromScreen` into the scratchpad. It must show the window with the menu.
  - **If the dotnet CLI can't compile WinUI XAML,** stop and report the error. Don't switch frameworks on your own: the spec names WinUI 3.
- [ ] **Step 4: Commit** with the message "Display Manager: WinUI 3 app scaffold, core library, tests, build script".

---

### Task 2: Core: API client, server finder, credentials

**Files:**
- Create: `manager/Manager.Core/ManageClient.cs`, `Models.cs`, `ServerFinder.cs`, `CredentialStore.cs`.
- Test: `manager/Manager.Tests/ClientTests.cs`. It uses a `FakeHandler : HttpMessageHandler` that records requests and returns canned JSON.

**Interfaces:**
- Consumes: part 1's routes. The JSON is snake_case, so use `JsonSerializerOptions` with `JsonNamingPolicy.SnakeCaseLower`.
- Produces:
  - `record Team(int Id, string Abbr, string Name)`.
  - `record League(bool On, List<Team> Teams, int? Favorite)`.
  - `record Stock(string Symbol, string Name)`.
  - `record Business(bool On, List<Stock> Watchlist, Dictionary<string,bool> News)`.
  - `record RotationItem(string Scene, int Seconds, bool On)`.
  - `record SaverOptions(int Minutes, bool Lock, string Screens, bool KeepAwake)`.
  - `record Screen(List<RotationItem>? Rotation, bool Launcher, bool Saved, string Mode, SaverOptions Saver)`.
  - `record Household(Dictionary<string,League> Sports, Business Business, List<RotationItem> DefaultRotation, Dictionary<string,Screen> Screens, bool NytSignedIn, bool AgendaSet, Dictionary<string,string> Leagues, List<SceneInfo> Scenes)`.
  - `record SceneInfo(string Scene, string Label)`.
  - `record StatusResponse(...)`: the fields in part 1's `/api/manage/status`, all nullable so an older server still parses.
  - `class ManageClient(HttpClient http, Uri baseUri, string key)`, which sets the `X-Manage-Key` header. Its methods:
    - `GetStatusAsync()`, `GetHouseholdAsync()`;
    - `SaveSportsAsync(Dictionary<string,League>)`, `SaveBusinessAsync(Business)`;
    - `SaveRotationAsync(string? screen, List<RotationItem>? rotation)`, `SaveScreenAsync(string name, string mode, SaverOptions)`;
    - `SetNytCookieAsync(string cookie)` (`""` = sign out);
    - `UpdateShulAsync()`, `GetLogAsync(int lines)`, `RestartAsync()`;
    - `SearchTeamsAsync(string league, string q)`, `SearchStocksAsync(string q)`.

    Every method returns `Task<Result<T>>`.
  - `record Result<T>(T? Value, string? Error)`. `Error` is a sentence for the person:
    - 401: "The access code was refused. Enter it again."
    - 400: the server's `error`.
    - 409: the server's `error`.
    - timeout or connection failure: "The display server isn't answering. Is DESKTOP-H72VKDJ on?"
    - other: "The server answered <code>."
  - `static string? CleanCookie(string pasted)`. It trims; accepts `NYT-S=<v>` or a bare value; strips a trailing `;`. Empty → null.
  - `class ServerFinder(HttpClient http, string rememberFile)`, with `Task<Uri?> FindAsync()` (the order from Global Constraints; on success it writes `rememberFile`).
  - `static class CredentialStore`, with `string? Read()`, `void Write(string key)` and `void Delete()`. These P/Invoke `advapi32` `CredReadW`/`CredWriteW`/`CredDeleteW` with `CRED_TYPE_GENERIC`, target `ShabbatDisplayManager`, persist `LOCAL_MACHINE`.

- [ ] **Step 1: Write the failing tests.**

```csharp
[Fact] public async Task Sends_key_header() {
    var h = new FakeHandler("{\"ok\":true}"); var c = Client(h);
    await c.GetStatusAsync();
    Assert.Equal("k123", h.Last!.Headers.GetValues("X-Manage-Key").Single());
}
[Fact] public async Task Client_maps_errors_to_sentences() {
    Assert.Equal("The access code was refused. Enter it again.", (await Client(new FakeHandler("{}", 401)).GetStatusAsync()).Error);
    Assert.StartsWith("The display server isn't answering", (await Client(FakeHandler.Throws()).GetStatusAsync()).Error);
}
[Fact] public async Task Bad_request_surfaces_server_error() {
    var r = await Client(new FakeHandler("{\"ok\":false,\"error\":\"Unknown scene: nope\"}", 400)).SaveRotationAsync(null, new());
    Assert.Equal("Unknown scene: nope", r.Error);
}
[Fact] public void Cookie_paste_is_trimmed_and_required() {
    Assert.Equal("abc", ManageClient.CleanCookie("  NYT-S=abc; "));
    Assert.Equal("abc", ManageClient.CleanCookie("abc"));
    Assert.Null(ManageClient.CleanCookie("   "));
}
[Fact] public async Task Household_parses_snake_case() {
    var json = "{\"sports\":{\"nba\":{\"on\":true,\"teams\":[{\"id\":18,\"abbr\":\"NY\",\"name\":\"New York Knicks\"}],\"favorite\":18}},\"business\":{\"on\":true,\"watchlist\":[],\"news\":{}},\"default_rotation\":[{\"scene\":\"shul\",\"seconds\":30,\"on\":true}],\"screens\":{},\"nyt_signed_in\":false,\"agenda_set\":true,\"leagues\":{},\"scenes\":[]}";
    var h = (await Client(new FakeHandler(json)).GetHouseholdAsync()).Value!;
    Assert.Equal(18, h.Sports["nba"].Favorite); Assert.Equal(30, h.DefaultRotation[0].Seconds);
}
[Fact] public async Task Finder_tries_in_order_and_remembers() {
    var h = FakeHandler.ByHost(new() { ["100.98.145.119"] = 0, ["desktop-h72vkdj"] = 200 });  // 0 = connection fails
    var file = Path.GetTempFileName();
    var u = await new ServerFinder(new HttpClient(h), file).FindAsync();
    Assert.Equal("desktop-h72vkdj", u!.Host.ToLowerInvariant());
    Assert.Contains("DESKTOP-H72VKDJ", File.ReadAllText(file), StringComparison.OrdinalIgnoreCase);
}
```

- [ ] **Step 2: Run them and watch them fail.** `dotnet test manager\Manager.Tests`. Expected: compile errors for the missing types.
- [ ] **Step 3: Implement it as specified.** `CredentialStore` has no unit test, since it touches the real vault; it's checked by hand in Task 3.
- [ ] **Step 4: Run the tests.** Expected: all pass.
- [ ] **Step 5: Commit** with the message "Display Manager core: API client, server finder, Credential Manager store".

---

### Task 3: Connect, Status page, and the editing rules

**Files:**
- Create: `manager/Manager.Core/StatusSummary.cs`, `RotationEditor.cs`.
- Create: `manager/App/ConnectDialog.xaml(.cs)`, `Pages/StatusPage.xaml(.cs)`, `AppState.cs`.
  - `AppState` is one shared `ManageClient`. It's created on start: `ServerFinder` runs, then the key comes from `CredentialStore`; when it's missing, or when any call answers 401, `ConnectDialog` opens.
- Test: `manager/Manager.Tests/SummaryTests.cs`, `RotationTests.cs`.

**Interfaces:**
- Produces:
  - `record Problem(string Level, string Text)`, where `Level` is "red" or "amber".
  - `static List<Problem> StatusSummary.Problems(StatusResponse s, DateTimeOffset now)`:
    - A feed with `ok == false` whose `failed_at` is more than 30 minutes ago → amber, "<feed label> hasn't updated since <h:mm tt>: <error>".
      - The labels map source keys to words: `weather` "Weather", `sport_nba` "NBA scores", `markets` "Stock prices", `shul` "Shul files", and so on.
    - `shul.problem` set → amber, with that text.
    - A launcher screen not seen for more than 10 minutes → amber, "<name> hasn't checked in since <time>."
    - A missing `feeds` or `screens` field → red, "The display server needs updating to work with this app."
    - An empty list means the page shows "Everything is working."
  - `class RotationEditor(List<RotationItem> items, IReadOnlyList<SceneInfo> catalog)`:
    - `MoveUp(i)`, `MoveDown(i)`, `Toggle(i)`;
    - `SetSeconds(i, s)`, which clamps to 5–300;
    - `AddMissingFromCatalog()`, which appends catalog scenes that aren't present, switched off;
    - `string? Validate()`, which returns "Choose at least one scene." when no item is on;
    - `List<RotationItem> Items`.
  - The Status page:
    - a big line: "Everything is working.", or the count of problems;
    - the problem list, colored;
    - below it, three small sections:
      - Feeds: each feed's name and last update, relative;
      - Shul: this week's files;
      - Screens: name and last seen.
    - A Refresh button. It also refreshes when opened.

- [ ] **Step 1: Write the failing tests.**

```csharp
[Fact] public void Failed_feed_is_amber_after_30_minutes() {
    var s = Status(feeds: new() { ["sport_nba"] = Feed(ok: false, failedMinutesAgo: 45, error: "HTTP 503") });
    var p = StatusSummary.Problems(s, Now).Single();
    Assert.Equal("amber", p.Level); Assert.StartsWith("NBA scores hasn't updated since", p.Text); Assert.EndsWith("HTTP 503", p.Text);
}
[Fact] public void Unreadable_bulletin_is_reported() {
    var s = Status(shulProblem: "This week's bulletin downloaded, but its Shabbat times couldn't be read.");
    Assert.Contains(StatusSummary.Problems(s, Now), p => p.Text.Contains("couldn't be read"));
}
[Fact] public void Silent_launcher_is_amber() {
    var s = Status(screens: new() { Screen("Ariela's Acer", launcher: true, seenMinutesAgo: 25) });
    Assert.Equal("Ariela's Acer hasn't checked in since " + Now.AddMinutes(-25).ToLocalTime().ToString("h:mm tt") + ".", StatusSummary.Problems(s, Now).Single().Text);
}
[Fact] public void Old_server_status_is_reported() {
    var s = new StatusResponse { Ok = true };   // no feeds, no screens
    Assert.Equal("red", StatusSummary.Problems(s, Now).Single().Level);
}
[Fact] public void Empty_rotation_cannot_be_saved() {
    var e = new RotationEditor(new() { new("news", 30, true) }, Catalog);
    e.Toggle(0); Assert.Equal("Choose at least one scene.", e.Validate());
}
[Fact] public void Seconds_are_clamped_and_moves_work() {
    var e = new RotationEditor(new() { new("shul", 30, true), new("news", 30, true) }, Catalog);
    e.SetSeconds(0, 2); e.MoveDown(0);
    Assert.Equal(new[] { "news", "shul" }, e.Items.Select(i => i.Scene)); Assert.Equal(5, e.Items[1].Seconds);
}
```

- [ ] **Step 2: Run them and watch them fail.**
- [ ] **Step 3: Implement the Core classes, then ConnectDialog, AppState and StatusPage.**
  - ConnectDialog has a PasswordBox for the access code and the text "The access code is printed at the end of setup on DESKTOP-H72VKDJ." It saves through `CredentialStore.Write` only after a successful `GetStatusAsync`.
- [ ] **Step 4: Run the tests (green), then `build-manager.bat`.**
  - Manual check against the local server from part 1: the first launch asks for the code; Status shows the feeds; relaunching doesn't ask again.
  - `cmdkey /list | findstr ShabbatDisplayManager` shows the entry.
- [ ] **Step 5: Commit** with the message "Display Manager: connect with access code, Status page with plain-language problems".

---

### Task 4: Sports and Business pages

**Files:**
- Create: `manager/App/Pages/SportsPage.xaml(.cs)`, `Pages/BusinessPage.xaml(.cs)`.
- Create: `manager/Manager.Core/Watchlist.cs`.
- Test: `manager/Manager.Tests/WatchlistTests.cs`.

**Interfaces:**
- Consumes: `GetHouseholdAsync`, `SaveSportsAsync`, `SearchTeamsAsync`, `SaveBusinessAsync`, `SearchStocksAsync`.
- Produces:
  - The Sports page: one `Expander` per league, MLB first, then `household.Leagues` in order. The header shows the name and an on/off `ToggleSwitch`. The body holds:
    - the chosen teams as rows: name, a ☆/★ button that sets the favorite (exactly one when the list isn't empty), and remove;
    - an `AutoSuggestBox` "Add a team". It searches `SearchTeamsAsync` after 250 ms of no typing; picking a result adds it, and the first team added becomes the favorite;
    - Save, which sends all leagues.

    The note under the list: "A league shows only in its season. Switching a league on adds it to screens that use the house rotation."
  - The Business page:
    - an on/off switch;
    - the watchlist: rows of symbol and name, with up, down and remove;
    - an `AutoSuggestBox` "Add a stock (ticker or company)", through `SearchStocksAsync`;
    - a switch each for "New York Times Business" and "CNBC";
    - Save;
    - the note "Prices are delayed. The first search downloads the SEC's list of companies."
  - `class Watchlist(List<Stock>)`, with `Add(Stock)` (ignores duplicates, max 30), `Move(int from, int to)` and `Remove(int)`.

- [ ] **Step 1: Write the failing tests.** `Add_ignores_duplicates_and_caps_at_30`; `Move_reorders`.
- [ ] **Step 2: Run them and watch them fail.** **Step 3: Implement the Watchlist and both pages.**
- [ ] **Step 4: Tests green.** Manual check against the local server:
  - Turn on NBA, add the Knicks, and Save. The InfoBar text is exact. `household.json` has `nba.on: true` and `nba_team` in `default_rotation`.
  - Add AAPL from "apple", then Save. Note this makes the first real SEC request, which Avi approved.
- [ ] **Step 5: Commit** with the message "Display Manager: Sports and Business pages".

---

### Task 5: Screens page

**Files:**
- Create: `manager/App/Pages/ScreensPage.xaml(.cs)`.

**Interfaces:**
- Consumes: `GetHouseholdAsync`, `GetStatusAsync` (for last seen), `SaveRotationAsync`, `SaveScreenAsync`, `RotationEditor`.
- Produces:
  - The left list: "House rotation (default)", then every screen. Each shows its name, "seen 3 min ago", and "PC" or "Browser" (from `launcher`).
  - The right pane for a screen:
    1. **Rotation.** A "Use the house rotation" toggle. When it's off, a list of scenes with a checkbox, label, seconds `NumberBox` (5–300) and up/down buttons.
       - Switching it off copies the house rotation as a start. `AddMissingFromCatalog()` runs, so new league scenes appear, switched off.
       - The Agenda row says "Private: shows your calendar on this screen."
    2. **For PCs only:** mode, as a `RadioButtons` choice of "Always on" or "Screen saver".
       - Screen saver adds idle minutes (`NumberBox` 1–240), "Lock Windows when it closes", the monitor (`ComboBox`: All screens / Plugged-in monitor only), and "Keep the PC awake and the screens on while it shows".
       - Until a screen is saved, the pane shows "Showing this PC's own settings. Nothing changes until you save."
    3. **Save.** It validates through `RotationEditor.Validate()`, then calls `SaveRotationAsync` (null rotation when it uses the house rotation), then `SaveScreenAsync` for PCs.
  - For the house default, only the rotation editor shows.

- [ ] **Step 1: Write the failing test** in `RotationTests`, `Copy_of_house_rotation_gets_new_scenes_off`. Start with the house list `[shul on]` and a catalog of `[shul, nba_team, nba]`. After the copy and `AddMissingFromCatalog`, expect `nba_team` and `nba` present with `On == false`.
- [ ] **Step 2: Run it and watch it fail** (if `AddMissingFromCatalog` doesn't already cover it, fix it). **Step 3: Implement the page.**
- [ ] **Step 4: Tests green.** Manual check:
  - Give a test screen a custom rotation with Agenda on and Save. `/api/state?screen=<name>` then includes the agenda data.
  - Switch it to screen saver for 1 minute and Save. A launcher running locally (part 1, Task 9) follows within about 70 seconds.
- [ ] **Step 5: Commit** with the message "Display Manager: Screens page with rotation editor and screen-saver options".

---

### Task 6: Shul, Server and NYT pages; finish

**Files:**
- Create: `manager/App/Pages/ShulPage.xaml(.cs)`, `Pages/ServerPage.xaml(.cs)`, `Pages/NytPage.xaml(.cs)`.
- Modify: `CLAUDE.md` and `README.md`. Add a "Display Manager app" section: build with `build-manager.bat`, where the access code comes from, and what each page does.

**Interfaces:**
- Consumes: `GetStatusAsync().Shul`, `UpdateShulAsync`, `GetLogAsync`, `RestartAsync`, `SetNytCookieAsync`, `CleanCookie`.
- Produces:
  - **The Shul page.** Three rows: Weekly chart, Bulletin and Calendar. Each row has:
    - the file name and when it arrived;
    - a ✓ in green ("this week" / "this Shabbat, 24 times read" / "this month"), or amber with the problem sentence.

    "Update now" shows a ProgressRing. When it finishes it shows the new summary; a 409 shows the server's sentence. "Open" opens `<server>/shul/<file>` in the default browser.
  - **The Server page.**
    - A table of feeds: name, last update, OK or the error.
    - The last 200 log lines, monospace, with a Refresh button.
    - Restart, behind a `ContentDialog`: "Restart the display server? The screens keep showing their last data and catch up in about a minute."
      - After a restart it polls `/health` every 2 seconds for up to 60 seconds, then shows "Server restarted." or "The server hasn't come back. Check DESKTOP-H72VKDJ."
  - **The NYT page.** "Signed in" or "Signed out", with Sign in and Sign out buttons.
    - Sign in opens a `WebView2`, with a user data folder in `%LOCALAPPDATA%\ShabbatDisplayManager\WebView2`, at `https://myaccount.nytimes.com/auth/login`.
      - After each `NavigationCompleted`, the page calls `CookieManager.GetCookiesAsync("https://www.nytimes.com")`. When `NYT-S` appears, it sends it with `SetNytCookieAsync`, closes the view and shows "Signed in".
    - Sign out sends `""` and deletes the WebView2 cookies.
    - An expander, "Sign-in page not working?", holds a PasswordBox and the instruction: "In a browser signed in to nytimes.com, open Developer tools → Application → Cookies → nytimes.com and copy the value of NYT-S." Save sends `CleanCookie(text)`; a null result shows "Paste the NYT-S value first."

- [ ] **Step 1: Write the failing test,** `Shul_row_text`. It belongs in Core, `ShulRows.From(StatusResponse.Shul)`, which returns three `(Title, Detail, Ok, Text)`. For a bulletin with `rows: 24` and `this_shabbat: true`, expect `"this Shabbat, 24 times read"`. With `rows: null`, expect `Ok == false` and the text to be the `problem` sentence.
- [ ] **Step 2: Run it and watch it fail.** **Step 3: Implement `ShulRows` and the three pages.**
- [ ] **Step 4: Tests green, then `build-manager.bat`.** Manual check:
  - Shul shows this week's files.
  - The log appears.
  - Restart comes back (local server under the launcher).
  - NYT sign-in: try the embedded page. If NYT blocks it, record that in the commit message and confirm the Paste path works. Then check `/api/manage/household` shows `nyt_signed_in: true`, and that the cookie appears nowhere in the response or `server.log`.
- [ ] **Step 5: Commit** with the message "Display Manager: Shul, Server and NYT pages; docs".
- [ ] **Step 6: Hand over.**
  - Run `build-manager.bat` on Avi's PC and pin the Start-menu shortcut.
  - Avi types the access code from part 1's deploy. Then turn on what his daughter wants (basketball) together.
