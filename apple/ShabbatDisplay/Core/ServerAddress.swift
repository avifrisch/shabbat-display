import Foundation

/// The display server's address as someone would type it: "192.168.4.109",
/// "desktop-h72vkdj:8765" or a full "http://…" URL.
struct ServerAddress: Equatable {
    static let defaultPort = 8765

    let base: URL

    init?(_ typed: String) {
        var text = typed.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return nil }
        if !text.contains("://") { text = "http://" + text }
        guard var parts = URLComponents(string: text),
              let scheme = parts.scheme?.lowercased(), scheme == "http" || scheme == "https",
              let host = parts.host, !host.isEmpty else { return nil }
        parts.scheme = scheme
        if parts.port == nil && scheme == "http" { parts.port = Self.defaultPort }
        parts.path = ""
        parts.query = nil
        parts.fragment = nil
        parts.user = nil
        parts.password = nil
        guard let url = parts.url else { return nil }
        base = url
    }

    /// What to show in the settings field.
    var display: String {
        let text = base.absoluteString
        return text.hasPrefix("http://") ? String(text.dropFirst("http://".count)) : text
    }

    var health: URL { base.appendingPathComponent("health") }

    /// The display page for this screen.
    func page(screen: String) -> URL {
        var parts = URLComponents(url: base, resolvingAgainstBaseURL: false)!
        parts.path = "/"
        parts.queryItems = [URLQueryItem(name: "screen", value: screen)]
        return parts.url!
    }

    /// The state, asked for without checking in (`preview=1`): the page itself checks in.
    func state(screen: String) -> URL {
        var parts = URLComponents(url: base, resolvingAgainstBaseURL: false)!
        parts.path = "/api/state"
        parts.queryItems = [URLQueryItem(name: "screen", value: screen),
                            URLQueryItem(name: "preview", value: "1")]
        return parts.url!
    }
}

/// The server's rule for a screen name (`valid_screen()`): letters, digits, space and `._'-`, up to 40.
func validScreenName(_ name: String) -> Bool {
    guard !name.isEmpty, name.count <= 40, name == name.trimmingCharacters(in: .whitespaces) else { return false }
    let extra = CharacterSet(charactersIn: " ._'-")
    return name.unicodeScalars.allSatisfy {
        ($0.isASCII && CharacterSet.alphanumerics.contains($0)) || extra.contains($0)
    }
}
