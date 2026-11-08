using Manager.Core;

namespace Manager.Tests;

public class RotationTests
{
    private static readonly List<SceneInfo> Catalog =
        [new("shul", "Shul"), new("news", "Headlines"), new("nba_team", "NBA team"), new("nba", "Around the NBA")];

    [Fact]
    public void Empty_rotation_cannot_be_saved()
    {
        var e = new RotationEditor([new("news", 30, true)], Catalog);
        e.Toggle(0); Assert.Equal("Choose at least one scene.", e.Validate());
        e.Toggle(0); Assert.Null(e.Validate());
        Assert.Equal("Choose at least one scene.", new RotationEditor([], Catalog).Validate());
    }

    [Fact]
    public void Seconds_are_clamped_and_moves_work()
    {
        var e = new RotationEditor([new("shul", 30, true), new("news", 30, true)], Catalog);
        e.SetSeconds(0, 2); e.MoveDown(0);
        Assert.Equal(new[] { "news", "shul" }, e.Items.Select(i => i.Scene)); Assert.Equal(5, e.Items[1].Seconds);
        e.SetSeconds(0, 1000); Assert.Equal(300, e.Items[0].Seconds);
        e.MoveUp(0); e.MoveDown(1);   // ends stay put
        Assert.Equal(new[] { "news", "shul" }, e.Items.Select(i => i.Scene));
    }

    [Fact]
    public void Editor_works_on_its_own_copy()
    {
        var house = new List<RotationItem> { new("shul", 30, true) };
        new RotationEditor(house, Catalog).Toggle(0);
        Assert.True(house[0].On);
    }

    [Fact]
    public void Labels_come_from_the_catalog()
    {
        var e = new RotationEditor([new("nba", 30, true), new("old_scene", 30, true)], Catalog);
        Assert.Equal("Around the NBA", e.Label(0));
        Assert.Equal("old_scene", e.Label(1));
    }

    [Fact]
    public void Copy_of_house_rotation_gets_new_scenes_off()
    {
        var e = new RotationEditor([new("shul", 30, true)], Catalog);
        e.AddMissingFromCatalog();
        Assert.Equal(new[] { "shul", "news", "nba_team", "nba" }, e.Items.Select(i => i.Scene));
        Assert.All(e.Items.Skip(1), i => Assert.False(i.On));
        Assert.True(e.Items[0].On);
    }
}
