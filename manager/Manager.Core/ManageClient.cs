using System.Net;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Json.Serialization;

namespace Manager.Core;

/// <summary>The display server's management API. Every call answers a Result; nothing throws.</summary>
public class ManageClient(HttpClient http, Uri baseUri, string key)
{
    public const string NotAnswering = "The display server isn't answering. Is DESKTOP-H72VKDJ on?";
    public const string Refused = "The access code was refused. Enter it again.";
    public const string NeedsUpdate = "The display server needs updating to work with this app.";

    public static readonly JsonSerializerOptions Json = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        PropertyNameCaseInsensitive = true,
        Converters = { new LenientInt() },
    };

    /// <summary>Reads 10.0 (how Python writes a float setting) as 10.</summary>
    private sealed class LenientInt : JsonConverter<int>
    {
        public override int Read(ref Utf8JsonReader reader, Type typeToConvert, JsonSerializerOptions options)
        {
            if (reader.TokenType != JsonTokenType.Number) throw new JsonException("expected a number");
            return reader.TryGetInt32(out var i) ? i : (int)Math.Round(reader.GetDouble());
        }

        public override void Write(Utf8JsonWriter writer, int value, JsonSerializerOptions options) => writer.WriteNumberValue(value);
    }

    public Uri BaseUri => baseUri;

    public Task<Result<StatusResponse>> GetStatusAsync() => Send<StatusResponse>(HttpMethod.Get, "status");
    public Task<Result<Household>> GetHouseholdAsync() => Send<Household>(HttpMethod.Get, "household");

    public async Task<Result<List<string>>> GetLogAsync(int lines) =>
        Pick(await Send<JsonObject>(HttpMethod.Get, $"log?lines={lines}"), j => j["lines"].Deserialize<List<string>>(Json) ?? []);

    public async Task<Result<List<Team>>> SearchTeamsAsync(string league, string q) =>
        Pick(await Send<JsonObject>(HttpMethod.Get, $"teams?league={Uri.EscapeDataString(league)}&q={Uri.EscapeDataString(q)}"),
             j => j["teams"].Deserialize<List<Team>>(Json) ?? []);

    public async Task<Result<List<Stock>>> SearchStocksAsync(string q) =>
        Pick(await Send<JsonObject>(HttpMethod.Get, $"stocks?q={Uri.EscapeDataString(q)}"), j => j["stocks"].Deserialize<List<Stock>>(Json) ?? []);

    public Task<Result<bool>> SaveSportsAsync(Dictionary<string, League> sports) => Save("sports", sports);
    public Task<Result<bool>> SaveBusinessAsync(Business business) => Save("business", business);
    public Task<Result<bool>> SaveRotationAsync(string? screen, List<RotationItem>? rotation) => Save("rotation", new { screen, rotation });
    public Task<Result<bool>> SaveScreenAsync(string name, string mode, SaverOptions saver) => Save("screen", new { name, mode, saver });
    public Task<Result<bool>> RestartAsync() => Save("restart", new { });

    /// <summary>"" signs out. The answer is whether the server now has a cookie.</summary>
    public async Task<Result<bool>> SetNytCookieAsync(string cookie) =>
        Pick(await Send<JsonObject>(HttpMethod.Post, "nyt", new { cookie }), j => j["nyt_signed_in"]?.GetValue<bool>() ?? false);

    public Task<Result<ShulUpdate>> UpdateShulAsync() => Send<ShulUpdate>(HttpMethod.Post, "shul-update", new { });

    /// <summary>Whether /health answers, for after a restart.</summary>
    public async Task<bool> HealthAsync()
    {
        try
        {
            using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(2));
            using var r = await http.GetAsync(new Uri(baseUri, "health"), cts.Token);
            return r.IsSuccessStatusCode;
        }
        catch (Exception e) when (e is HttpRequestException or TaskCanceledException)
        {
            return false;
        }
    }

    /// <summary>The NYT-S value from what was pasted: "NYT-S=abc;" or "abc". Null when nothing is left.</summary>
    public static string? CleanCookie(string pasted)
    {
        var v = (pasted ?? "").Trim().TrimEnd(';').Trim();
        if (v.StartsWith("NYT-S=", StringComparison.OrdinalIgnoreCase))
            v = v["NYT-S=".Length..].Trim();
        return v.Length == 0 ? null : v;
    }

    private async Task<Result<bool>> Save(string name, object body)
    {
        var r = await Send<JsonObject>(HttpMethod.Post, name, body);
        return r.Ok ? new(true, null) : new(false, r.Error);
    }

    private static Result<T> Pick<T>(Result<JsonObject> r, Func<JsonObject, T> f) =>
        r.Ok ? new(f(r.Value!), null) : new(default, r.Error);

    private async Task<Result<T>> Send<T>(HttpMethod method, string path, object? body = null)
    {
        using var req = new HttpRequestMessage(method, new Uri(baseUri, "api/manage/" + path));
        req.Headers.Add("X-Manage-Key", key);
        // a string, not JsonContent: the server reads exactly Content-Length bytes, and a streamed body has none
        if (body is not null)
            req.Content = new StringContent(JsonSerializer.Serialize(body, body.GetType(), Json), Encoding.UTF8, "application/json");
        try
        {
            using var resp = await http.SendAsync(req);
            var text = await resp.Content.ReadAsStringAsync();
            if (resp.IsSuccessStatusCode)
                return new(JsonSerializer.Deserialize<T>(text, Json), null);
            return new(default, ErrorFor(resp.StatusCode, text));
        }
        catch (Exception e) when (e is HttpRequestException or TaskCanceledException)
        {
            return new(default, NotAnswering);
        }
        catch (Exception e) when (e is JsonException or InvalidOperationException or NotSupportedException or FormatException)
        {
            return new(default, NeedsUpdate);
        }
    }

    private static string ErrorFor(HttpStatusCode code, string text)
    {
        if (code == HttpStatusCode.Unauthorized) return Refused;
        if (code == HttpStatusCode.NotFound) return NeedsUpdate;
        try
        {
            if (JsonNode.Parse(text)?["error"]?.GetValue<string>() is { Length: > 0 } e) return e;
        }
        catch (Exception ex) when (ex is JsonException or InvalidOperationException) { }
        return $"The server answered {(int)code}.";
    }
}
