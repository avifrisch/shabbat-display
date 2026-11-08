using Manager.Core;

namespace Manager.Tests;

public class ShulTests
{
    private const string Unreadable = "This week's bulletin downloaded, but its Shabbat times couldn't be read.";

    [Fact]
    public void Shul_row_text()
    {
        var s = new ShulStatus(new ShulChart("Nov1-weeklydavening.png", "2026-11-01", true),
                               new ShulBulletin("7Nov-ChayeiSarah.pdf", "2026-11-07", true, 24),
                               [new ShulCalendar("November2026.jpg", true)], null);
        var rows = ShulRows.From(s);
        Assert.Equal(new[] { "Weekly chart", "Bulletin", "Calendar" }, rows.Select(r => r.Title));
        Assert.All(rows, r => Assert.True(r.Ok));
        Assert.Equal("this week", rows[0].Text);
        Assert.Equal("this Shabbat, 24 times read", rows[1].Text);
        Assert.Equal("7Nov-ChayeiSarah.pdf", rows[1].Detail);
        Assert.Equal("this month", rows[2].Text);
    }

    [Fact]
    public void Unreadable_bulletin_row_gives_the_problem()
    {
        var s = new ShulStatus(null, new ShulBulletin("7Nov-ChayeiSarah.pdf", "2026-11-07", true, null), [], Unreadable);
        var b = ShulRows.From(s)[1];
        Assert.False(b.Ok);
        Assert.Equal(Unreadable, b.Text);
    }

    [Fact]
    public void Missing_files_are_not_ok()
    {
        var rows = ShulRows.From(new ShulStatus(null, null, null, null));
        Assert.All(rows, r => Assert.False(r.Ok));
        Assert.Equal("not downloaded", rows[0].Text);
    }

    [Fact]
    public void Last_weeks_files_say_so()
    {
        var s = new ShulStatus(new ShulChart("Oct25-weeklydavening.png", "2026-10-25", false),
                               new ShulBulletin("31Oct-Vayera.pdf", "2026-10-31", false, 22), [new ShulCalendar("October2026.jpg", false)], null);
        var rows = ShulRows.From(s);
        Assert.Equal(new[] { "not this week's", "not this Shabbat's", "not this month's" }, rows.Select(r => r.Text));
    }
}
