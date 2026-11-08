using Manager.Core;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;

namespace ShabbatManager.Pages;

/// <summary>The business scene: on or off, the watchlist in order, and which headlines it shows.</summary>
public sealed partial class BusinessPage : Page
{
    private Watchlist watchlist = new([]);
    private Dictionary<string, bool> news = [];
    private readonly Dictionary<string, Stock> found = [];
    private readonly Debouncer debounce = new(250);
    private bool loading, dirty;

    public BusinessPage()
    {
        InitializeComponent();
    }

    protected override void OnNavigatedTo(NavigationEventArgs e)
    {
        if (!dirty) _ = Load();
    }

    private async Task Load()
    {
        Busy.IsActive = true;
        var r = await AppState.Call(c => c.GetHouseholdAsync());
        Busy.IsActive = false;
        Ui.Show(Message, r.Error);
        if (r.Value is not { } h) return;
        loading = true;
        OnSwitch.IsOn = h.Business.On;
        news = new(h.Business.News ?? []);
        NytSwitch.IsOn = news.GetValueOrDefault("biz_nyt", true);
        CnbcSwitch.IsOn = news.GetValueOrDefault("biz_cnbc", true);
        watchlist = new(h.Business.Watchlist ?? []);
        loading = false;
        BuildList();
        SaveButton.IsEnabled = true;
        dirty = false;
    }

    private void BuildList()
    {
        Stocks.Children.Clear();
        if (watchlist.Items.Count == 0)
            Stocks.Children.Add(Ui.Note("No stocks yet. The scene still shows the S&P 500, Dow and Nasdaq."));
        for (var i = 0; i < watchlist.Items.Count; i++)
        {
            var at = i;
            var s = watchlist.Items[i];
            var row = new Grid { ColumnSpacing = 12 };
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(80) });
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            row.Children.Add(Ui.Text(s.Symbol, Ui.Gold, wrap: false));
            var name = Ui.Text(s.Name, wrap: false);
            Grid.SetColumn(name, 1);
            row.Children.Add(name);
            var buttons = new StackPanel { Orientation = Orientation.Horizontal };
            buttons.Children.Add(Ui.IconButton(Ui.Up, "Move up", () => Edit(() => watchlist.Move(at, at - 1)), enabled: at > 0));
            buttons.Children.Add(Ui.IconButton(Ui.Down, "Move down", () => Edit(() => watchlist.Move(at, at + 1)), enabled: at < watchlist.Items.Count - 1));
            buttons.Children.Add(Ui.IconButton(Ui.Remove, "Remove " + s.Symbol, () => Edit(() => watchlist.Remove(at))));
            Grid.SetColumn(buttons, 2);
            row.Children.Add(buttons);
            Stocks.Children.Add(row);
        }
    }

    private void Edit(Action change)
    {
        change();
        BuildList();
        Changed(this, null!);
    }

    private void Changed(object sender, RoutedEventArgs e)
    {
        if (loading) return;
        dirty = true;
        Message.IsOpen = false;
    }

    private async void StockSearch_TextChanged(AutoSuggestBox sender, AutoSuggestBoxTextChangedEventArgs args)
    {
        if (args.Reason != AutoSuggestionBoxTextChangeReason.UserInput) return;
        if (await debounce.Pause() is not { } ticket) return;
        var q = sender.Text.Trim();
        if (q.Length == 0) { sender.ItemsSource = null; return; }
        var r = await AppState.Call(c => c.SearchStocksAsync(q));
        if (!debounce.IsLatest(ticket)) return;
        if (!r.Ok) { Ui.Show(Message, r.Error); return; }
        found.Clear();
        foreach (var s in r.Value!) found[$"{s.Symbol}  {s.Name}"] = s;
        sender.ItemsSource = found.Count > 0 ? found.Keys.ToList() : new List<string> { "No company found" };
    }

    private void StockSearch_SuggestionChosen(AutoSuggestBox sender, AutoSuggestBoxSuggestionChosenEventArgs args)
    {
        if (args.SelectedItem is not string label || !found.TryGetValue(label, out var s)) return;
        if (!watchlist.Add(s))
        {
            Ui.Show(Message, watchlist.Items.Count >= Watchlist.Max ? "The watchlist holds at most 30 stocks." : s.Symbol + " is already on the list.");
            return;
        }
        BuildList();
        Changed(this, null!);
        sender.Text = "";
    }

    private async void Save_Click(object sender, RoutedEventArgs e)
    {
        news["biz_nyt"] = NytSwitch.IsOn;
        news["biz_cnbc"] = CnbcSwitch.IsOn;
        SaveButton.IsEnabled = false;
        Busy.IsActive = true;
        var r = await AppState.Call(c => c.SaveBusinessAsync(new Business(OnSwitch.IsOn, watchlist.Items, news)));
        Busy.IsActive = false;
        SaveButton.IsEnabled = true;
        if (r.Ok) dirty = false;
        Ui.Show(Message, r.Error, Ui.Saved);
    }
}
