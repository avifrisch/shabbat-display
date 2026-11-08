namespace Manager.Core;

/// <summary>The editing rules for one rotation. Works on its own copy of the list.</summary>
public class RotationEditor(List<RotationItem> items, IReadOnlyList<SceneInfo> catalog)
{
    public const int MinSeconds = 5;
    public const int MaxSeconds = 300;

    private readonly HashSet<string> given = [.. items.Select(i => i.Scene)];

    public List<RotationItem> Items { get; } = [.. items];

    /// <summary>The list to save: scenes added from the catalog and left off are dropped. The server counts an off
    /// scene as present, so saving one would stop it adding that league when the league is switched on.</summary>
    public List<RotationItem> ItemsToSave() => [.. Items.Where(i => i.On || given.Contains(i.Scene))];

    public string Label(int i) => catalog.FirstOrDefault(c => c.Scene == Items[i].Scene)?.Label ?? Items[i].Scene;

    public void MoveUp(int i)
    {
        if (i > 0 && i < Items.Count) (Items[i - 1], Items[i]) = (Items[i], Items[i - 1]);
    }

    public void MoveDown(int i)
    {
        if (i >= 0 && i < Items.Count - 1) (Items[i + 1], Items[i]) = (Items[i], Items[i + 1]);
    }

    public void Toggle(int i) => Items[i] = Items[i] with { On = !Items[i].On };

    public void SetOn(int i, bool on) => Items[i] = Items[i] with { On = on };

    public void SetSeconds(int i, int seconds) => Items[i] = Items[i] with { Seconds = Math.Clamp(seconds, MinSeconds, MaxSeconds) };

    /// <summary>Scenes the server offers that aren't in the list yet, added at the end switched off.</summary>
    public void AddMissingFromCatalog()
    {
        foreach (var c in catalog)
            if (!Items.Any(i => i.Scene == c.Scene))
                Items.Add(new RotationItem(c.Scene, 30, false));
    }

    public string? Validate() => Items.Any(i => i.On) ? null : "Choose at least one scene.";
}
