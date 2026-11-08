using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using ShabbatManager.Pages;

namespace ShabbatManager;

public sealed partial class MainWindow : Window
{
    private static readonly Dictionary<string, Type> PageTypes = new()
    {
        ["Status"] = typeof(StatusPage),
        ["Live"] = typeof(LivePage),
        ["Sports"] = typeof(SportsPage),
        ["Business"] = typeof(BusinessPage),
        ["Screens"] = typeof(ScreensPage),
        ["Shul"] = typeof(ShulPage),
        ["NYT"] = typeof(NytPage),
        ["Server"] = typeof(ServerPage),
    };

    public MainWindow()
    {
        InitializeComponent();
        ExtendsContentIntoTitleBar = true;
        SetTitleBar(AppTitleBar);
        AppWindow.Resize(new Windows.Graphics.SizeInt32(1100, 780));
    }

    private async void Root_Loaded(object sender, RoutedEventArgs e)
    {
        AppState.Root = Root.XamlRoot;
        await Connect();
    }

    private async void TryAgain_Click(object sender, RoutedEventArgs e) => await Connect();

    private async Task Connect()
    {
        ConnectionBar.Message = "Looking for the display server…";
        ConnectionBar.Severity = InfoBarSeverity.Informational;
        ConnectionBar.IsOpen = true;
        var error = await AppState.ConnectAsync();
        if (error is null)
            ConnectionBar.IsOpen = false;
        else
        {
            ConnectionBar.Message = error;
            ConnectionBar.Severity = InfoBarSeverity.Warning;
        }
        // (re)open the current page so it loads with the connection
        var current = Nav.SelectedItem;
        Nav.SelectedItem = null;
        Nav.SelectedItem = current ?? Nav.MenuItems[0];
    }

    private void Nav_SelectionChanged(NavigationView sender, NavigationViewSelectionChangedEventArgs args)
    {
        if (args.SelectedItem is not NavigationViewItem item) return;
        var tag = (string)item.Tag;
        if (PageTypes.TryGetValue(tag, out var type))
            ContentFrame.Navigate(type);
        else
            ContentFrame.Content = new TextBlock { Text = tag, Style = (Style)Application.Current.Resources["TitleTextBlockStyle"] };
    }
}
