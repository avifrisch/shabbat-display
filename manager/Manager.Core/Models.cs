namespace Manager.Core;

// The management API's JSON, from the server's /api/manage/* routes (snake_case on the wire).

public record Team(int Id, string Abbr, string Name);

public record League(bool On, List<Team> Teams, int? Favorite);

public record Stock(string Symbol, string Name);

public record Business(bool On, List<Stock> Watchlist, Dictionary<string, bool> News);

public record RotationItem(string Scene, int Seconds, bool On);

public record SaverOptions(int Minutes, bool Lock, string Screens, bool KeepAwake);

/// <summary>What a PC's own settings.json says, sent by its launcher.</summary>
public record LocalSettings(string? Mode, SaverOptions? Saver);

/// <summary>Until a screen is saved in the app, the PC follows its own settings (Local), not Mode and Saver.</summary>
public record Screen(List<RotationItem>? Rotation, bool Launcher, bool Saved, string Mode, SaverOptions Saver, LocalSettings? Local = null)
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
