namespace Manager.Tests;

public class Smoke
{
    [Fact]
    public void Core_loads() => Assert.NotNull(typeof(Manager.Core.ManageClient));
}
