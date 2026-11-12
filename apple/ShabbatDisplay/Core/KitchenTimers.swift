import Foundation

struct KitchenTimer: Codable, Identifiable, Equatable {
    var id = UUID()
    var label: String
    var ends: Date
    var ringing = false

    var name: String { label.isEmpty ? "Timer" : label.prefix(1).uppercased() + label.dropFirst() }
}

/// The countdown timers set by voice. Pure bookkeeping: the caller supplies the time and makes the noise.
struct KitchenTimers: Equatable {
    /// A timer nobody stops goes quiet by itself.
    static let ringsFor: TimeInterval = 180

    private(set) var all: [KitchenTimer] = []

    init(_ timers: [KitchenTimer] = []) { all = timers }

    var ringing: [KitchenTimer] { all.filter(\.ringing) }

    mutating func add(seconds: Int, label: String, now: Date) {
        guard (1...86_400).contains(seconds) else { return }
        all.append(KitchenTimer(label: label.trimmingCharacters(in: .whitespaces), ends: now.addingTimeInterval(TimeInterval(seconds))))
        all.sort { $0.ends < $1.ends }
    }

    /// Stops the timers with this label ("all", or an empty label, stops every one).
    mutating func cancel(label: String) {
        let want = label.trimmingCharacters(in: .whitespaces).lowercased()
        if want.isEmpty || want == "all" {
            all.removeAll()
        } else if all.contains(where: { $0.label.lowercased() == want }) {
            all.removeAll { $0.label.lowercased() == want }
        } else {
            all.removeAll { $0.label.lowercased().contains(want) || (!$0.label.isEmpty && want.contains($0.label.lowercased())) }
        }
    }

    mutating func removeAll() { all.removeAll() }

    /// Stops whatever is ringing.
    mutating func silence() { all.removeAll(where: \.ringing) }

    /// Moves the clock on. Returns the timers that have just started to ring.
    mutating func advance(to now: Date) -> [KitchenTimer] {
        all.removeAll { $0.ringing && now.timeIntervalSince($0.ends) > Self.ringsFor }
        var started: [KitchenTimer] = []
        for index in all.indices where !all[index].ringing && all[index].ends <= now {
            all[index].ringing = true
            // One that ended long ago (the app was closed) is dropped, not rung late.
            if now.timeIntervalSince(all[index].ends) <= Self.ringsFor { started.append(all[index]) }
        }
        all.removeAll { $0.ringing && now.timeIntervalSince($0.ends) > Self.ringsFor }
        return started
    }

    /// What the assistant is told about the timers.
    func report(now: Date) -> [[String: Any]] {
        all.map { ["label": $0.label, "seconds_left": max(0, Int($0.ends.timeIntervalSince(now).rounded())), "ringing": $0.ringing] }
    }
}

func countdown(_ seconds: TimeInterval) -> String {
    let total = max(0, Int(seconds.rounded(.up)))
    let (h, m, s) = (total / 3600, total % 3600 / 60, total % 60)
    return h > 0 ? String(format: "%d:%02d:%02d", h, m, s) : String(format: "%d:%02d", m, s)
}
