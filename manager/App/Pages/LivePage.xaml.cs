using Manager.Core;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;
using Microsoft.Web.WebView2.Core;

namespace ShabbatManager.Pages;

/// <summary>The display itself, live and clickable: the house rotation or one screen's.</summary>
public sealed partial class LivePage : Page
{
    // its own folder: the NYT page clears its browser's cookies after a sign-in
    private static readonly string WebFolder =
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "ShabbatDisplayManager", "WebView2-Live");
    private const string House = "House rotation";

    private bool webReady, filling;

    public LivePage()
    {
        InitializeComponent();
    }

    protected override async void OnNavigatedTo(NavigationEventArgs e)
    {
        filling = true;
        ScreenPicker.Items.Add(House);
        ScreenPicker.SelectedIndex = 0;
        filling = false;
        var r = await AppState.Call(c => c.GetHouseholdAsync());
        Ui.Show(Message, r.Error);
        if (r.Value?.Screens is { } screens)
        {
            filling = true;
            foreach (var name in screens.Keys.Order()) ScreenPicker.Items.Add(name);
            filling = false;
        }
        await Show();
    }

    protected override void OnNavigatedFrom(NavigationEventArgs e)
    {
        // stop the page's polling once it's out of sight
        if (webReady) Web.Close();
    }

    private string? Screen => ScreenPicker.SelectedItem as string is { } s && s != House ? s : null;

    private async Task Show()
    {
        if (AppState.Server is not { } server) return;
        try
        {
            if (!webReady)
            {
                Directory.CreateDirectory(WebFolder);
                var env = await CoreWebView2Environment.CreateWithOptionsAsync(null, WebFolder, new CoreWebView2EnvironmentOptions());
                await Web.EnsureCoreWebView2Async(env);
                webReady = true;
            }
            Web.CoreWebView2.Navigate(LiveView.PageUrl(server, Screen).AbsoluteUri);
        }
        catch (Exception)   // no WebView2 runtime, or it failed to start
        {
            Ui.Show(Message, "The live view couldn't open here. Use Open in browser.");
        }
    }

    private async void ScreenPicker_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (!filling) await Show();
    }

    private async void Reload_Click(object sender, RoutedEventArgs e) => await Show();

    private async void OpenInBrowser_Click(object sender, RoutedEventArgs e)
    {
        if (AppState.Server is { } server)
            await Windows.System.Launcher.LaunchUriAsync(LiveView.PageUrl(server, Screen));
    }
}
