using System.Globalization;
using System.Text.Json;

namespace Manager.Core;

// The logic of ShabbatDisplay.scr, kept here so it can be tested without a window.

public enum SaverAction { Show, Preview, Configure }

/// <summary>What Windows asked for: /s show, /p HWND preview in that window, /c (or nothing) settings.</summary>
public record SaverLaunch(SaverAction Action, nint Parent)
{
    public static SaverLaunch Parse(string[] args)
    {
        if (args.Length == 0) return new(SaverAction.Configure, 0);
        var first = args[0].Trim();
        var flag = first.Length >= 2 && first[0] is '/' or '-' ? char.ToLowerInvariant(first[1]) : ' ';
        var rest = first.Length > 3 && first[2] == ':' ? first[3..] : args.Length > 1 ? args[1] : "";
        return flag switch
        {
            's' => new(SaverAction.Show, 0),
            'p' when long.TryParse(rest, NumberStyles.Integer, CultureInfo.InvariantCulture, out var h) => new(SaverAction.Preview, (nint)h),
            _ => new(SaverAction.Configure, 0),
        };
    }
}

/// <summary>From a candle lighting to havdalah.</summary>
public record HolySpan(DateTimeOffset Start, DateTimeOffset End);

/// <summary>saver.json, written next to the .scr by the launcher. Nothing secret is in it.</summary>
public record SaverConfig(Uri Url, string Screen, bool Shabbat, List<HolySpan> Holy)
{
    /// <summary>Null when the file isn't usable: bad JSON, or no http(s) address.</summary>
    public static SaverConfig? Load(string json)
    {
        try
        {
            using var doc = JsonDocument.Parse(json);
            var root = doc.RootElement;
            if (root.ValueKind != JsonValueKind.Object) return null;
            if (!root.TryGetProperty("url", out var u) || u.ValueKind != JsonValueKind.String
                || !Uri.TryCreate(u.GetString(), UriKind.Absolute, out var url) || url.Scheme is not ("http" or "https"))
                return null;
            var screen = root.TryGetProperty("screen", out var s) && s.ValueKind == JsonValueKind.String ? s.GetString() ?? "" : "";
            var shabbat = root.TryGetProperty("shabbat", out var b) && b.ValueKind == JsonValueKind.True;
            var holy = new List<HolySpan>();
            if (root.TryGetProperty("holy", out var h) && h.ValueKind == JsonValueKind.Array)
                foreach (var span in h.EnumerateArray())
                    if (span.ValueKind == JsonValueKind.Object
                        && span.TryGetProperty("start", out var a) && DateTimeOffset.TryParse(a.GetString(), CultureInfo.InvariantCulture, DateTimeStyles.None, out var start)
                        && span.TryGetProperty("end", out var e) && DateTimeOffset.TryParse(e.GetString(), CultureInfo.InvariantCulture, DateTimeStyles.None, out var end))
                        holy.Add(new(start, end));
            return new(url, screen, shabbat, holy);
        }
        catch (Exception ex) when (ex is JsonException or InvalidOperationException)
        {
            return null;
        }
    }

    /// <summary>Shabbat or Yom Tov now, with the switch on: input is ignored and nothing locks.</summary>
    public bool IsHoly(DateTimeOffset now) => Shabbat && Holy.Any(s => s.Start <= now && now < s.End);

    /// <summary>From midnight of the candle-lighting day to havdalah, with the switch on: the screens stay on,
    /// so a modern-standby laptop never sleeps (and locks) before Shabbat.</summary>
    public bool HoldScreens(DateTimeOffset now) =>
        Shabbat && Holy.Any(s => new DateTimeOffset(s.Start.DateTime.Date, s.Start.Offset) <= now && now < s.End);

    /// <summary>The display page for monitor number shift: look-only, and that many scenes in.</summary>
    public Uri PageUrl(int shift) =>
        new(Url, "?screen=" + Uri.EscapeDataString(Screen) + "&saver=1&shift=" + shift.ToString(CultureInfo.InvariantCulture));
}

/// <summary>Closes the screen saver on new input (GetLastInputInfo's tick), except over Shabbat and Yom Tov.
/// Input during Shabbat moves the baseline, so it doesn't count once havdalah comes.</summary>
public sealed class InputGate(uint startTick)
{
    private uint baseline = startTick;

    public bool ShouldClose(uint tick, bool holy)
    {
        if (holy) { baseline = tick; return false; }
        return tick != baseline;
    }
}
