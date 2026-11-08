using Manager.Core;

namespace Manager.Tests;

public class ClientTests
{
    private static ManageClient Client(FakeHandler h) => new(new HttpClient(h), new Uri("http://test:8765/"), "k123");

    [Fact]
    public async Task Sends_key_header()
    {
        var h = new FakeHandler("{\"ok\":true}"); var c = Client(h);
        await c.GetStatusAsync();
        Assert.Equal("k123", h.Last!.Headers.GetValues("X-Manage-Key").Single());
        Assert.Equal("http://test:8765/api/manage/status", h.Last.RequestUri!.ToString());
    }

    [Fact]
    public async Task Client_maps_errors_to_sentences()
    {
        Assert.Equal("The access code was refused. Enter it again.", (await Client(new FakeHandler("{}", 401)).GetStatusAsync()).Error);
        Assert.StartsWith("The display server isn't answering", (await Client(FakeHandler.Throws()).GetStatusAsync()).Error);
        Assert.Equal("The server answered 502.", (await Client(new FakeHandler("<html>", 502)).GetStatusAsync()).Error);
        Assert.Equal("The display server needs updating to work with this app.", (await Client(new FakeHandler("{\"ok\":false,\"error\":\"not found\"}", 404)).GetStatusAsync()).Error);
    }

    [Fact]
    public async Task Bad_request_surfaces_server_error()
    {
        var r = await Client(new FakeHandler("{\"ok\":false,\"error\":\"Unknown scene: nope\"}", 400)).SaveRotationAsync(null, new());
        Assert.Equal("Unknown scene: nope", r.Error);
        var busy = await Client(new FakeHandler("{\"ok\":false,\"error\":\"already updating; try again in a minute\"}", 409)).UpdateShulAsync();
        Assert.Equal("already updating; try again in a minute", busy.Error);
    }

    [Fact]
    public void Cookie_paste_is_trimmed_and_required()
    {
        Assert.Equal("abc", ManageClient.CleanCookie("  NYT-S=abc; "));
        Assert.Equal("abc", ManageClient.CleanCookie("abc"));
        Assert.Null(ManageClient.CleanCookie("   "));
        Assert.Null(ManageClient.CleanCookie("NYT-S=;"));
    }

    [Fact]
    public async Task Household_parses_snake_case()
    {
        var json = "{\"sports\":{\"nba\":{\"on\":true,\"teams\":[{\"id\":18,\"abbr\":\"NY\",\"name\":\"New York Knicks\"}],\"favorite\":18}},\"business\":{\"on\":true,\"watchlist\":[],\"news\":{}},\"default_rotation\":[{\"scene\":\"shul\",\"seconds\":30,\"on\":true}],\"screens\":{\"Den\":{\"rotation\":null,\"launcher\":true,\"saved\":false,\"mode\":\"saver\",\"saver\":{\"minutes\":10,\"lock\":true,\"shabbat\":true}}},\"nyt_signed_in\":false,\"agenda_set\":true,\"leagues\":{},\"scenes\":[]}";
        var h = (await Client(new FakeHandler(json)).GetHouseholdAsync()).Value!;
        Assert.Equal(18, h.Sports["nba"].Favorite); Assert.Equal(30, h.DefaultRotation[0].Seconds);
        Assert.True(h.Screens["Den"].Saver.Shabbat); Assert.Null(h.Screens["Den"].Rotation);
        Assert.True(h.AgendaSet);
    }

    [Fact]
    public async Task Whole_numbers_written_as_floats_still_parse()
    {
        // Python writes a float minutes setting as 10.0
        var json = "{\"sports\":{},\"business\":{\"on\":true,\"watchlist\":[],\"news\":{}},\"default_rotation\":[{\"scene\":\"shul\",\"seconds\":30.0,\"on\":true}],\"screens\":{\"Den\":{\"rotation\":null,\"launcher\":true,\"saved\":false,\"mode\":\"saver\",\"saver\":{\"minutes\":10.0,\"lock\":true,\"shabbat\":false}}},\"nyt_signed_in\":false,\"agenda_set\":false,\"leagues\":{},\"scenes\":[]}";
        var r = await Client(new FakeHandler(json)).GetHouseholdAsync();
        Assert.Null(r.Error);
        Assert.Equal(10, r.Value!.Screens["Den"].Saver.Minutes);
        Assert.Equal(30, r.Value.DefaultRotation[0].Seconds);
    }

    [Fact]
    public async Task Unsaved_screen_carries_the_pcs_own_settings()
    {
        var json = "{\"sports\":{},\"business\":{\"on\":true,\"watchlist\":[],\"news\":{}},\"default_rotation\":[],\"screens\":{\"Acer\":{\"rotation\":null,\"launcher\":true,\"saved\":false,\"mode\":\"always\",\"saver\":{\"minutes\":10,\"lock\":true,\"shabbat\":false},\"local\":{\"mode\":\"saver\",\"saver\":{\"minutes\":15.0,\"lock\":false,\"shabbat\":true}}}},\"nyt_signed_in\":false,\"agenda_set\":false,\"leagues\":{},\"scenes\":[]}";
        var acer = (await Client(new FakeHandler(json)).GetHouseholdAsync()).Value!.Screens["Acer"];
        Assert.Equal("saver", acer.Effective.Mode);
        Assert.Equal(new SaverOptions(15, false, true), acer.Effective.Saver);
    }

    [Fact]
    public void Saved_screen_uses_its_saved_settings()
    {
        var s = new Screen(null, true, true, "always", new SaverOptions(10, true, false), new LocalSettings("saver", new SaverOptions(5, true, false)));
        Assert.Equal("always", s.Effective.Mode);
    }

    [Fact]
    public async Task Odd_values_never_throw()
    {
        var json = "{\"sports\":{},\"business\":{\"on\":true,\"watchlist\":[],\"news\":{}},\"default_rotation\":[{\"scene\":\"shul\",\"seconds\":\"30\",\"on\":true}],\"screens\":{},\"nyt_signed_in\":false,\"agenda_set\":false,\"leagues\":{},\"scenes\":[]}";
        var r = await Client(new FakeHandler(json)).GetHouseholdAsync();
        Assert.Equal(ManageClient.NeedsUpdate, r.Error);
    }

    [Fact]
    public async Task Saves_send_snake_case_bodies()
    {
        var h = new FakeHandler("{\"ok\":true}"); var c = Client(h);
        var r = await c.SaveScreenAsync("Den", "saver", new SaverOptions(15, true, true));
        Assert.Null(r.Error);
        Assert.Equal(HttpMethod.Post, h.Last!.Method);
        Assert.Contains("\"saver\":{\"minutes\":15,\"lock\":true,\"shabbat\":true}", h.LastBody);
        Assert.Contains("\"name\":\"Den\"", h.LastBody);
        await c.SaveRotationAsync("Den", null);
        Assert.Contains("\"rotation\":null", h.LastBody);
    }

    [Fact]
    public async Task Bodies_carry_a_content_length()
    {
        // the server reads exactly Content-Length bytes; a streamed body arrives empty
        var h = new FakeHandler("{\"ok\":true}");
        await Client(h).SaveSportsAsync(new() { ["nba"] = new League(true, [new(18, "NY", "New York Knicks")], 18) });
        Assert.Equal(h.LastBody!.Length, h.Last!.Content!.Headers.ContentLength);
        Assert.Contains("\"nba\":{\"on\":true", h.LastBody);
    }

    [Fact]
    public async Task Old_status_without_fields_still_parses()
    {
        var s = (await Client(new FakeHandler("{\"ok\":true}")).GetStatusAsync()).Value!;
        Assert.True(s.Ok); Assert.Null(s.Feeds); Assert.Null(s.Screens);
    }

    [Fact]
    public async Task Finder_tries_in_order_and_remembers()
    {
        var h = FakeHandler.ByHost(new() { ["100.98.145.119"] = 0, ["desktop-h72vkdj"] = 200 });  // 0 = connection fails
        var file = Path.GetTempFileName();
        var u = await new ServerFinder(new HttpClient(h), file).FindAsync();
        Assert.Equal("desktop-h72vkdj", u!.Host.ToLowerInvariant());
        Assert.Contains("DESKTOP-H72VKDJ", File.ReadAllText(file), StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public async Task Finder_tries_remembered_address_first()
    {
        var h = FakeHandler.ByHost(new() { ["10.0.0.5"] = 200, ["desktop-h72vkdj"] = 200 });
        var file = Path.GetTempFileName();
        File.WriteAllText(file, "http://10.0.0.5:8765/");
        Assert.Equal("10.0.0.5", (await new ServerFinder(new HttpClient(h), file).FindAsync())!.Host);
    }

    [Fact]
    public async Task Finder_gives_null_when_nothing_answers()
    {
        Assert.Null(await new ServerFinder(new HttpClient(FakeHandler.Throws()), Path.GetTempFileName()).FindAsync());
    }
}
