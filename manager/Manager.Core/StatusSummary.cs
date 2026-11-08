namespace Manager.Core;

public record Problem(string Level, string Text);

/// <summary>Turns /api/manage/status into plain sentences about what needs attention.</summary>
public static class StatusSummary
{
    private static readonly Dictionary<string, string> Labels = new()
    {
        ["weather"] = "Weather",
        ["nws"] = "Weather forecast",
        ["alerts"] = "Weather alerts",
        ["zmanim"] = "Zmanim",
        ["hebdate"] = "Hebrew date",
        ["calendar"] = "Jewish calendar",
        ["team"] = "MLB team",
        ["standings"] = "MLB standings",
        ["scoreboard"] = "MLB scores",
        ["transactions"] = "MLB transactions",
        ["yankees_news"] = "Team news",
        ["mlb_news"] = "MLB news",
        ["nyt"] = "NYT headlines",
        ["cnn"] = "CNN headlines",
        ["toi"] = "Times of Israel",
        ["agenda"] = "Agenda",
        ["shul"] = "Shul files",
        ["markets"] = "Stock prices",
        ["biz_nyt"] = "NYT Business",
        ["biz_cnbc"] = "CNBC",
        ["sport_nba"] = "NBA scores",
        ["sport_wnba"] = "WNBA scores",
        ["sport_nfl"] = "NFL scores",
        ["sport_nhl"] = "NHL scores",
        ["sport_mls"] = "MLS scores",
        ["sport_ncaam"] = "Men's college basketball scores",
        ["sport_ncaaw"] = "Women's college basketball scores",
        ["sport_ncaaf"] = "College football scores",
    };

    public static string FeedLabel(string key) => Labels.TryGetValue(key, out var l) ? l : key;

    public static List<Problem> Problems(StatusResponse s, DateTimeOffset now)
    {
        if (s.Feeds is null || s.Screens is null)
            return [new("red", ManageClient.NeedsUpdate)];
        var list = new List<Problem>();
        foreach (var (key, f) in s.Feeds.OrderBy(kv => FeedLabel(kv.Key)))
        {
            if (f.Ok != false || f.FailedAt is null || now - When(f.FailedAt.Value) < TimeSpan.FromMinutes(30)) continue;
            var since = f.Updated is { } u ? "hasn't updated since " + Clock(u, now) : "hasn't loaded yet";
            list.Add(new("amber", $"{FeedLabel(key)} {since}: {f.Error}"));
        }
        if (s.Shul?.Problem is { Length: > 0 } shul)
            list.Add(new("amber", shul));
        foreach (var sc in s.Screens.Where(x => x.Launcher))
        {
            if (sc.Last is { } last && now - When(last) > TimeSpan.FromMinutes(10))
                list.Add(new("amber", $"{sc.Name} hasn't checked in since {Clock(last, now)}."));
            else if (sc.Last is null && s.Started is { } started && now - When(started) > TimeSpan.FromMinutes(10))
                list.Add(new("amber", $"{sc.Name} hasn't checked in since the server started."));
        }
        return list;
    }

    public static DateTimeOffset When(double unixSeconds) => DateTimeOffset.FromUnixTimeMilliseconds((long)(unixSeconds * 1000));

    /// <summary>"3:05 PM" today, "Fri 3:05 PM" another day.</summary>
    public static string Clock(double unixSeconds, DateTimeOffset now)
    {
        var t = When(unixSeconds).ToLocalTime();
        return t.Date == now.ToLocalTime().Date ? t.ToString("h:mm tt") : t.ToString("ddd h:mm tt");
    }

    /// <summary>"just now", "4 min ago", "3 hr ago", "2 days ago".</summary>
    public static string Ago(double? unixSeconds, DateTimeOffset now)
    {
        if (unixSeconds is null) return "never";
        var d = now - When(unixSeconds.Value);
        if (d < TimeSpan.FromMinutes(1)) return "just now";
        if (d < TimeSpan.FromHours(1)) return $"{(int)d.TotalMinutes} min ago";
        if (d < TimeSpan.FromDays(2)) return $"{(int)d.TotalHours} hr ago";
        return $"{(int)d.TotalDays} days ago";
    }
}
