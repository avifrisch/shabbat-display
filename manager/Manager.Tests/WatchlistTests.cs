using Manager.Core;

namespace Manager.Tests;

public class WatchlistTests
{
    [Fact]
    public void Add_ignores_duplicates_and_caps_at_30()
    {
        var w = new Watchlist([]);
        Assert.True(w.Add(new("AAPL", "Apple Inc.")));
        Assert.False(w.Add(new("aapl", "Apple again")));
        for (var i = 0; i < 40; i++) w.Add(new($"T{i}", $"Company {i}"));
        Assert.Equal(30, w.Items.Count);
        Assert.Equal("AAPL", w.Items[0].Symbol);
    }

    [Fact]
    public void Move_reorders()
    {
        var w = new Watchlist([new("A", "a"), new("B", "b"), new("C", "c")]);
        w.Move(2, 0);
        Assert.Equal(new[] { "C", "A", "B" }, w.Items.Select(s => s.Symbol));
        w.Move(0, 5);   // out of range: nothing happens
        Assert.Equal(new[] { "C", "A", "B" }, w.Items.Select(s => s.Symbol));
        w.Remove(1);
        Assert.Equal(new[] { "C", "B" }, w.Items.Select(s => s.Symbol));
    }
}

public class LeagueRulesTests
{
    private static readonly Team Knicks = new(18, "NY", "New York Knicks");
    private static readonly Team Nets = new(17, "BKN", "Brooklyn Nets");

    [Fact]
    public void First_team_added_is_the_favorite()
    {
        var l = LeagueRules.Add(new League(true, [], null), Knicks);
        l = LeagueRules.Add(l, Nets);
        Assert.Equal(18, l.Favorite);
        Assert.Equal(2, l.Teams.Count);
        Assert.Equal(2, LeagueRules.Add(l, Knicks).Teams.Count);   // no duplicates
    }

    [Fact]
    public void Removing_the_favorite_moves_it()
    {
        var l = new League(true, [Knicks, Nets], 18);
        l = LeagueRules.Remove(l, 18);
        Assert.Equal(17, l.Favorite);
        l = LeagueRules.Remove(l, 17);
        Assert.Null(l.Favorite);
        Assert.Empty(l.Teams);
    }

    [Fact]
    public void Favorite_must_be_chosen()
    {
        var l = new League(true, [Knicks, Nets], 18);
        Assert.Equal(17, LeagueRules.SetFavorite(l, 17).Favorite);
        Assert.Equal(18, LeagueRules.SetFavorite(l, 99).Favorite);
    }
}
