using Manager.Core;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;

namespace ShabbatManager.Pages;

/// <summary>The house rotation, and for each screen its own rotation and (on a PC) always-on or screen saver.</summary>
public sealed partial class ScreensPage : Page
{
    private const string Agenda = "agenda";

    /// <summary>One screen's unsaved state. Name null is the house rotation.</summary>
    private sealed class Draft
    {
        public string? Name;
        public RotationEditor? Rotation;   // null: uses the house rotation
        public bool Launcher, Saved;
        public string Mode = "always";
        public SaverOptions Saver = new(10, true, false);
        public double? Seen;
        public bool Dirty, ModeDirty;
        public int Version;   // goes up with every edit, so a save only clears the edits it sent
    }

    private Household? household;
    private readonly List<Draft> drafts = [];
    private Draft? current;

    public ScreensPage()
    {
        InitializeComponent();
    }

    protected override void OnNavigatedTo(NavigationEventArgs e)
    {
        if (!drafts.Any(d => d.Dirty)) _ = Load();
    }

    private async void Reload_Click(object sender, RoutedEventArgs e)
    {
        if (drafts.Any(d => d.Dirty))
        {
            var ask = new ContentDialog
            {
                XamlRoot = XamlRoot,
                Title = "Discard unsaved changes?",
                Content = "Reloading shows what the display server has now. Changes you haven't saved are lost.",
                PrimaryButtonText = "Discard and reload",
                CloseButtonText = "Cancel",
                DefaultButton = ContentDialogButton.Close,
            };
            if (await ask.ShowAsync() != ContentDialogResult.Primary) return;
        }
        await Load();
    }

    private async Task Load()
    {
        Busy.IsActive = true;
        var h = await AppState.Call(c => c.GetHouseholdAsync());
        var s = h.Ok ? await AppState.Call(c => c.GetStatusAsync()) : null;
        Busy.IsActive = false;
        Ui.Show(Message, h.Error);
        if (h.Value is null) return;
        if (h.Value.DefaultRotation is null || h.Value.Screens is null || h.Value.Scenes is null)
        {
            Ui.Show(Message, ManageClient.NeedsUpdate);
            return;
        }
        household = h.Value;
        var seen = (s?.Value?.Screens ?? []).ToDictionary(x => x.Name);
        var selected = current?.Name;
        drafts.Clear();
        var house = new RotationEditor(household.DefaultRotation, household.Scenes);
        house.AddMissingFromCatalog();
        drafts.Add(new Draft { Rotation = house });
        foreach (var name in household.Screens.Keys.Union(seen.Keys).Order(StringComparer.OrdinalIgnoreCase))
        {
            var sc = household.Screens.GetValueOrDefault(name);
            var st = seen.GetValueOrDefault(name);
            RotationEditor? rot = null;
            if (sc?.Rotation is { } r)
            {
                rot = new RotationEditor(r, household.Scenes);
                rot.AddMissingFromCatalog();
            }
            drafts.Add(new Draft
            {
                Name = name,
                Rotation = rot,
                Launcher = (sc?.Launcher ?? false) || (st?.Launcher ?? false),
                Saved = sc?.Saved ?? false,
                // until it's saved here, the PC follows its own settings: show (and keep) those
                Mode = sc?.Effective.Mode ?? "always",
                Saver = sc?.Effective.Saver ?? new SaverOptions(10, true, false),
                Seen = st?.Last,
            });
        }
        BuildList(drafts.FindIndex(d => d.Name == selected) is var i and >= 0 ? i : 0);
        SaveButton.IsEnabled = true;
    }

    private void BuildList(int select)
    {
        ScreenList.Items.Clear();
        var now = DateTimeOffset.Now;
        foreach (var d in drafts)
        {
            var p = new StackPanel { Padding = new Thickness(0, 6, 0, 6) };
            p.Children.Add(Ui.Text(d.Name ?? "House rotation (default)", wrap: false));
            if (d.Name is not null)
                p.Children.Add(Ui.Note((d.Launcher ? "PC" : "Browser") + " · " + (d.Seen is null ? "not seen lately" : "seen " + StatusSummary.Ago(d.Seen, now))));
            else
                p.Children.Add(Ui.Note("Every screen without its own"));
            AutomationProperties.SetName(p, d.Name ?? "House rotation (default)");
            ScreenList.Items.Add(p);
        }
        ScreenList.SelectedIndex = select;
    }

    private void ScreenList_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (ScreenList.SelectedIndex < 0 || ScreenList.SelectedIndex >= drafts.Count) return;
        current = drafts[ScreenList.SelectedIndex];
        BuildPane();
    }

    private void BuildPane()
    {
        Pane.Children.Clear();
        if (current is not { } d || household is null) return;
        Pane.Children.Add(new TextBlock { Text = d.Name ?? "House rotation", Style = (Style)Application.Current.Resources["SubtitleTextBlockStyle"] });

        if (d.Name is null)
            Pane.Children.Add(Ui.Note("Screens that don't have their own rotation show this one."));
        else
        {
            var useHouse = new ToggleSwitch { Header = "Use the house rotation", IsOn = d.Rotation is null, OnContent = "Yes", OffContent = "No, its own" };
            useHouse.Toggled += (_, _) =>
            {
                if (useHouse.IsOn)
                    d.Rotation = null;
                else
                {
                    // start from a copy of the house rotation as it stands in the editor
                    d.Rotation = new RotationEditor(drafts[0].Rotation!.ItemsToSave(), household.Scenes);
                    d.Rotation.AddMissingFromCatalog();
                }
                Changed(d);
                BuildPane();
            };
            Pane.Children.Add(useHouse);
        }

        if (d.Rotation is { } rot)
            Pane.Children.Add(RotationList(d, rot));

        if (d.Name is not null && d.Launcher)
            Pane.Children.Add(ModeSection(d));
    }

    private StackPanel RotationList(Draft d, RotationEditor rot)
    {
        var list = new StackPanel { Spacing = 2, Margin = new Thickness(0, 8, 0, 0) };
        list.Children.Add(Ui.Note("Ticked scenes show in this order, each for the seconds given. Scenes with nothing to show (a league out of season) are skipped."));
        for (var i = 0; i < rot.Items.Count; i++)
        {
            var at = i;
            var item = rot.Items[i];
            var row = new Grid { ColumnSpacing = 8 };
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });

            var check = new CheckBox { Content = rot.Label(i), IsChecked = item.On, MinWidth = 0 };
            check.Click += (_, _) => { rot.SetOn(at, check.IsChecked == true); Changed(d); };
            var left = new StackPanel();
            left.Children.Add(check);
            if (item.Scene == Agenda)
                left.Children.Add(Ui.Note(household!.AgendaSet ? "Private: shows your calendar on this screen." : "Private: shows your calendar on this screen. No calendar is set up yet."));
            row.Children.Add(left);

            var secs = new NumberBox
            {
                Value = item.Seconds,
                Minimum = RotationEditor.MinSeconds,
                Maximum = RotationEditor.MaxSeconds,
                SpinButtonPlacementMode = NumberBoxSpinButtonPlacementMode.Compact,
                Width = 110,
                VerticalAlignment = VerticalAlignment.Top,
            };
            AutomationProperties.SetName(secs, rot.Label(i) + " seconds");
            secs.ValueChanged += (_, a) =>
            {
                if (double.IsNaN(a.NewValue)) { secs.Value = rot.Items[at].Seconds; return; }
                if ((int)Math.Round(a.NewValue) == rot.Items[at].Seconds) return;
                rot.SetSeconds(at, (int)Math.Round(a.NewValue));
                Changed(d);
            };
            Grid.SetColumn(secs, 1);
            row.Children.Add(secs);

            var moves = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Top };
            moves.Children.Add(Ui.IconButton(Ui.Up, "Move " + rot.Label(i) + " up", () => { rot.MoveUp(at); Changed(d); BuildPane(); }, enabled: at > 0));
            moves.Children.Add(Ui.IconButton(Ui.Down, "Move " + rot.Label(i) + " down", () => { rot.MoveDown(at); Changed(d); BuildPane(); }, enabled: at < rot.Items.Count - 1));
            Grid.SetColumn(moves, 2);
            row.Children.Add(moves);
            list.Children.Add(row);
        }
        return list;
    }

    private StackPanel ModeSection(Draft d)
    {
        var p = new StackPanel { Spacing = 8 };
        p.Children.Add(Ui.Heading("This PC"));
        if (!d.Saved && !d.Dirty)
            p.Children.Add(Ui.Card(Ui.Text("Showing this PC's own settings. Nothing changes until you save."), Ui.Gold));

        string[] modes = ["always", "saver", "off"];
        var mode = new RadioButtons { Header = "Shows the display" };
        mode.Items.Add("Always on");
        mode.Items.Add("Screen saver");
        mode.Items.Add("Off");
        mode.SelectedIndex = Math.Max(0, Array.IndexOf(modes, d.Mode));
        p.Children.Add(mode);

        var saver = new StackPanel { Spacing = 8, Margin = new Thickness(0, 4, 0, 0), Visibility = d.Mode == "saver" ? Visibility.Visible : Visibility.Collapsed };
        saver.Children.Add(Ui.Note("Windows' own screen saver shows the display on every screen."));
        var minutes = new NumberBox
        {
            Header = "Wait (minutes)",
            Value = d.Saver.Minutes,
            Minimum = 1,
            Maximum = 240,
            SpinButtonPlacementMode = NumberBoxSpinButtonPlacementMode.Compact,
            Width = 260,
            HorizontalAlignment = HorizontalAlignment.Left,
        };
        minutes.ValueChanged += (_, a) =>
        {
            if (double.IsNaN(a.NewValue)) { minutes.Value = d.Saver.Minutes; return; }
            var m = (int)Math.Clamp(Math.Round(a.NewValue), 1, 240);
            if (m == d.Saver.Minutes) return;
            d.Saver = d.Saver with { Minutes = m };
            ChangedMode(d);
        };
        var lockBox = new CheckBox { Content = "Lock Windows when it closes (never over Shabbat and Yom Tov)", IsChecked = d.Saver.Lock };
        lockBox.Click += (_, _) => { d.Saver = d.Saver with { Lock = lockBox.IsChecked == true }; ChangedMode(d); };
        var shabbat = new CheckBox { Content = "Keep the screens on over Shabbat and Yom Tov", IsChecked = d.Saver.Shabbat };
        var winL = Ui.Note("Don't lock this PC (Win+L) on Erev Shabbat: the screen saver can't show over the lock screen.");
        winL.Visibility = d.Saver.Shabbat ? Visibility.Visible : Visibility.Collapsed;
        shabbat.Click += (_, _) =>
        {
            d.Saver = d.Saver with { Shabbat = shabbat.IsChecked == true };
            winL.Visibility = d.Saver.Shabbat ? Visibility.Visible : Visibility.Collapsed;
            ChangedMode(d);
        };
        saver.Children.Add(minutes);
        saver.Children.Add(lockBox);
        saver.Children.Add(shabbat);
        saver.Children.Add(winL);
        p.Children.Add(saver);

        // RadioButtons raises SelectionChanged while it loads; only a real change counts as an edit
        mode.SelectionChanged += (_, _) =>
        {
            if (mode.SelectedIndex < 0 || modes[mode.SelectedIndex] == d.Mode) return;
            d.Mode = modes[mode.SelectedIndex];
            saver.Visibility = d.Mode == "saver" ? Visibility.Visible : Visibility.Collapsed;
            ChangedMode(d);
        };
        return p;
    }

    private void Changed(Draft d)
    {
        d.Dirty = true;
        d.Version++;
        Message.IsOpen = false;
    }

    private void ChangedMode(Draft d)
    {
        d.ModeDirty = true;
        Changed(d);
    }

    private async void Save_Click(object sender, RoutedEventArgs e)
    {
        var pending = drafts.Where(x => x.Dirty).ToList();
        if (pending.Count == 0)
        {
            Ui.Show(Message, null, "No changes to save.");
            return;
        }
        foreach (var x in pending)
            if (x.Rotation?.Validate() is { } invalid)
            {
                ScreenList.SelectedIndex = drafts.IndexOf(x);
                Ui.Show(Message, $"{x.Name ?? "House rotation"}: {invalid}");
                return;
            }
        SaveButton.IsEnabled = false;
        Busy.IsActive = true;
        string? error = null;
        foreach (var x in pending)
        {
            var version = x.Version;
            var modeEdited = x.ModeDirty;
            var r = await AppState.Call(c => c.SaveRotationAsync(x.Name, x.Rotation?.ItemsToSave()));
            // a PC's mode is sent only when it was edited, so saving a rotation never changes what the PC does
            if (r.Ok && x.Name is not null && x.Launcher && modeEdited)
                r = await AppState.Call(c => c.SaveScreenAsync(x.Name, x.Mode, x.Saver));
            if (!r.Ok)
            {
                error = $"{x.Name ?? "House rotation"}: {r.Error}";
                ScreenList.SelectedIndex = drafts.IndexOf(x);
                break;
            }
            if (modeEdited) x.Saved = true;
            if (x.Version == version) x.Dirty = x.ModeDirty = false;
        }
        Busy.IsActive = false;
        SaveButton.IsEnabled = true;
        Ui.Show(Message, error, Ui.Saved);
        if (error is null) BuildPane();
    }
}
