namespace Manager.Core;

/// <summary>Finds the display server: the address that worked last time, then Tailscale, the PC's name, its home address.</summary>
public class ServerFinder(HttpClient http, string rememberFile)
{
    public static readonly string[] Known =
    [
        "http://100.98.145.119:8765/",
        "http://DESKTOP-H72VKDJ:8765/",
        "http://192.168.4.109:8765/",
    ];

    public static string DefaultRememberFile =>
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "ShabbatDisplayManager", "server.txt");

    public async Task<Uri?> FindAsync()
    {
        foreach (var candidate in Candidates())
        {
            if (!Uri.TryCreate(candidate, UriKind.Absolute, out var u)) continue;
            if (await Answers(u))
            {
                Remember(u);
                return u;
            }
        }
        return null;
    }

    private IEnumerable<string> Candidates()
    {
        string? remembered = null;
        try
        {
            if (File.Exists(rememberFile)) remembered = File.ReadAllText(rememberFile).Trim();
        }
        catch (IOException) { }
        if (!string.IsNullOrEmpty(remembered)) yield return remembered;
        foreach (var k in Known)
            if (!string.Equals(k, remembered, StringComparison.OrdinalIgnoreCase)) yield return k;
    }

    private async Task<bool> Answers(Uri u)
    {
        using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(2));
        try
        {
            using var r = await http.GetAsync(new Uri(u, "health"), cts.Token);
            return r.IsSuccessStatusCode;
        }
        catch (Exception e) when (e is HttpRequestException or TaskCanceledException)
        {
            return false;
        }
    }

    private void Remember(Uri u)
    {
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(rememberFile)!);
            File.WriteAllText(rememberFile, u.ToString());
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException) { }
    }
}
