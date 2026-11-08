using System.Runtime.InteropServices;

namespace ShabbatSaver;

internal static class Native
{
    [StructLayout(LayoutKind.Sequential)]
    private struct LASTINPUTINFO { public uint cbSize; public uint dwTime; }

    [DllImport("user32.dll")]
    private static extern bool GetLastInputInfo(ref LASTINPUTINFO info);

    /// <summary>The tick of the last mouse or keyboard input anywhere on this PC.</summary>
    public static uint LastInputTick()
    {
        var info = new LASTINPUTINFO { cbSize = (uint)Marshal.SizeOf<LASTINPUTINFO>() };
        return GetLastInputInfo(ref info) ? info.dwTime : 0;
    }

    private const uint ES_CONTINUOUS = 0x80000000, ES_SYSTEM_REQUIRED = 0x00000001, ES_DISPLAY_REQUIRED = 0x00000002;

    [DllImport("kernel32.dll")]
    private static extern uint SetThreadExecutionState(uint flags);

    /// <summary>Hold the PC awake and the screens on, or let the power settings decide.</summary>
    public static void HoldScreens(bool on) =>
        SetThreadExecutionState(on ? ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED : ES_CONTINUOUS);

    [DllImport("user32.dll")]
    private static extern bool SetWindowPos(nint hWnd, nint after, int x, int y, int cx, int cy, uint flags);

    /// <summary>Above every ordinary window, without taking the focus.</summary>
    public static void KeepOnTop(nint hWnd) =>
        SetWindowPos(hWnd, -1 /* HWND_TOPMOST */, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010 /* NOSIZE | NOMOVE | NOACTIVATE */);

    [DllImport("user32.dll")]
    public static extern bool IsWindow(nint hWnd);

    [DllImport("user32.dll")]
    private static extern nint SetParent(nint child, nint parent);

    /// <summary>Put a child window inside another program's window.</summary>
    public static void MoveInto(nint child, nint parent) => SetParent(child, parent);

    [DllImport("user32.dll")]
    private static extern nint GetWindowDpiAwarenessContext(nint hWnd);

    [DllImport("user32.dll")]
    private static extern nint SetThreadDpiAwarenessContext(nint context);

    /// <summary>A child window in another program must share its DPI mode, or Windows won't host it.</summary>
    public static void MatchDpiOf(nint window)
    {
        var context = GetWindowDpiAwarenessContext(window);
        if (context != 0) SetThreadDpiAwarenessContext(context);
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct RECT { public int Left, Top, Right, Bottom; }

    [DllImport("user32.dll")]
    public static extern bool GetClientRect(nint hWnd, out RECT rect);
}
