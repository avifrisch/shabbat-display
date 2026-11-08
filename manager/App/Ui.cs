using Microsoft.UI;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
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

    // Segoe Fluent Icons
    public const string Up = "", Down = "", Remove = "", Star = "", StarFilled = "";

    public static Button IconButton(string glyph, string tip, Action click, Brush? color = null, bool enabled = true)
    {
        var icon = new FontIcon { Glyph = glyph, FontSize = 14 };
        if (color is not null) icon.Foreground = color;
        var b = new Button { Content = icon, Padding = new Thickness(8, 6, 8, 6), IsEnabled = enabled, Background = Transparent, BorderThickness = new Thickness(0) };
        ToolTipService.SetToolTip(b, tip);
        AutomationProperties.SetName(b, tip);
        b.Click += (_, _) => click();
        return b;
    }

    public static TextBlock Note(string text) => new()
    {
        Text = text,
        TextWrapping = TextWrapping.Wrap,
        Foreground = Dim,
        Style = (Style)Application.Current.Resources["CaptionTextBlockStyle"],
        Margin = new Thickness(0, 4, 0, 0),
    };
}

/// <summary>Waits for a pause in typing; an older wait is cancelled by a newer one.</summary>
public sealed class Debouncer(int ms)
{
    private int latest;

    /// <summary>A ticket for this keystroke, once typing has paused; null when a newer keystroke came in.</summary>
    public async Task<int?> Pause()
    {
        var mine = ++latest;
        await Task.Delay(ms);
        return mine == latest ? mine : null;
    }

    /// <summary>Whether an answer for this ticket is still wanted (no typing since).</summary>
    public bool IsLatest(int ticket) => ticket == latest;
}
