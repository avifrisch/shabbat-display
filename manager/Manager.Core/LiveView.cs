namespace Manager.Core;

/// <summary>The display page as the app's live view shows it.</summary>
public static class LiveView
{
    /// <summary>The house rotation (no screen), or one screen's page marked as a preview,
    /// so the server doesn't count it as that screen checking in.</summary>
    public static Uri PageUrl(Uri server, string? screen) => screen is null
        ? server
        : new Uri(server, "?screen=" + Uri.EscapeDataString(screen) + "&preview=1");
}
