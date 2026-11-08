using Manager.Core;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;

namespace ShabbatManager.Pages;

/// <summary>Whether everything is working, in plain words, then each feed, the shul's files and each screen.</summary>
public sealed partial class StatusPage : Page
{
    public StatusPage()
    {
        InitializeComponent();
    }

    protected override void OnNavigatedTo(NavigationEventArgs e) => _ = Load();

    private void Refresh_Click(object sender, RoutedEventArgs e) => _ = Load();

    private async Task Load()
    {
        Busy.IsActive = true;
        var r = await AppState.Call(c => c.GetStatusAsync());
        Busy.IsActive = false;
        Ui.Show(Message, r.Error);
        if (r.Value is { } s) Render(s, DateTimeOffset.Now);
    }

    private void Render(StatusResponse s, DateTimeOffset now)
    {
        var problems = StatusSummary.Problems(s, now);
        Headline.Text = problems.Count switch
        {
            0 => "Everything is working.",
            1 => "One thing needs attention.",
            _ => $"{problems.Count} things need attention.",
        };
        Headline.Foreground = problems.Count == 0 ? Ui.Green : problems.Any(p => p.Level == "red") ? Ui.Red : Ui.Amber;
        Problems.Children.Clear();
        foreach (var p in problems)
            Problems.Children.Add(Ui.Card(Ui.Text(p.Text), p.Level == "red" ? Ui.Red : Ui.Amber));

        Details.Children.Clear();
        if (s.Feeds is { } feeds)
        {
            Details.Children.Add(Ui.Heading("Feeds"));
            var grid = new Grid { ColumnSpacing = 24, RowSpacing = 4 };
            foreach (var (key, f) in feeds.OrderBy(kv => StatusSummary.FeedLabel(kv.Key)))
                Ui.AddRow(grid,
                    Ui.Text(StatusSummary.FeedLabel(key), wrap: false),
                    Ui.Text("updated " + StatusSummary.Ago(f.Updated, now), Ui.Dim, wrap: false),
                    f.Ok == false ? Ui.Text(f.Error ?? "failed", Ui.Amber) : Ui.Text("OK", Ui.Green, wrap: false));
            Details.Children.Add(grid);
        }
        if (s.Shul is { } shul)
        {
            Details.Children.Add(Ui.Heading("Shul"));
            foreach (var row in ShulRows.From(shul))
                Details.Children.Add(ShulLine(row));
        }
        if (s.Screens is { } screens)
        {
            Details.Children.Add(Ui.Heading("Screens"));
            var grid = new Grid { ColumnSpacing = 24, RowSpacing = 4 };
            foreach (var sc in screens)
                Ui.AddRow(grid,
                    Ui.Text(sc.Name, wrap: false),
                    Ui.Text(sc.Launcher ? "PC" : "Browser", Ui.Dim, wrap: false),
                    Ui.Text(sc.Last is null ? "not seen since the server started" : "seen " + StatusSummary.Ago(sc.Last, now), Ui.Dim, wrap: false));
            Details.Children.Add(grid);
        }
    }

    public static UIElement ShulLine(ShulRow row)
    {
        var p = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 12 };
        p.Children.Add(Ui.Text(row.Ok ? "✓" : "!", row.Ok ? Ui.Green : Ui.Amber, wrap: false));
        p.Children.Add(Ui.Text(row.Title, wrap: false));
        p.Children.Add(Ui.Text(row.Detail, Ui.Dim, wrap: false));
        p.Children.Add(Ui.Text(row.Text, row.Ok ? Ui.Green : Ui.Amber));
        return p;
    }
}
