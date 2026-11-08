using Manager.Core;
using Microsoft.UI.Xaml;

namespace ShabbatManager;

/// <summary>The one connection to the display server, shared by every page.</summary>
public static class AppState
{
    public static readonly HttpClient Http = new() { Timeout = TimeSpan.FromSeconds(20) };

    public static ManageClient? Client { get; private set; }
    public static Uri? Server { get; private set; }
    public static XamlRoot? Root { get; set; }

    private static Task<bool>? asking;

    /// <summary>Finds the server and the access code, asking for it when there's none. Null, or why it couldn't connect.</summary>
    public static async Task<string?> ConnectAsync()
    {
        Server = await new ServerFinder(Http, ServerFinder.DefaultRememberFile).FindAsync();
        if (Server is null)
        {
            Client = null;
            return ManageClient.NotAnswering;
        }
        var key = CredentialStore.Read();
        if (key is not null)
        {
            Client = new ManageClient(Http, Server, key);
            return null;
        }
        return await AskForCodeAsync() ? null : "The access code is needed to manage the display.";
    }

    /// <summary>Opens the access-code dialog (only one at a time). True once a code works.</summary>
    public static Task<bool> AskForCodeAsync()
    {
        return asking ??= Ask();

        static async Task<bool> Ask()
        {
            try
            {
                if (Server is null || Root is null) return false;
                var d = new ConnectDialog(Http, Server) { XamlRoot = Root };
                await d.ShowAsync();
                if (d.Client is null) return false;
                Client = d.Client;
                return true;
            }
            finally
            {
                asking = null;
            }
        }
    }

    /// <summary>Runs one API call. A refused code asks for it again; a server that stopped answering is looked for again. Each retries once.</summary>
    public static async Task<Result<T>> Call<T>(Func<ManageClient, Task<Result<T>>> f)
    {
        if (Client is null)
        {
            var e = await ConnectAsync();
            if (e is not null) return new(default, e);
        }
        var r = await f(Client!);
        if (r.Error == ManageClient.Refused)
        {
            if (await AskForCodeAsync()) r = await f(Client!);
        }
        else if (r.Error == ManageClient.NotAnswering)
        {
            var old = Server;
            if (await ConnectAsync() is null && Server != old) r = await f(Client!);
        }
        return r;
    }
}
