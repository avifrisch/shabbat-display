using Manager.Core;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Navigation;

namespace ShabbatManager.Pages;

/// <summary>Announcements: send one, see which phones and tablets get them, and the keys that carry them. Each button saves at once.</summary>
public sealed partial class PhonesPage : Page
{
    private const string AnnounceHelp = "Shown on every display for 45 seconds, said by iPads that are listening, and sent to the phones and tablets below.";

    private bool loaded;

    public PhonesPage()
    {
        InitializeComponent();
    }

    protected override void OnNavigatedTo(NavigationEventArgs e) => _ = Load();

    private void Refresh_Click(object sender, RoutedEventArgs e)
    {
        loaded = false;   // Refresh also puts back the saved push key settings
        _ = Load();
    }

    private async Task Load()
    {
        Busy.IsActive = true;
        var r = await AppState.Call(c => c.GetVoiceAsync());
        Busy.IsActive = false;
        Take(r, null);
    }

    private async Task<bool> Change(string op, string? done, params (string Key, object? Value)[] more)
    {
        Busy.IsActive = true;
        var r = await AppState.Call(c => c.ChangeVoiceAsync(op, more));
        Busy.IsActive = false;
        return Take(r, r.Value?.Note ?? done, fields: op == "set_push");
    }

    /// <summary>Shows the state. The push key boxes are filled on the first load and after saving them, so a refresh of the rest doesn't undo typing.</summary>
    private bool Take(Result<VoiceState> r, string? done, bool fields = false)
    {
        Ui.Show(Message, r.Error, done);
        if (r.Value is not { } v) return false;

        AnnounceButton.IsEnabled = !v.Holy;
        AnnounceNote.Text = v.Holy ? "Nothing is announced on Shabbat or Yom Tov." : AnnounceHelp;

        Devices.Children.Clear();
        if (v.Devices is not { Count: > 0 }) Devices.Children.Add(Ui.Note("No phone or tablet has asked for announcements yet."));
        foreach (var d in v.Devices ?? [])
        {
            var device = d;
            var name = device.Screen.Length > 0 ? device.Screen : "this device";
            var row = new Grid { ColumnSpacing = 12 };
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            row.Children.Add(Ui.Text(VoiceSummary.Device(device)));
            var remove = Ui.IconButton(Ui.Remove, "Remove " + name, () => _ = Change("forget_device", $"Removed {name}.", ("id", device.Id)));
            Grid.SetColumn(remove, 1);
            row.Children.Add(remove);
            Devices.Children.Add(row);
        }

        var (text, good) = VoiceSummary.Push(v.Push);
        PushState.Text = text;
        PushState.Foreground = good ? Ui.Green : Ui.Amber;
        if (v.Push is { } p && (fields || !loaded))
        {
            KeyFile.Text = p.KeyFile;
            KeyId.Text = p.KeyId;
            TeamId.Text = p.TeamId;
            Critical.IsOn = p.Critical;
            loaded = true;
        }

        NtfyState.Text = v.NtfySet ? "An address is saved." : "No address is saved.";
        NtfyState.Foreground = v.NtfySet ? Ui.Green : Ui.Dim;
        RemoveNtfy.IsEnabled = v.NtfySet;
        return true;
    }

    private async void Announce_Click(object sender, RoutedEventArgs e)
    {
        var text = AnnounceText.Text.Trim();
        if (text.Length == 0)
        {
            Ui.Show(Message, "Type what to announce.");
            return;
        }
        AnnounceButton.IsEnabled = false;   // one click, one announcement
        if (await Change("announce", "Announced.", ("text", text))) AnnounceText.Text = "";
        else AnnounceButton.IsEnabled = true;
    }

    private void AnnounceText_KeyDown(object sender, KeyRoutedEventArgs e)
    {
        if (e.Key != Windows.System.VirtualKey.Enter || !AnnounceButton.IsEnabled) return;
        e.Handled = true;
        Announce_Click(sender, e);
    }

    private async void SavePush_Click(object sender, RoutedEventArgs e) =>
        await Change("set_push", "The push key settings are saved.", ("key_file", KeyFile.Text.Trim()), ("key_id", KeyId.Text.Trim()),
                     ("team_id", TeamId.Text.Trim()), ("critical", Critical.IsOn));

    private async void SaveNtfy_Click(object sender, RoutedEventArgs e)
    {
        var url = NtfyBox.Password.Trim();
        if (url.Length == 0)
        {
            Ui.Show(Message, "Paste the address first.");
            return;
        }
        if (await Change("set_ntfy", "The address is saved.", ("url", url))) NtfyBox.Password = "";
    }

    private async void RemoveNtfy_Click(object sender, RoutedEventArgs e) =>
        await Change("set_ntfy", "The address is removed.", ("url", ""));
}
