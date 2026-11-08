using Manager.Core;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;

namespace ShabbatManager.Pages;

/// <summary>Each league on or off, its teams, and the favorite whose games get their own scene.</summary>
public sealed partial class SportsPage : Page
{
    private Dictionary<string, League> sports = [];
    private readonly Dictionary<string, StackPanel> bodies = [];
    private Dictionary<string, string> names = [];
    private bool dirty;

    public SportsPage()
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
        sports = new(h.Sports);
        names = new() { ["mlb"] = "MLB" };
        foreach (var (k, v) in h.Leagues) names[k] = v;
        Build();
        SaveButton.IsEnabled = true;
        dirty = false;
    }

    private IEnumerable<string> Order() => names.Keys.Where(sports.ContainsKey);

    private void Build()
    {
        Leagues.Children.Clear();
        bodies.Clear();
        foreach (var key in Order())
        {
            var on = new ToggleSwitch { IsOn = sports[key].On, OnContent = "On", OffContent = "Off", MinWidth = 0 };
            AutomationProperties.SetName(on, names[key] + " on");
            on.Toggled += (_, _) => { sports[key] = sports[key] with { On = on.IsOn }; Changed(); };
            var header = new Grid { HorizontalAlignment = HorizontalAlignment.Stretch };
            header.ColumnDefinitions.Add(new ColumnDefinition());
            header.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            header.Children.Add(Ui.Text(names[key], wrap: false));
            Grid.SetColumn(on, 1);
            header.Children.Add(on);
            var body = new StackPanel { Spacing = 4 };
            bodies[key] = body;
            var expander = new Expander
            {
                Header = header,
                Content = body,
                HorizontalAlignment = HorizontalAlignment.Stretch,
                HorizontalContentAlignment = HorizontalAlignment.Stretch,
                IsExpanded = sports[key].On,
            };
            AutomationProperties.SetName(expander, names[key]);
            Leagues.Children.Add(expander);
            BuildBody(key);
        }
    }

    private void BuildBody(string key)
    {
        var body = bodies[key];
        body.Children.Clear();
        var league = sports[key];
        if (league.Teams.Count == 0)
            body.Children.Add(Ui.Note("No teams chosen. Its scores page still shows every game."));
        foreach (var t in league.Teams)
        {
            var fav = league.Favorite == t.Id;
            var row = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 4 };
            row.Children.Add(Ui.IconButton(fav ? Ui.StarFilled : Ui.Star, fav ? "Favorite team" : "Make this the favorite team",
                () => { sports[key] = LeagueRules.SetFavorite(sports[key], t.Id); Changed(); BuildBody(key); }, fav ? Ui.Gold : null));
            row.Children.Add(Ui.Text(t.Name + (fav ? "  (favorite: gets its own scene)" : ""), wrap: false));
            row.Children.Add(Ui.IconButton(Ui.Remove, "Remove " + t.Name,
                () => { sports[key] = LeagueRules.Remove(sports[key], t.Id); Changed(); BuildBody(key); }));
            body.Children.Add(row);
        }
        body.Children.Add(TeamSearch(key));
    }

    private AutoSuggestBox TeamSearch(string key)
    {
        var box = new AutoSuggestBox { PlaceholderText = "Add a team", Width = 320, HorizontalAlignment = HorizontalAlignment.Left, Margin = new Thickness(0, 6, 0, 4) };
        AutomationProperties.SetName(box, "Add a " + names[key] + " team");
        var found = new Dictionary<string, Team>();
        var debounce = new Debouncer(250);
        box.TextChanged += async (s, args) =>
        {
            if (args.Reason != AutoSuggestionBoxTextChangeReason.UserInput) return;
            if (await debounce.Pause() is not { } ticket) return;
            var q = s.Text.Trim();
            if (q.Length == 0) { s.ItemsSource = null; return; }
            var r = await AppState.Call(c => c.SearchTeamsAsync(key, q));
            if (!debounce.IsLatest(ticket)) return;
            if (!r.Ok) { Ui.Show(Message, r.Error); return; }
            found.Clear();
            foreach (var t in r.Value!) found[$"{t.Name} ({t.Abbr})"] = t;
            s.ItemsSource = found.Count > 0 ? found.Keys.ToList() : new List<string> { "No team found" };
        };
        box.SuggestionChosen += (s, args) =>
        {
            if (args.SelectedItem is string label && found.TryGetValue(label, out var t))
            {
                sports[key] = LeagueRules.Add(sports[key], t);
                Changed();
                BuildBody(key);
            }
        };
        return box;
    }

    private void Changed()
    {
        dirty = true;
        Message.IsOpen = false;
    }

    private async void Save_Click(object sender, RoutedEventArgs e)
    {
        SaveButton.IsEnabled = false;
        Busy.IsActive = true;
        var r = await AppState.Call(c => c.SaveSportsAsync(sports));
        Busy.IsActive = false;
        SaveButton.IsEnabled = true;
        if (r.Ok) dirty = false;
        Ui.Show(Message, r.Error, Ui.Saved);
    }
}
