import Foundation

/// What the display server answered to a spoken request.
struct AssistantReply: Equatable {
    enum Action: Equatable {
        case setTimer(seconds: Int, label: String)
        case cancelTimer(label: String)
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
            default:
                break
            }
        }
        return reply
    }
}

enum AssistantClient {
    struct Exchange { let q: String; let a: String }

    static func body(text: String, timers: [[String: Any]], history: [Exchange]) -> Data {
        let json: [String: Any] = ["text": text, "timers": timers, "history": history.map { ["q": $0.q, "a": $0.a] }]
        return (try? JSONSerialization.data(withJSONObject: json)) ?? Data()
    }

    /// Nil when the display computer didn't answer at all.
    static func ask(_ server: ServerAddress, text: String, timers: [[String: Any]], history: [Exchange]) async -> AssistantReply? {
        var request = URLRequest(url: server.base.appendingPathComponent("api/assistant"), timeoutInterval: 45)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = body(text: text, timers: timers, history: history)
        guard let (data, _) = try? await URLSession.shared.data(for: request) else { return nil }
        return AssistantReply.parse(data)
    }
}
