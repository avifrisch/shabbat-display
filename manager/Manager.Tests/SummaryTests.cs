using Manager.Core;

namespace Manager.Tests;

public class SummaryTests
{
    private static readonly DateTimeOffset Now = new(2026, 11, 8, 15, 0, 0, TimeSpan.FromHours(-5));

    private static double Ago(int minutes) => Now.AddMinutes(-minutes).ToUnixTimeSeconds();

    private static FeedStatus Feed(bool ok = true, int failedMinutesAgo = 0, string? error = null, int updatedMinutesAgo = 120) =>
        new(ok, Ago(updatedMinutesAgo), error, ok ? null : Ago(failedMinutesAgo));

    private static ScreenStatus Screen(string name, bool launcher, int seenMinutesAgo) => new(name, Ago(seenMinutesAgo), launcher, "always", false);

    private static StatusResponse Status(Dictionary<string, FeedStatus>? feeds = null, string? shulProblem = null, List<ScreenStatus>? screens = null) => new()
    {
        Ok = true,
        Started = Ago(600),
        Feeds = feeds ?? new() { ["weather"] = Feed() },
        Shul = new ShulStatus(null, null, [], shulProblem),
        Screens = screens ?? [],
    };

    [Fact]
    public void Everything_working_is_no_problems() => Assert.Empty(StatusSummary.Problems(Status(), Now));

    [Fact]
    public void Failed_feed_is_amber_after_30_minutes()
    {
        var s = Status(feeds: new() { ["sport_nba"] = Feed(ok: false, failedMinutesAgo: 45, error: "HTTP 503") });
        var p = StatusSummary.Problems(s, Now).Single();
        Assert.Equal("amber", p.Level); Assert.StartsWith("NBA scores hasn't updated since", p.Text); Assert.EndsWith("HTTP 503", p.Text);
    }

    [Fact]
    public void Brief_feed_failure_is_not_reported()
    {
        var s = Status(feeds: new() { ["weather"] = Feed(ok: false, failedMinutesAgo: 5, error: "timed out") });
        Assert.Empty(StatusSummary.Problems(s, Now));
    }

    [Fact]
    public void Unreadable_bulletin_is_reported()
    {
        var s = Status(shulProblem: "This week's bulletin downloaded, but its Shabbat times couldn't be read.");
        Assert.Contains(StatusSummary.Problems(s, Now), p => p.Text.Contains("couldn't be read"));
    }

    [Fact]
    public void Silent_launcher_is_amber()
    {
        var s = Status(screens: [Screen("Ariela's Acer", launcher: true, seenMinutesAgo: 25)]);
        Assert.Equal("Ariela's Acer hasn't checked in since " + Now.AddMinutes(-25).ToLocalTime().ToString("h:mm tt") + ".", StatusSummary.Problems(s, Now).Single().Text);
    }

    [Fact]
    public void Silent_browser_screen_is_fine() =>
        Assert.Empty(StatusSummary.Problems(Status(screens: [Screen("Kitchen iPad", launcher: false, seenMinutesAgo: 600)]), Now));

    [Fact]
    public void Old_server_status_is_reported()
    {
        var s = new StatusResponse { Ok = true };   // no feeds, no screens
        var p = StatusSummary.Problems(s, Now).Single();
        Assert.Equal("red", p.Level);
        Assert.Equal("The display server needs updating to work with this app.", p.Text);
    }

    [Fact]
    public void Feed_labels_are_words()
    {
        Assert.Equal("Stock prices", StatusSummary.FeedLabel("markets"));
        Assert.Equal("WNBA scores", StatusSummary.FeedLabel("sport_wnba"));
        Assert.Equal("something_new", StatusSummary.FeedLabel("something_new"));
    }
}
