using Manager.Core;

namespace Manager.Tests;

public class LiveViewTests
{
    private static readonly Uri Server = new("http://100.98.145.119:8765/");

    [Fact]
    public void House_rotation_is_the_plain_page()
    {
        Assert.Equal("http://100.98.145.119:8765/", LiveView.PageUrl(Server, null).ToString());
    }

    [Fact]
    public void A_screen_is_shown_as_a_preview_so_it_does_not_count_as_checking_in()
    {
        Assert.Equal("http://100.98.145.119:8765/?screen=Ariela%27s%20Acer&preview=1",
            LiveView.PageUrl(Server, "Ariela's Acer").AbsoluteUri);
    }
}
