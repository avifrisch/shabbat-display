namespace ShabbatSaver;

/// <summary>The little picture in the Screen Saver Settings dialog: a window inside the one Windows hands over.</summary>
internal sealed class PreviewWindow : Form
{
    private const int WS_CHILD = 0x40000000, WS_VISIBLE = 0x10000000;
    private readonly nint parent;
    private readonly System.Windows.Forms.Timer watch = new() { Interval = 500 };

    public PreviewWindow(nint parent)
    {
        this.parent = parent;
        FormBorderStyle = FormBorderStyle.None;
        BackColor = ColorTranslator.FromHtml("#0D1726");
        ShowInTaskbar = false;
        if (Native.GetClientRect(parent, out var r)) Size = new Size(r.Right - r.Left, r.Bottom - r.Top);
        watch.Tick += (_, _) => { if (!Native.IsWindow(parent)) Close(); };
        watch.Start();
    }

    protected override CreateParams CreateParams
    {
        get
        {
            var cp = base.CreateParams;
            cp.Parent = parent;
            cp.Style = WS_CHILD | WS_VISIBLE;
            cp.X = cp.Y = 0;
            return cp;
        }
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        base.OnPaint(e);
        using var font = new Font("Segoe UI Semibold", Math.Max(ClientSize.Height / 8f, 6f), GraphicsUnit.Pixel);
        using var gold = new SolidBrush(ColorTranslator.FromHtml("#E5BA5E"));
        using var center = new StringFormat { Alignment = StringAlignment.Center, LineAlignment = StringAlignment.Center };
        e.Graphics.DrawString("Shabbat Display", font, gold, ClientRectangle, center);
    }
}
