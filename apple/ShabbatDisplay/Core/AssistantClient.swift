import Foundation

/// What the display server answered to a spoken request.
struct AssistantReply: Equatable {
    enum Action: Equatable {
        case setTimer(seconds: Int, label: String)
        case cancelTimer(label: String)
        case playMusic(query: String, kind: String)
        case musicControl(String)
        /// Put a code on the display for a phone: a full link, or a page on the display server.
        case showCode(title: String, url: String?, path: String?)
        case homeSet(device: String, room: String, action: String, value: Int?)
        case homeScene(String)
        case setReminder(when: String, text: String, again: String)
        case cancelReminder(String)
        case playRadio(String)
    }

    var say = ""
    var actions: [Action] = []
    /// The server's reason when it didn't answer the request ("holy", "budget_month", "not_set_up", …).
    var error: String?

    /// Reads the server's JSON. Anything it doesn't recognise is left out.
    static func parse(_ data: Data) -> AssistantReply? {
        guard let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
        var reply = AssistantReply()
        reply.say = (root["say"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        reply.error = root["ok"] as? Bool == true ? nil : (root["error"] as? String ?? "unknown")
        for item in root["actions"] as? [[String: Any]] ?? [] {
            let label = item["label"] as? String ?? ""
            switch item["type"] as? String {
            case "set_timer":
                if let seconds = item["seconds"] as? Int, (1...86_400).contains(seconds) {
                    reply.actions.append(.setTimer(seconds: seconds, label: label))
                }
            case "cancel_timer":
                reply.actions.append(.cancelTimer(label: label))
            case "play_music":
                if let query = item["query"] as? String, !query.isEmpty {
                    reply.actions.append(.playMusic(query: query, kind: item["kind"] as? String ?? "any"))
                }
            case "music_control":
                if let command = item["command"] as? String, ["pause", "resume", "next", "previous", "stop"].contains(command) {
                    reply.actions.append(.musicControl(command))
                }
            case "home_set":
                if let device = item["device"] as? String, !device.isEmpty, let what = item["action"] as? String,
                   ["on", "off", "brightness", "temperature", "position", "lock", "close"].contains(what) {
                    reply.actions.append(.homeSet(device: device, room: item["room"] as? String ?? "", action: what, value: item["value"] as? Int))
                }
            case "home_scene":
                if let name = item["name"] as? String, !name.isEmpty { reply.actions.append(.homeScene(name)) }
            case "set_reminder":
                if let when = item["when"] as? String, let text = item["text"] as? String, !text.isEmpty {
                    reply.actions.append(.setReminder(when: when, text: text, again: item["repeat"] as? String ?? "none"))
                }
            case "cancel_reminder":
                reply.actions.append(.cancelReminder(item["text"] as? String ?? "all"))
            case "play_radio":
                if let station = item["station"] as? String, !station.isEmpty { reply.actions.append(.playRadio(station)) }
            case "show_code":
                let url = (item["url"] as? String).flatMap { $0.hasPrefix("https://") ? $0 : nil }
                let path = (item["path"] as? String).flatMap { $0.hasPrefix("/") && !$0.hasPrefix("//") ? $0 : nil }
                if url != nil || path != nil {
                    reply.actions.append(.showCode(title: item["title"] as? String ?? "", url: url, path: path))
                }
            default:
                break
            }
        }
        return reply
    }
}

enum AssistantClient {
    struct Exchange { let q: String; let a: String }

    static func body(text: String, timers: [[String: Any]], history: [Exchange], music: [String: Any] = [:],
                     home: [String: Any]? = nil, reminders: [[String: Any]] = [], screen: String = "", device: String = "") -> Data {
        var json: [String: Any] = ["text": text, "timers": timers, "music": music, "reminders": reminders, "screen": screen, "device": device,
                                   "history": history.map { ["q": $0.q, "a": $0.a] }]
        if let home { json["home"] = home }
        return (try? JSONSerialization.data(withJSONObject: json)) ?? Data()
    }

    /// Nil when the display computer didn't answer at all.
    static func ask(_ server: ServerAddress, text: String, timers: [[String: Any]], history: [Exchange],
                    music: [String: Any] = [:], home: [String: Any]? = nil, reminders: [[String: Any]] = [],
                    screen: String = "", device: String = "") async -> AssistantReply? {
        var request = URLRequest(url: server.base.appendingPathComponent("api/assistant"), timeoutInterval: 45)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = body(text: text, timers: timers, history: history, music: music, home: home, reminders: reminders, screen: screen, device: device)
        guard let (data, _) = try? await URLSession.shared.data(for: request) else { return nil }
        return AssistantReply.parse(data)
    }
}

/// Announcements for every display ("tell everyone dinner is ready").
enum AnnouncementFeed {
    struct Batch: Equatable {
        var last = 0
        var texts: [String] = []
    }

    /// The announcements in the server's answer that didn't come from this screen.
    static func parse(_ data: Data, mine: String) -> Batch? {
        guard let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any], let last = root["last"] as? Int else { return nil }
        let items = root["items"] as? [[String: Any]] ?? []
        return Batch(last: last, texts: items.compactMap { item in
            guard let text = item["text"] as? String, !text.isEmpty, item["from"] as? String != mine else { return nil }
            return text
        })
    }

    static func fetch(_ server: ServerAddress, since: Int, mine: String) async -> Batch? {
        var parts = URLComponents(url: server.base.appendingPathComponent("api/announcements"), resolvingAgainstBaseURL: false)!
        parts.queryItems = [URLQueryItem(name: "since", value: String(since))]
        var request = URLRequest(url: parts.url!, timeoutInterval: 5)
        request.cachePolicy = .reloadIgnoringLocalCacheData
        guard let (data, _) = try? await URLSession.shared.data(for: request) else { return nil }
        return parse(data, mine: mine)
    }
}
