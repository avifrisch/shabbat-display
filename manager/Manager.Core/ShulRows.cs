namespace Manager.Core;

public record ShulRow(string Title, string Detail, bool Ok, string Text);

/// <summary>The shul's three files as rows: weekly chart, bulletin, calendar.</summary>
public static class ShulRows
{
    public static List<ShulRow> From(ShulStatus s)
    {
        var chart = s.Chart is { } c
            ? new ShulRow("Weekly chart", c.File ?? "", c.ThisWeek, c.ThisWeek ? "this week" : "not this week's")
            : new ShulRow("Weekly chart", "", false, "not downloaded");

        ShulRow bulletin;
        if (s.Bulletin is not { } b)
            bulletin = new("Bulletin", "", false, "not downloaded");
        else if (b.Rows is null)
            bulletin = new("Bulletin", b.File ?? "", false, s.Problem ?? "Its Shabbat times couldn't be read.");
        else
            bulletin = new("Bulletin", b.File ?? "", b.ThisShabbat, b.ThisShabbat ? $"this Shabbat, {b.Rows} times read" : "not this Shabbat's");

        var cals = s.Calendars ?? [];
        var calendar = cals.Count == 0
            ? new ShulRow("Calendar", "", false, "not downloaded")
            : new ShulRow("Calendar", string.Join(", ", cals.Select(x => x.File)), cals.Any(x => x.ThisMonth),
                          cals.Any(x => x.ThisMonth) ? "this month" : "not this month's");
        return [chart, bulletin, calendar];
    }
}
