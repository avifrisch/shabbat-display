using Manager.Core;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;

namespace ShabbatManager.Pages;

/// <summary>Whether this week's chart, bulletin and calendar came in, with a button to check the shul's site now.</summary>
public sealed partial class ShulPage : Page
{
    public ShulPage()
    {
        InitializeComponent();
    }

    protected override void OnNavigatedTo(NavigationEventArgs e) => _ = Load();

    private async Task Load()
    {
        Busy.IsActive = true;
        var r = await AppState.Call(c => c.GetStatusAsync());
        Busy.IsActive = false;
        Ui.Show(Message, r.Error ?? (r.Value is { Shul: null } ? ManageClient.NeedsUpdate : null));
        if (r.Value?.Shul is { } s) Render(s);
    }

    private void Render(ShulStatus s)
    {
        Rows.Children.Clear();
        var files = new[] { s.Chart?.File, s.Bulletin?.File, s.Calendars?.FirstOrDefault()?.File };
        var rows = ShulRows.From(s);
        for (var i = 0; i < rows.Count; i++)
        {
            var row = rows[i];
            var text = new StackPanel { Spacing = 2 };
            text.Children.Add(new TextBlock { Text = row.Title, Style = (Style)Application.Current.Resources["BodyStrongTextBlockStyle"] });
            text.Children.Add(Ui.Text(row.Detail.Length > 0 ? row.Detail : "No file yet", Ui.Dim));
            text.Children.Add(Ui.Text((row.Ok ? "✓ " : "") + row.Text, row.Ok ? Ui.Green : Ui.Amber));
            var grid = new Grid { ColumnSpacing = 16 };
            grid.ColumnDefinitions.Add(new ColumnDefinition());
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            grid.Children.Add(text);
            List<string?> calendars = i == 2 ? [.. (s.Calendars ?? []).Select(c => c.File)] : [files[i]];
            var open = new StackPanel { Spacing = 4, VerticalAlignment = VerticalAlignment.Center };
            foreach (var f in calendars.OfType<string>())
            {
                var b = new Button { Content = calendars.Count > 1 ? "Open " + f : "Open" };
                b.Click += (_, _) => OpenFile(f);
                open.Children.Add(b);
            }
            Grid.SetColumn(open, 1);
            grid.Children.Add(open);
            Rows.Children.Add(Ui.Card(grid, row.Ok ? Ui.Green : Ui.Amber));
        }
    }

    private static void OpenFile(string file)
    {
        if (AppState.Server is not { } server) return;
        var url = new Uri(server, "shul/" + Uri.EscapeDataString(file));
        System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(url.ToString()) { UseShellExecute = true });
    }

    private async void Update_Click(object sender, RoutedEventArgs e)
    {
        UpdateButton.IsEnabled = false;
        Busy.IsActive = true;
        Ui.Show(Message, null);
        var r = await AppState.Call(c => c.UpdateShulAsync());
        Busy.IsActive = false;
        UpdateButton.IsEnabled = true;
        if (!r.Ok)
        {
            Ui.Show(Message, r.Error);
            return;
        }
        Ui.Show(Message, null, "Checked the shul's site.");
        if (r.Value?.Shul is { } s) Render(s);
    }
}
