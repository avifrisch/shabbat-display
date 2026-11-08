using Manager.Core;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;

namespace ShabbatManager.Pages;

/// <summary>The server's feeds and log, and a restart for when something is stuck.</summary>
public sealed partial class ServerPage : Page
{
    public ServerPage()
    {
        InitializeComponent();
    }

    protected override void OnNavigatedTo(NavigationEventArgs e) => _ = Load();

    private void Refresh_Click(object sender, RoutedEventArgs e) => _ = Load();

    private async Task Load()
    {
        Busy.IsActive = true;
        var s = await AppState.Call(c => c.GetStatusAsync());
        var log = s.Ok ? await AppState.Call(c => c.GetLogAsync(200)) : null;
        Busy.IsActive = false;
        Ui.Show(Message, s.Error ?? log?.Error);
        var now = DateTimeOffset.Now;
        Where.Text = AppState.Server is { } u
            ? $"Connected to {u.Host}" + (s.Value?.Started is { } st ? $", running since {StatusSummary.Clock(st, now)}." : ".")
            : "Not connected.";
        if (s.Value?.Feeds is { } feeds)
        {
            Feeds.Children.Clear();
            Feeds.RowDefinitions.Clear();
            foreach (var (key, f) in feeds.OrderBy(kv => StatusSummary.FeedLabel(kv.Key)))
                Ui.AddRow(Feeds,
                    Ui.Text(StatusSummary.FeedLabel(key), wrap: false),
                    Ui.Text("updated " + StatusSummary.Ago(f.Updated, now), Ui.Dim, wrap: false),
                    f.Ok == false ? Ui.Text(f.Error ?? "failed", Ui.Amber) : Ui.Text("OK", Ui.Green, wrap: false));
        }
        if (log?.Value is { } lines)
        {
            Log.Text = string.Join("\r\n", lines);
            Log.SelectionStart = Log.Text.Length;   // newest at the bottom, in view
        }
    }

    private async void Restart_Click(object sender, RoutedEventArgs e)
    {
        var ask = new ContentDialog
        {
            XamlRoot = XamlRoot,
            Title = "Restart the display server?",
            Content = "The screens keep showing their last data and catch up in about a minute.",
            PrimaryButtonText = "Restart",
            CloseButtonText = "Cancel",
            DefaultButton = ContentDialogButton.Close,
        };
        if (await ask.ShowAsync() != ContentDialogResult.Primary) return;
        RestartButton.IsEnabled = false;
        Busy.IsActive = true;
        var r = await AppState.Call(c => c.RestartAsync());
        if (!r.Ok)
        {
            Busy.IsActive = false;
            RestartButton.IsEnabled = true;
            Ui.Show(Message, r.Error);
            return;
        }
        Message.Severity = InfoBarSeverity.Informational;
        Message.Message = "Restarting…";
        Message.IsOpen = true;
        await Task.Delay(2000);   // let the old server go away first
        var back = false;
        for (var waited = 2; waited <= 60 && !back; waited += 2)
        {
            back = AppState.Client is { } c && await c.HealthAsync();
            if (!back) await Task.Delay(2000);
        }
        Busy.IsActive = false;
        RestartButton.IsEnabled = true;
        if (back)
        {
            Ui.Show(Message, null, "Server restarted.");
            await Load();
            Ui.Show(Message, null, "Server restarted.");
        }
        else
            Ui.Show(Message, "The server hasn't come back. Check DESKTOP-H72VKDJ.");
    }
}
