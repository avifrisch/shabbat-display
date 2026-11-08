namespace Manager.Core;

/// <summary>The stocks on the business scene, in order. At most 30, no symbol twice.</summary>
public class Watchlist(List<Stock> items)
{
    public const int Max = 30;

    public List<Stock> Items { get; } = [.. items];

    public bool Add(Stock s)
    {
        if (Items.Count >= Max || Items.Any(x => string.Equals(x.Symbol, s.Symbol, StringComparison.OrdinalIgnoreCase))) return false;
        Items.Add(s);
        return true;
    }

    public void Move(int from, int to)
    {
        if (from < 0 || from >= Items.Count || to < 0 || to >= Items.Count) return;
        var s = Items[from];
        Items.RemoveAt(from);
        Items.Insert(to, s);
    }

    public void Remove(int i)
    {
        if (i >= 0 && i < Items.Count) Items.RemoveAt(i);
    }
}

/// <summary>A league's chosen teams: one favorite whenever there are any.</summary>
public static class LeagueRules
{
    public static League Add(League l, Team t)
    {
        if (l.Teams.Any(x => x.Id == t.Id)) return l;
        return l with { Teams = [.. l.Teams, t], Favorite = l.Favorite ?? t.Id };
    }

    public static League Remove(League l, int id)
    {
        var teams = l.Teams.Where(x => x.Id != id).ToList();
        var fav = l.Favorite == id || !teams.Any(x => x.Id == l.Favorite) ? teams.FirstOrDefault()?.Id : l.Favorite;
        return l with { Teams = teams, Favorite = fav };
    }

    public static League SetFavorite(League l, int id) => l.Teams.Any(x => x.Id == id) ? l with { Favorite = id } : l;
}
