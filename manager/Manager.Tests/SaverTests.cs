using Manager.Core;

namespace Manager.Tests;

public class SaverTests
{
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

    private const string Json = """
        {"url":"http://100.98.145.119:8765/","screen":"Ariela's Acer","shabbat":true,
         "holy":[{"start":"2026-11-13T16:17:00-05:00","end":"2026-11-14T17:20:00-05:00"}]}
        """;

    private static DateTimeOffset T(string s) => DateTimeOffset.Parse(s);

    [Fact]
    public void Load_rejects_bad_files()
    {
        Assert.Null(SaverConfig.Load("{}"));
        Assert.Null(SaverConfig.Load("not json"));
        Assert.Null(SaverConfig.Load("""{"url":"file:///c:/x"}"""));
    }

    [Fact]
    public void PageUrl_has_screen_saver_and_shift() =>
        Assert.Equal("http://100.98.145.119:8765/?screen=Ariela%27s%20Acer&saver=1&shift=1", SaverConfig.Load(Json)!.PageUrl(1).AbsoluteUri);

    [Fact]
    public void Holy_only_inside_the_span_and_with_the_switch_on()
    {
        var c = SaverConfig.Load(Json)!;
        Assert.False(c.IsHoly(T("2026-11-13T16:00:00-05:00")));
        Assert.True(c.IsHoly(T("2026-11-14T12:00:00-05:00")));
        Assert.False(c.IsHoly(T("2026-11-14T17:21:00-05:00")));
        Assert.False((c with { Shabbat = false }).IsHoly(T("2026-11-14T12:00:00-05:00")));
    }

    [Fact]
    public void Screens_held_from_midnight_of_the_candle_lighting_day()
    {
        var c = SaverConfig.Load(Json)!;
        Assert.False(c.HoldScreens(T("2026-11-12T23:30:00-05:00")));
        Assert.True(c.HoldScreens(T("2026-11-13T00:30:00-05:00")));
        Assert.False(c.HoldScreens(T("2026-11-14T17:21:00-05:00")));
        Assert.False((c with { Shabbat = false }).HoldScreens(T("2026-11-13T00:30:00-05:00")));
    }

    [Fact]
    public void InputGate_closes_on_input_outside_shabbat()
    {
        var g = new InputGate(100);
        Assert.False(g.ShouldClose(100, false));
        Assert.True(g.ShouldClose(101, false));
    }

    [Fact]
    public void InputGate_after_havdalah_needs_new_input()
    {
        var g = new InputGate(100);
        Assert.False(g.ShouldClose(250, true));   // touched on Shabbat: ignored
        Assert.False(g.ShouldClose(250, false));  // havdalah: that old touch doesn't count
        Assert.True(g.ShouldClose(251, false));
    }
}
