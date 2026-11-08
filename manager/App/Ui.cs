using Microsoft.UI;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Windows.UI;

namespace ShabbatManager;

/// <summary>Small helpers the pages share.</summary>
public static class Ui
{
    public const string Saved = "Saved. Screens update within a minute.";

    public static readonly SolidColorBrush Gold = Brush(0xE5, 0xBA, 0x5E);
    public static readonly SolidColorBrush Amber = Brush(0xF2, 0xA9, 0x3B);
    public static readonly SolidColorBrush Red = Brush(0xE8, 0x61, 0x5A);
    public static readonly SolidColorBrush Green = Brush(0x6C, 0xCB, 0x77);
    public static readonly SolidColorBrush Dim = new(Color.FromArgb(0xB0, 0xFF, 0xFF, 0xFF));

    private static SolidColorBrush Brush(byte r, byte g, byte b) => new(Color.FromArgb(0xFF, r, g, b));

    /// <summary>An error in red, else a success line in green, else hidden.</summary>
    public static void Show(InfoBar bar, string? error, string? success = null)
    {
        if (error is null && success is null)
        {
            bar.IsOpen = false;
            return;
        }
        bar.Severity = error is null ? InfoBarSeverity.Success : InfoBarSeverity.Error;
        bar.Message = error ?? success;
        bar.IsOpen = true;
    }

    public static TextBlock Text(string text, Brush? color = null, bool wrap = true)
    {
        var t = new TextBlock { Text = text, TextWrapping = wrap ? TextWrapping.Wrap : TextWrapping.NoWrap, VerticalAlignment = VerticalAlignment.Center };
        if (color is not null) t.Foreground = color;
        return t;
    }

    public static TextBlock Heading(string text) => new()
    {
        Text = text,
        Style = (Style)Application.Current.Resources["SubtitleTextBlockStyle"],
        Margin = new Thickness(0, 20, 0, 4),
    };

    /// <summary>A row of text cells in a Grid with Auto columns.</summary>
    public static void AddRow(Grid grid, params UIElement[] cells)
    {
        while (grid.ColumnDefinitions.Count < cells.Length)
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        var row = grid.RowDefinitions.Count;
        grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        for (var i = 0; i < cells.Length; i++)
        {
            Grid.SetRow((FrameworkElement)cells[i], row);
            Grid.SetColumn((FrameworkElement)cells[i], i);
            grid.Children.Add(cells[i]);
        }
    }

    public static Border Card(UIElement child, Brush accent) => new()
    {
        Child = child,
        BorderBrush = accent,
        BorderThickness = new Thickness(4, 0, 0, 0),
        Background = (Brush)Application.Current.Resources["CardBackgroundFillColorDefaultBrush"],
        Padding = new Thickness(14, 10, 14, 10),
        CornerRadius = new CornerRadius(4),
    };

    public static SolidColorBrush Transparent => new(Colors.Transparent);
}
