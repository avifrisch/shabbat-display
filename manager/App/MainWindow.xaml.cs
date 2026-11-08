using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace ShabbatManager;

public sealed partial class MainWindow : Window
{
    public MainWindow()
    {
        InitializeComponent();
        AppWindow.Resize(new Windows.Graphics.SizeInt32(1100, 760));
        Nav.SelectedItem = Nav.MenuItems[0];
    }

    private void Nav_SelectionChanged(NavigationView sender, NavigationViewSelectionChangedEventArgs args)
    {
        if (args.SelectedItem is NavigationViewItem item)
            ContentFrame.Content = new TextBlock { Text = (string)item.Tag, Style = (Style)Application.Current.Resources["TitleTextBlockStyle"] };
    }
}
