using Manager.Core;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Navigation;

namespace ShabbatManager.Pages;

/// <summary>The family's lists (shopping and to-do) and the sets of usual Walmart items. Every change is sent at once.</summary>
public sealed partial class ListsPage : Page
{
    private ListsState state = new([], []);
    private string listId = "", setId = "";
    private bool building;

    public ListsPage()
    {
        InitializeComponent();
    }

    protected override void OnNavigatedTo(NavigationEventArgs e) => _ = Load();

    private void Refresh_Click(object sender, RoutedEventArgs e) => _ = Load();

    private ShopList? ThisList => state.Lists?.FirstOrDefault(l => l.Id == listId) ?? state.Lists?.FirstOrDefault();
    private UsualSet? ThisSet => state.Sets?.FirstOrDefault(s => s.Id == setId) ?? state.Sets?.FirstOrDefault();

    private async Task Load()
    {
        Busy.IsActive = true;
        var r = await AppState.Call(c => c.GetListsAsync());
        Busy.IsActive = false;
        Take(r, null);
    }

    /// <summary>Sends one change and shows what the server now has.</summary>
    private async Task<bool> Change(string op, string? done, params (string Key, object? Value)[] more)
    {
        Busy.IsActive = true;
        var r = await AppState.Call(c => c.ChangeListsAsync(op, more));
        Busy.IsActive = false;
        return Take(r, done);
    }

    private bool Take(Result<ListsState> r, string? done)
    {
        Ui.Show(Message, r.Error, done);
        if (r.Value is not { } s) return false;
        if (s.Lists is not { Count: > 0 } || s.Sets is not { Count: > 0 })
        {
            Ui.Show(Message, ManageClient.NeedsUpdate);
            return false;
        }
        state = s;
        Build();
        return true;
    }

    private void Build()
    {
        building = true;
        var list = ThisList!;
        var set = ThisSet!;
        listId = list.Id;
        setId = set.Id;
        ListPick.ItemsSource = state.Lists!.Select(l => l.IsTodo ? l.Name + " (to-do)" : l.Name).ToList();
        ListPick.SelectedIndex = state.Lists!.IndexOf(list);
        SetPick.ItemsSource = state.Sets!.Select(s => s.Name).ToList();
        SetPick.SelectedIndex = state.Sets!.IndexOf(set);
        building = false;

        var main = list == state.Lists[0];
        DeleteList.IsEnabled = !main;
        ClearList.IsEnabled = list.Items.Count > 0;
        ItemText.PlaceholderText = list.IsTodo ? "Add a job" : "Add an item";
        Items.Children.Clear();
        if (list.Items.Count == 0) Items.Children.Add(Ui.Note("Nothing on this list."));
        foreach (var text in list.Items)
        {
            var item = text;
            Items.Children.Add(Row(Ui.Text(item), null,
                Ui.IconButton(Ui.Remove, "Remove " + item, () => _ = Change("remove_item", null, ("list", listId), ("text", item)))));
        }

        DeleteSet.IsEnabled = state.Sets.Count > 1;
        SetToList.IsEnabled = set.Items.Count > 0;
        Usuals.Children.Clear();
        if (set.Items.Count == 0) Usuals.Children.Add(Ui.Note("No usual items in this set."));
        foreach (var u in set.Items)
        {
            var usual = u;
            var buttons = new StackPanel { Orientation = Orientation.Horizontal };
            if (state.Sets.Count > 1)
            {
                var menu = new MenuFlyout();
                foreach (var other in state.Sets.Where(s => s.Id != set.Id))
                {
                    var to = other;
                    var entry = new MenuFlyoutItem { Text = to.Name };
                    entry.Click += (_, _) => _ = Change("move_usual", null, ("id", usual.Id), ("set", to.Id));
                    menu.Items.Add(entry);
                }
                var move = new Button { Content = "Move to", Flyout = menu, Padding = new Thickness(8, 4, 8, 4) };
                Microsoft.UI.Xaml.Automation.AutomationProperties.SetName(move, "Move " + usual.Name + " to another set");
                buttons.Children.Add(move);
            }
            buttons.Children.Add(Ui.IconButton(Ui.Remove, "Remove " + usual.Name, () => _ = Change("remove_usual", null, ("id", usual.Id))));
            var note = Ui.Text(usual.ItemId.Length > 0 ? "Walmart item " + usual.ItemId : "No product link: left out of the cart",
                               usual.ItemId.Length > 0 ? Ui.Dim : Ui.Amber, wrap: false);
            Usuals.Children.Add(Row(Ui.Text(usual.Label), note, buttons));
        }
    }

    private static Grid Row(UIElement name, UIElement? note, UIElement buttons)
    {
        var row = new Grid { ColumnSpacing = 12 };
        row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        row.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        row.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        row.Children.Add(name);
        if (note is not null)
        {
            Grid.SetColumn((FrameworkElement)note, 1);
            row.Children.Add(note);
        }
        Grid.SetColumn((FrameworkElement)buttons, 2);
        row.Children.Add(buttons);
        return row;
    }

    private void ListPick_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (building || ListPick.SelectedIndex < 0) return;
        listId = state.Lists![ListPick.SelectedIndex].Id;
        Build();
    }

    private void SetPick_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (building || SetPick.SelectedIndex < 0) return;
        setId = state.Sets![SetPick.SelectedIndex].Id;
        Build();
    }

    // -- lists

    private async void AddItem_Click(object sender, RoutedEventArgs e)
    {
        var text = ItemText.Text.Trim();
        if (text.Length == 0) return;
        if (await Change("add_item", null, ("list", listId), ("text", text))) ItemText.Text = "";
        ItemText.Focus(FocusState.Programmatic);
    }

    private void ItemText_KeyDown(object sender, KeyRoutedEventArgs e)
    {
        if (e.Key != Windows.System.VirtualKey.Enter) return;
        e.Handled = true;
        AddItem_Click(sender, e);
    }

    private async void NewList_Click(object sender, RoutedEventArgs e)
    {
        var kind = new ComboBox { Header = "Kind", ItemsSource = new List<string> { "Shopping list", "To-do list" }, SelectedIndex = 0, Width = 280 };
        if (await AskName("New list", "", "Create", kind) is not { } name) return;
        if (await Change("create_list", null, ("name", name), ("kind", kind.SelectedIndex == 1 ? "todo" : "shopping")))
        {
            listId = state.Lists!.FirstOrDefault(l => string.Equals(l.Name, name, StringComparison.OrdinalIgnoreCase))?.Id ?? listId;
            Build();
        }
    }

    private async void RenameList_Click(object sender, RoutedEventArgs e)
    {
        if (ThisList is not { } list || await AskName("Rename the list", list.Name, "Rename") is not { } name) return;
        await Change("rename_list", null, ("list", list.Id), ("name", name));
    }

    private async void ClearList_Click(object sender, RoutedEventArgs e)
    {
        if (ThisList is not { } list || !await Confirm($"Take everything off {list.Name}?", "Empty it")) return;
        await Change("clear_list", null, ("list", list.Id));
    }

    private async void DeleteList_Click(object sender, RoutedEventArgs e)
    {
        if (ThisList is not { } list || !await Confirm($"Delete the list {list.Name} and what is on it?", "Delete")) return;
        await Change("delete_list", null, ("list", list.Id));
    }

    // -- usual items

    private async void AddUsual_Click(object sender, RoutedEventArgs e)
    {
        var qty = double.IsNaN(UsualQty.Value) ? 1 : (int)Math.Clamp(UsualQty.Value, 1, 24);
        if (!await Change("add_usual", null, ("set", setId), ("name", UsualName.Text.Trim()), ("link", UsualLink.Text.Trim()), ("qty", qty))) return;
        UsualName.Text = "";
        UsualLink.Text = "";
        UsualQty.Value = 1;
    }

    private async void NewSet_Click(object sender, RoutedEventArgs e)
    {
        if (await AskName("New set of usual items", "", "Create") is not { } name) return;
        if (await Change("create_set", null, ("name", name)))
        {
            setId = state.Sets!.FirstOrDefault(s => string.Equals(s.Name, name, StringComparison.OrdinalIgnoreCase))?.Id ?? setId;
            Build();
        }
    }

    private async void RenameSet_Click(object sender, RoutedEventArgs e)
    {
        if (ThisSet is not { } set || await AskName("Rename the set", set.Name, "Rename") is not { } name) return;
        await Change("rename_set", null, ("set", set.Id), ("name", name));
    }

    private async void SetToList_Click(object sender, RoutedEventArgs e)
    {
        if (ThisSet is not { } set) return;
        await Change("set_to_list", $"The {set.Name} items are on the shopping list.", ("set", set.Id));
    }

    private async void DeleteSet_Click(object sender, RoutedEventArgs e)
    {
        if (ThisSet is not { } set || !await Confirm($"Delete the set {set.Name} and its {set.Items.Count} items?", "Delete")) return;
        await Change("delete_set", null, ("set", set.Id));
    }

    // -- dialogs

    private async Task<string?> AskName(string title, string start, string go, UIElement? extra = null)
    {
        var box = new TextBox { Header = "Name", Text = start, MaxLength = 30, Width = 280 };
        var panel = new StackPanel { Spacing = 12 };
        panel.Children.Add(box);
        if (extra is not null) panel.Children.Add(extra);
        var dialog = new ContentDialog
        {
            Title = title, Content = panel, PrimaryButtonText = go, CloseButtonText = "Cancel",
            DefaultButton = ContentDialogButton.Primary, XamlRoot = XamlRoot,
        };
        if (await dialog.ShowAsync() != ContentDialogResult.Primary) return null;
        var name = box.Text.Trim();
        return name.Length == 0 ? null : name;
    }

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
