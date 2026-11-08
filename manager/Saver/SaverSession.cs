using Microsoft.Web.WebView2.Core;
using SaverConfig = Manager.Core.SaverConfig;
using InputGate = Manager.Core.InputGate;
using WinScreen = System.Windows.Forms.Screen;

namespace ShabbatSaver;

/// <summary>One screen saver run: a window on every monitor, closed by any input except over Shabbat and Yom Tov.</summary>
internal sealed class SaverSession
{
    private static readonly string ConfigFile = Path.Combine(Path.GetDirectoryName(Environment.ProcessPath) ?? "", "saver.json");
    private static readonly string WebFolder =
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "ShabbatDisplay", "SaverWebView2");

    private readonly List<SaverForm> forms = [];
    private readonly InputGate gate = new(Native.LastInputTick());
    private readonly System.Windows.Forms.Timer inputTimer = new() { Interval = 50 };
    private readonly System.Windows.Forms.Timer secondTimer = new() { Interval = 1000 };
    private int seconds;
    private Task<CoreWebView2Environment>? browser;

    public SaverConfig? Config { get; private set; } = ReadConfig();

    public bool Holy => Config?.IsHoly(DateTimeOffset.Now) == true;

    /// <summary>One browser for all the monitors, with its own data folder.</summary>
    public Task<CoreWebView2Environment> Browser()
    {
        Directory.CreateDirectory(WebFolder);
        if (browser is { IsFaulted: true } or { IsCanceled: true }) browser = null;   // a failed start is tried again
        return browser ??= CoreWebView2Environment.CreateAsync(null, WebFolder);
    }

    /// <summary>The shared browser died: the next window to need one starts a new one. Every window reports
    /// the same death, so only the browser that died is forgotten, not one already started in its place.</summary>
    public void BrowserDied(CoreWebView2Environment dead)
    {
        if (browser is { IsCompletedSuccessfully: true } t && ReferenceEquals(t.Result, dead)) browser = null;
    }

    public void Start()
    {
        var screens = WinScreen.AllScreens.OrderByDescending(s => s.Primary).ThenBy(s => s.Bounds.Left).ToList();
        for (var i = 0; i < screens.Count; i++)
        {
            var form = new SaverForm(this, i, screens[i]);
            forms.Add(form);
            form.Show();
        }
        Cursor.Hide();
        inputTimer.Tick += (_, _) =>
        {
            if (gate.ShouldClose(Native.LastInputTick(), Holy)) Close();
        };
        secondTimer.Tick += (_, _) =>
        {
            Native.HoldScreens(Config?.HoldScreens(DateTimeOffset.Now) == true);
            if (++seconds % 60 == 0 && ReadConfig() is { } fresh) Config = fresh;   // the launcher may have new Shabbat times
            foreach (var f in forms) f.Tick();
        };
        Native.HoldScreens(Config?.HoldScreens(DateTimeOffset.Now) == true);
        inputTimer.Start();
        secondTimer.Start();
    }

    /// <summary>Gone at once: hide every window, then end the process without waiting on the browser.</summary>
    public void Close()
    {
        foreach (var f in forms) f.Hide();
        Environment.Exit(0);
    }

    private static SaverConfig? ReadConfig()
    {
        try { return SaverConfig.Load(File.ReadAllText(ConfigFile)); }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException) { return null; }
    }
}
