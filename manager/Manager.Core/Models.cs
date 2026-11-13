namespace Manager.Core;

// The management API's JSON, from the server's /api/manage/* routes (snake_case on the wire).

public record Team(int Id, string Abbr, string Name);

public record League(bool On, List<Team> Teams, int? Favorite);

public record Stock(string Symbol, string Name);

public record Business(bool On, List<Stock> Watchlist, Dictionary<string, bool> News);

public record RotationItem(string Scene, int Seconds, bool On);

/// <summary>Windows' screen saver on a PC: its wait, whether Windows locks when it closes, and the Shabbat switch.</summary>
public record SaverOptions(int Minutes, bool Lock, bool Shabbat);

/// <summary>What a PC's own settings.json says, sent by its launcher.</summary>
public record LocalSettings(string? Mode, SaverOptions? Saver);

/// <summary>Until a screen is saved in the app, the PC follows its own settings (Local), not Mode and Saver.</summary>
/// Announce: the PC says announcements aloud (on unless switched off; a server from before the switch doesn't send it).
public record Screen(List<RotationItem>? Rotation, bool Launcher, bool Saved, string Mode, SaverOptions Saver, LocalSettings? Local = null, bool Announce = true)
{
    public LocalSettings Effective => !Saved && Local is { } l
        ? new(l.Mode ?? "always", l.Saver ?? Saver)
        : new(Mode ?? "always", Saver);
}

public record SceneInfo(string Scene, string Label);

public record Household(
    Dictionary<string, League> Sports,
    Business Business,
    List<RotationItem> DefaultRotation,
    Dictionary<string, Screen> Screens,
    bool NytSignedIn,
    bool AgendaSet,
    Dictionary<string, string> Leagues,
    List<SceneInfo> Scenes);

/// <summary>/api/manage/status. Everything may be missing when the server is older than the app.</summary>
public class StatusResponse
{
    public bool Ok { get; init; }
    public double? Started { get; init; }
    public Dictionary<string, FeedStatus>? Feeds { get; init; }
    public ShulStatus? Shul { get; init; }
    public List<ScreenStatus>? Screens { get; init; }
}

/// <summary>Times are Unix seconds.</summary>
public record FeedStatus(bool? Ok, double? Updated, string? Error, double? FailedAt);

public record ScreenStatus(string Name, double? Last, bool Launcher, string? Mode, bool Saved);

public record ShulStatus(ShulChart? Chart, ShulBulletin? Bulletin, List<ShulCalendar>? Calendars, string? Problem);

public record ShulChart(string? File, string? Date, bool ThisWeek);

public record ShulBulletin(string? File, string? Date, bool ThisShabbat, int? Rows);

public record ShulCalendar(string? File, bool ThisMonth);

public record ShulUpdate(string? Summary, ShulStatus? Shul);

/// <summary>A value, or a sentence for the person saying why there isn't one.</summary>
public record Result<T>(T? Value, string? Error)
{
    public bool Ok => Error is null;
}

/// <summary>One of the family's lists. Kind is "shopping" or "todo"; the first list is the main shopping list.</summary>
public record ShopList(string Id, string Name, string Kind, List<string> Items)
{
    public bool IsTodo => Kind == "todo";
}

/// <summary>A usual Walmart item. ItemId is Walmart's product number, "" until a link is given.</summary>
public record UsualItem(string Id, string Name, string ItemId, int Qty)
{
    public string Label => Qty > 1 ? $"{Qty} × {Name}" : Name;
}

/// <summary>A named set of usual items ("Weekly", "Shabbat").</summary>
public record UsualSet(string Id, string Name, List<UsualItem> Items);

/// <summary>GET and POST /api/manage/lists: every list and every set of usual items.</summary>
public record ListsState(List<ShopList>? Lists, List<UsualSet>? Sets);

/// <summary>The Apple push key as the display computer has it. KeyFile is a path on that computer; KeyFound is whether a file is there.</summary>
public record PushSetup(string KeyFile, string KeyId, string TeamId, bool Critical, bool Ready, bool KeyFound);

/// <summary>A phone or tablet that asked for announcements. Env is "production" (TestFlight, App Store) or "development" (installed from Xcode).</summary>
public record PushDevice(string Id, string Screen, string Env, long At);

/// <summary>GET and POST /api/manage/voice: the voice assistant and the announcements, with no secret in it.</summary>
public record VoiceState(bool KeySet, double MonthlyUsd, int DailyRequests, bool BudgetOk, double SpentUsd, int RequestsToday,
                         PushSetup? Push, bool NtfySet, bool MenuappSet, List<PushDevice>? Devices, bool Holy, string? Note,
                         AlexaSetup? Alexa = null);

/// <summary>Announcements on Echo devices through Voice Monkey: whether its token is saved, and the speaker IDs, comma separated.</summary>
public record AlexaSetup(bool TokenSet, string Devices);
