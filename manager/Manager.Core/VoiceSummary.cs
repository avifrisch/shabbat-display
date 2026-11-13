using System.Globalization;

namespace Manager.Core;

/// <summary>The sentences the Voice assistant and Phones pages show.</summary>
public static class VoiceSummary
{
    private static string Usd(double d) => d.ToString(d is > 0 and < 0.01 ? "0.0000" : "0.00", CultureInfo.InvariantCulture);

    /// <summary>Whether the assistant answers, and if not, why.</summary>
    public static (string Text, bool Good) Assistant(VoiceState v)
    {
        if (!v.KeySet) return ("Off: no Claude key yet", false);
        if (!v.BudgetOk) return ("Stopped: the spending count on the display computer can't be read. Delete assistant-budget.json there to start the month's count again.", false);
        if (v.SpentUsd >= v.MonthlyUsd) return ("Stopped until next month: the monthly limit is reached", false);
        if (v.RequestsToday >= v.DailyRequests) return ("Stopped until tomorrow: today's limit is reached", false);
        return (v.Holy ? "Set up. Off now, as on every Shabbat and Yom Tov" : "On", true);
    }

    public static string Spent(VoiceState v) =>
        $"${Usd(v.SpentUsd)} of ${Usd(v.MonthlyUsd)} spent this month. {v.RequestsToday} of {v.DailyRequests} requests today.";

    /// <summary>Whether spoken announcements can reach the phones, and if not, what is missing.</summary>
    public static (string Text, bool Good) Push(PushSetup? p)
    {
        if (p is null || !p.Ready) return ("Not set up: the key file, key ID and team ID are all needed", false);
        if (!p.KeyFound) return ("The key file isn't on the display computer at that path", false);
        return (p.Critical ? "Set up, sounding through silent mode" : "Set up", true);
    }

    public static string Device(PushDevice d)
    {
        var name = d.Screen.Length > 0 ? d.Screen : "A device with no name";
        var build = d.Env == "development" ? "installed from the Mac" : "TestFlight or App Store";
        var when = d.At > 0 ? DateTimeOffset.FromUnixTimeSeconds(d.At).ToLocalTime().ToString("MMM d", CultureInfo.InvariantCulture) : "";
        return when.Length > 0 ? $"{name} · {build} · last registered {when}" : $"{name} · {build}";
    }

    /// <summary>The Alexa line on the Phones page, and whether it is good news.</summary>
    public static (string Text, bool Good) Alexa(AlexaSetup? a)
    {
        if (a is null) return ("The display server needs updating before it can send to Alexa.", false);
        var n = a.Devices.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries).Length;
        if (!a.TokenSet && n == 0) return ("Not set up.", false);
        if (!a.TokenSet) return ("The token is missing.", false);
        if (n == 0) return ("No speaker is chosen yet.", false);
        return (n == 1 ? "Set up: announcements are said on 1 speaker." : $"Set up: announcements are said on {n} speakers.", true);
    }
}
