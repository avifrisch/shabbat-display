using Manager.Core;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace ShabbatManager;

/// <summary>Asks for the access code and keeps it only once the server accepts it.</summary>
public sealed partial class ConnectDialog : ContentDialog
{
    private readonly HttpClient http;
    private readonly Uri server;

    public ManageClient? Client { get; private set; }

    public ConnectDialog(HttpClient http, Uri server)
    {
        this.http = http;
        this.server = server;
        InitializeComponent();
    }

    private async void Connect_Click(ContentDialog sender, ContentDialogButtonClickEventArgs args)
    {
        var deferral = args.GetDeferral();
        try
        {
            var code = Code.Password.Trim();
            if (code.Length == 0)
            {
                Show("Type the access code first.");
                args.Cancel = true;
                return;
            }
            IsPrimaryButtonEnabled = false;
            var client = new ManageClient(http, server, code);
            var r = await client.GetStatusAsync();
            IsPrimaryButtonEnabled = true;
            if (!r.Ok)
            {
                Show(r.Error!);
                args.Cancel = true;
                return;
            }
            try
            {
                CredentialStore.Write(code);
            }
            catch (InvalidOperationException e)
            {
                Show(e.Message);
                args.Cancel = true;
                return;
            }
            Client = client;
        }
        finally
        {
            deferral.Complete();
        }
    }

    private void Show(string text)
    {
        Error.Text = text;
        Error.Visibility = Visibility.Visible;
    }
}
