using Manager.Core;

namespace ShabbatSaver;

internal static class Program
{
    public const string ManagedHere = "The Shabbat Display screen saver is managed from the Shabbat Display Manager app.";

    [STAThread]
    private static void Main(string[] args)
    {
        var launch = SaverLaunch.Parse(args);
        ApplicationConfiguration.Initialize();
        switch (launch.Action)
        {
            case SaverAction.Show:
                using (new Mutex(true, @"Local\ShabbatDisplayScreenSaver", out var first))
                {
                    if (!first) return;   // Windows started it twice (the launcher's own mutex is ShabbatDisplaySaver)
                    new SaverSession().Start();
                    Application.Run();
                }
                break;
            case SaverAction.Preview:
                Application.Run(new PreviewWindow(launch.Parent));
                break;
            default:
                MessageBox.Show(ManagedHere, "Shabbat Display", MessageBoxButtons.OK, MessageBoxIcon.Information);
                break;
        }
    }
}
