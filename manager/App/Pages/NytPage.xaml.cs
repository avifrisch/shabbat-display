using Manager.Core;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;
using Microsoft.Web.WebView2.Core;

namespace ShabbatManager.Pages;

/// <summary>Signs the display in to the NYT: the NYT-S cookie from an embedded sign-in page, or pasted. Never shown.</summary>
public sealed partial class NytPage : Page
{
    private static readonly string WebFolder =
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "ShabbatDisplayManager", "WebView2");

    private bool webReady, sending;

    public NytPage()
    {
        InitializeComponent();
    }

    protected override void OnNavigatedTo(NavigationEventArgs e) => _ = Load();

    protected override void OnNavigatedFrom(NavigationEventArgs e) => CloseSignIn();

    private async Task Load()
    {
        Busy.IsActive = true;
        var r = await AppState.Call(c => c.GetHouseholdAsync());
        Busy.IsActive = false;
        Ui.Show(Message, r.Error);
        if (r.Value is { } h) ShowState(h.NytSignedIn);
    }

    private void ShowState(bool signedIn)
    {
        State.Text = signedIn ? "Signed in" : "Signed out";
        State.Foreground = signedIn ? Ui.Green : Ui.Dim;
        SignOutButton.IsEnabled = signedIn;
    }

    private async void SignIn_Click(object sender, RoutedEventArgs e)
    {
        Ui.Show(Message, null);
        try
        {
            if (!webReady)
            {
                Directory.CreateDirectory(WebFolder);
                var env = await CoreWebView2Environment.CreateWithOptionsAsync(null, WebFolder, new CoreWebView2EnvironmentOptions());
                await Web.EnsureCoreWebView2Async(env);
                Web.CoreWebView2.NavigationCompleted += async (_, _) => await LookForCookie();
                webReady = true;
            }
            Controls.Visibility = Visibility.Collapsed;
            SignInView.Visibility = Visibility.Visible;
            Web.CoreWebView2.Navigate("https://myaccount.nytimes.com/auth/login");
        }
        catch (Exception)   // no WebView2 runtime, or it failed to start
        {
            CloseSignIn();
            Ui.Show(Message, "The sign-in page couldn't open here. Use “Sign-in page not working?” below.");
        }
    }

    private async Task LookForCookie()
    {
        if (sending || SignInView.Visibility != Visibility.Visible) return;
        var cookies = await Web.CoreWebView2.CookieManager.GetCookiesAsync("https://www.nytimes.com");
        var nyts = cookies.FirstOrDefault(c => c.Name == "NYT-S" && c.Value.Length > 0);
        if (nyts is null) return;
        sending = true;
        await Send(nyts.Value);
        sending = false;
    }

    private async Task<bool> Send(string cookie)
    {
        Busy.IsActive = true;
        var r = await AppState.Call(c => c.SetNytCookieAsync(cookie));
        Busy.IsActive = false;
        if (!r.Ok)
        {
            Ui.Show(Message, r.Error);
            return false;
        }
        CloseSignIn();
        // the display has it now; don't keep a second copy in the app's browser
        if (webReady) Web.CoreWebView2.CookieManager.DeleteAllCookies();
        ShowState(r.Value);
        if (r.Value) Ui.Show(Message, null, Ui.Saved);
        else Ui.Show(Message, "The display server didn't keep the sign-in.");
        return r.Value;
    }

    private void CloseSignIn()
    {
        SignInView.Visibility = Visibility.Collapsed;
        Controls.Visibility = Visibility.Visible;
        if (webReady) Web.CoreWebView2.Navigate("about:blank");
    }

    private void CancelSignIn_Click(object sender, RoutedEventArgs e) => CloseSignIn();

    private async void SignOut_Click(object sender, RoutedEventArgs e)
    {
        Busy.IsActive = true;
        var r = await AppState.Call(c => c.SetNytCookieAsync(""));
        Busy.IsActive = false;
        if (!r.Ok)
        {
            Ui.Show(Message, r.Error);
            return;
        }
        if (webReady)
            Web.CoreWebView2.CookieManager.DeleteAllCookies();
        else
        {
            try
            {
                if (Directory.Exists(WebFolder)) Directory.Delete(WebFolder, true);
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException) { }
        }
        ShowState(r.Value);
        if (r.Value) Ui.Show(Message, "Signed out here, but the display still has the NYT sign-in from its settings.json.");
        else Ui.Show(Message, null, Ui.Saved);
    }

    private async void PasteSave_Click(object sender, RoutedEventArgs e)
    {
        if (ManageClient.CleanCookie(Paste.Password) is not { } cookie)
        {
            Ui.Show(Message, "Paste the NYT-S value first.");
            return;
        }
        if (await Send(cookie)) Paste.Password = "";
    }
}
