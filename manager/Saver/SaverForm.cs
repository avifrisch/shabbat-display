using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;
using WinScreen = System.Windows.Forms.Screen;

namespace ShabbatSaver;

/// <summary>The display on one monitor, or a dark clock when the always-on PC can't be reached.</summary>
internal sealed class SaverForm : Form
{
    private static readonly Color Navy = ColorTranslator.FromHtml("#0D1726");

    private readonly SaverSession session;
    private readonly int index;
    private readonly Rectangle bounds;
    private readonly Fallback fallback = new() { Dock = DockStyle.Fill };
    private WebView2? web;   // made again after its browser process dies
    private CoreWebView2Environment? env;   // the browser it runs in
    private int sinceTry;
    private bool webReady, starting, showingWeb;

    public SaverForm(SaverSession session, int index, WinScreen screen)
    {
        this.session = session;
        this.index = index;
        bounds = screen.Bounds;
        FormBorderStyle = FormBorderStyle.None;
        StartPosition = FormStartPosition.Manual;
        Bounds = bounds;
        TopMost = true;
        ShowInTaskbar = false;
        BackColor = Navy;
        Text = "Shabbat Display";
        Controls.Add(fallback);
    }

    protected override async void OnShown(EventArgs e)
    {
        base.OnShown(e);
        Bounds = bounds;   // again, now that the window is on its monitor (it may have another DPI)
        Native.KeepOnTop(Handle);
        await StartWeb();
        Navigate();
    }

    /// <summary>A browser in this window, unless one is ready or on its way.</summary>
    private async Task StartWeb()
    {
        if (webReady || starting) return;
        starting = true;
        try
        {
            if (web is null)
            {
                web = new WebView2 { Dock = DockStyle.Fill, Visible = false, DefaultBackgroundColor = Navy };
                Controls.Add(web);
            }
            env = await session.Browser();
            await web.EnsureCoreWebView2Async(env);
            var s = web.CoreWebView2.Settings;
            s.AreDefaultContextMenusEnabled = false;
            s.AreDevToolsEnabled = false;
            s.IsZoomControlEnabled = false;
            s.AreBrowserAcceleratorKeysEnabled = false;
            s.IsStatusBarEnabled = false;
            web.CoreWebView2.NavigationCompleted += (_, a) =>
            {
                if (a.IsSuccess) ShowWeb(); else ShowFallback();
            };
            web.CoreWebView2.ProcessFailed += (_, a) => BrowserFailed(a.ProcessFailedKind);
            webReady = true;
        }
        catch (Exception)   // no WebView2 runtime, or it couldn't start: try again in 30 s
        {
            DropWeb();
            fallback.ShowWords = true;
        }
        finally
        {
            starting = false;
        }
    }

    /// <summary>A page that crashed is loaded again on the next retry; a browser that died is replaced,
    /// with a new browser process, so the display comes back without anyone touching it.</summary>
    private void BrowserFailed(CoreWebView2ProcessFailedKind kind)
    {
        ShowFallback();
        if (kind == CoreWebView2ProcessFailedKind.BrowserProcessExited) BrowserGone();
    }

    /// <summary>Forget this browser (a dead one can't be asked anything), so the next retry starts a new one.</summary>
    private void BrowserGone()
    {
        if (env is not null) session.BrowserDied(env);
        env = null;
        DropWeb();
    }

    private void DropWeb()
    {
        webReady = false;
        if (web is null) return;
        Controls.Remove(web);
        try { web.Dispose(); } catch (Exception) { }   // its browser is already gone
        web = null;
    }

    protected override void OnDpiChanged(DpiChangedEventArgs e)
    {
        e.Cancel = true;   // keep covering exactly this monitor
        Bounds = bounds;
    }

    protected override void OnFormClosing(FormClosingEventArgs e)
    {
        // Over Shabbat and Yom Tov nothing closes it (Alt+F4, a stray WM_CLOSE); signing out or shutting down always works
        if (e.CloseReason != CloseReason.WindowsShutDown && session.Holy) { e.Cancel = true; return; }
        session.Close();
    }

    /// <summary>Every second: on top (a second window's creation can drop the first's topmost flag), the clock,
    /// the words after 10 s without the display, a retry every 30 s.</summary>
    public void Tick()
    {
        Native.KeepOnTop(Handle);
        fallback.Invalidate();
        if (showingWeb) return;
        sinceTry++;
        if (sinceTry >= 10) fallback.ShowWords = true;
        if (sinceTry >= 30) _ = Retry();
    }

    private async Task Retry()
    {
        sinceTry = 0;
        await StartWeb();
        Navigate();
    }

    private void Navigate()
    {
        sinceTry = 0;
        if (!webReady || web is null || session.Config is not { } config) return;
        try { web.CoreWebView2.Navigate(config.PageUrl(index).AbsoluteUri); }
        catch (Exception)   // its browser is gone, whether or not ProcessFailed said so
        {
            ShowFallback();
            BrowserGone();
        }
    }

    private void ShowWeb()
    {
        showingWeb = true;
        if (web is not null) web.Visible = true;
        fallback.Visible = false;
    }

    private void ShowFallback()
    {
        showingWeb = false;
        fallback.ShowWords = true;
        fallback.Visible = true;
        if (web is not null) web.Visible = false;
    }

    /// <summary>The display's dark background with a clock, and a quiet line when it can't be reached.</summary>
    private sealed class Fallback : Control
    {
        private bool words;

        public Fallback()
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.UserPaint, true);
            BackColor = Navy;
        }

        [System.ComponentModel.DesignerSerializationVisibility(System.ComponentModel.DesignerSerializationVisibility.Hidden)]
        public bool ShowWords
        {
            get => words;
            set { words = value; Invalidate(); }
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            base.OnPaint(e);
            var g = e.Graphics;
            g.TextRenderingHint = System.Drawing.Text.TextRenderingHint.AntiAliasGridFit;
            var h = Math.Max(ClientSize.Height, 1);
            using var clockFont = new Font("Segoe UI Light", h / 6f, GraphicsUnit.Pixel);
            using var smallFont = new Font("Segoe UI", h / 36f, GraphicsUnit.Pixel);
            using var warm = new SolidBrush(ColorTranslator.FromHtml("#F2EBDD"));
            using var dim = new SolidBrush(ColorTranslator.FromHtml("#7F8797"));
            using var center = new StringFormat { Alignment = StringAlignment.Center, LineAlignment = StringAlignment.Center };
            g.DrawString(DateTime.Now.ToString("h:mm"), clockFont, warm, new RectangleF(0, 0, ClientSize.Width, h * 0.9f), center);
            if (words)
                g.DrawString("Display not reachable", smallFont, dim, new RectangleF(0, h * 0.58f, ClientSize.Width, h * 0.1f), center);
        }
    }
}
