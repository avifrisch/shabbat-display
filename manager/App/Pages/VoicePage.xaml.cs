using Manager.Core;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;

namespace ShabbatManager.Pages;

/// <summary>The iPad app's voice assistant: its Claude key, its spending limits and what it has spent. Each button saves at once.</summary>
public sealed partial class VoicePage : Page
{
    public VoicePage()
    {
        InitializeComponent();
    }

    protected override void OnNavigatedTo(NavigationEventArgs e) => _ = Load();

    private void Refresh_Click(object sender, RoutedEventArgs e) => _ = Load();

    private async Task Load()
    {
        Busy.IsActive = true;
        var r = await AppState.Call(c => c.GetVoiceAsync());
        Busy.IsActive = false;
        Take(r, null);
    }

    private async Task<bool> Change(string op, string done, params (string Key, object? Value)[] more)
    {
        Busy.IsActive = true;
        var r = await AppState.Call(c => c.ChangeVoiceAsync(op, more));
        Busy.IsActive = false;
        return Take(r, done);
    }

    private bool Take(Result<VoiceState> r, string? done)
    {
        Ui.Show(Message, r.Error, done);
        if (r.Value is not { } v) return false;
        var (text, good) = VoiceSummary.Assistant(v);
        State.Text = text;
        State.Foreground = good ? Ui.Green : Ui.Amber;
        Spent.Text = VoiceSummary.Spent(v);
        KeyState.Text = v.KeySet ? "A key is saved." : "No key is saved.";
        KeyState.Foreground = v.KeySet ? Ui.Green : Ui.Dim;
        RemoveKey.IsEnabled = v.KeySet;
        MonthlyBox.Value = v.MonthlyUsd;
        DailyBox.Value = v.DailyRequests;
        MenuState.Text = v.MenuappSet ? "An address is saved." : "No address is saved: the list stays on the display computer only.";
        MenuState.Foreground = v.MenuappSet ? Ui.Green : Ui.Dim;
        RemoveMenu.IsEnabled = v.MenuappSet;
        return true;
    }

    private async void SaveKey_Click(object sender, RoutedEventArgs e)
    {
        var key = KeyBox.Password.Trim();
        if (key.Length == 0)
        {
            Ui.Show(Message, "Paste the key first.");
            return;
        }
        if (await Change("set_key", "The key is saved.", ("key", key))) KeyBox.Password = "";
    }

    private async void RemoveKey_Click(object sender, RoutedEventArgs e)
    {
        if (!await Confirm("Remove the Claude key? The voice assistant stops answering until a key is saved again.", "Remove")) return;
        await Change("set_key", "The key is removed. The voice assistant is off.", ("key", ""));
    }

    private async void SaveLimits_Click(object sender, RoutedEventArgs e)
    {
        if (double.IsNaN(MonthlyBox.Value) || double.IsNaN(DailyBox.Value))
        {
            Ui.Show(Message, "Both limits need a number.");
            return;
        }
        await Change("set_limits", "The limits are saved.", ("monthly_usd", Math.Round(MonthlyBox.Value, 2)), ("daily_requests", (int)Math.Round(DailyBox.Value)));
    }

    private async void SaveMenu_Click(object sender, RoutedEventArgs e)
    {
        var url = MenuBox.Password.Trim();
        if (url.Length == 0)
        {
            Ui.Show(Message, "Paste the address first.");
            return;
        }
        if (await Change("set_menuapp", "The address is saved.", ("url", url))) MenuBox.Password = "";
    }

    private async void RemoveMenu_Click(object sender, RoutedEventArgs e) =>
        await Change("set_menuapp", "The address is removed.", ("url", ""));

    private async Task<bool> Confirm(string question, string go)
    {
        var dialog = new ContentDialog
        {
            Title = question, PrimaryButtonText = go, CloseButtonText = "Cancel",
            DefaultButton = ContentDialogButton.Close, XamlRoot = XamlRoot,
        };
        return await dialog.ShowAsync() == ContentDialogResult.Primary;
    }
}
