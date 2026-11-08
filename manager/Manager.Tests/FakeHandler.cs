using System.Net;
using System.Text;

namespace Manager.Tests;

/// <summary>Answers every request with canned JSON and remembers the last one.</summary>
public class FakeHandler : HttpMessageHandler
{
    private readonly Func<HttpRequestMessage, HttpResponseMessage> answer;
    public HttpRequestMessage? Last { get; private set; }
    public string? LastBody { get; private set; }

    public FakeHandler(string body, int status = 200)
        : this(_ => new HttpResponseMessage((HttpStatusCode)status) { Content = new StringContent(body, Encoding.UTF8, "application/json") }) { }

    private FakeHandler(Func<HttpRequestMessage, HttpResponseMessage> answer) => this.answer = answer;

    /// <summary>Every request fails as if the server were off.</summary>
    public static FakeHandler Throws() => new(_ => throw new HttpRequestException("connection refused"));

    /// <summary>Status per host; 0 means the connection fails. Hosts not listed fail too.</summary>
    public static FakeHandler ByHost(Dictionary<string, int> hosts) => new(r =>
    {
        var code = hosts.TryGetValue(r.RequestUri!.Host.ToLowerInvariant(), out var c) ? c : 0;
        if (code == 0) throw new HttpRequestException("connection refused");
        return new HttpResponseMessage((HttpStatusCode)code) { Content = new StringContent("ok") };
    });

    protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct)
    {
        Last = request;
        LastBody = request.Content is null ? null : await request.Content.ReadAsStringAsync(ct);
        return answer(request);
    }
}
