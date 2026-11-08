using System.Runtime.InteropServices;

namespace ShabbatSaver;

/// <summary>The little picture in the Screen Saver Settings dialog: a child of the window Windows hands over.
/// A plain window, not a Form: WinForms parks a Form's handle under a window of its own instead of another
/// program's. Program.cs first matches that window's DPI mode, which Windows requires of such a child.</summary>
internal sealed class PreviewWindow : NativeWindow
{
    private const int WS_CHILD = 0x40000000, WS_VISIBLE = 0x10000000;
    private const int WM_PAINT = 0x000F, WM_ERASEBKGND = 0x0014;
    private readonly nint parent;
    private readonly System.Windows.Forms.Timer watch = new() { Interval = 500 };

    public PreviewWindow(nint parent)
    {
        this.parent = parent;
        Native.GetClientRect(parent, out var r);
        CreateHandle(new CreateParams
        {
            Parent = parent,
            Style = WS_CHILD | WS_VISIBLE,
            Width = r.Right - r.Left,
            Height = r.Bottom - r.Top,
        });
        watch.Tick += (_, _) =>
        {
            if (Native.IsWindow(parent)) return;
            watch.Stop();
            Application.ExitThread();   // the dialog closed or showed another screen saver
        };
        watch.Start();
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct PAINTSTRUCT
    {
        public nint hdc;
        public bool fErase;
        public Native.RECT rcPaint;
        public bool fRestore, fIncUpdate;
        [MarshalAs(UnmanagedType.ByValArray, SizeConst = 32)] public byte[] rgbReserved;
    }

    [DllImport("user32.dll")]
    private static extern nint BeginPaint(nint hWnd, out PAINTSTRUCT ps);

    [DllImport("user32.dll")]
    private static extern bool EndPaint(nint hWnd, ref PAINTSTRUCT ps);

    protected override void WndProc(ref Message m)
    {
        if (m.Msg == WM_ERASEBKGND) { m.Result = 1; return; }   // painted whole in WM_PAINT
        if (m.Msg != WM_PAINT) { base.WndProc(ref m); return; }
        var hdc = BeginPaint(Handle, out var ps);
        Native.GetClientRect(Handle, out var r);
        var area = new Rectangle(0, 0, r.Right - r.Left, r.Bottom - r.Top);
        using (var g = Graphics.FromHdc(hdc))
        using (var navy = new SolidBrush(ColorTranslator.FromHtml("#0D1726")))
        using (var gold = new SolidBrush(ColorTranslator.FromHtml("#E5BA5E")))
        using (var font = new Font("Segoe UI Semibold", Math.Max(area.Height / 8f, 6f), GraphicsUnit.Pixel))
        using (var center = new StringFormat { Alignment = StringAlignment.Center, LineAlignment = StringAlignment.Center })
        {
            g.FillRectangle(navy, area);
            g.DrawString("Shabbat Display", font, gold, area, center);
        }
        EndPaint(Handle, ref ps);
    }
}
