import Foundation

struct Reminder: Codable, Identifiable, Equatable {
    enum Repeat: String, Codable { case none, daily, weekdays }

    var id = UUID()
    var text: String
    var when: Date
    var again: Repeat = .none
}

/// Reminders and alarms for a time of day. Pure bookkeeping, like `KitchenTimers`.
struct Reminders: Equatable {
    private(set) var all: [Reminder] = []

    init(_ reminders: [Reminder] = []) { all = reminders.sorted { $0.when < $1.when } }

    /// "2026-11-12T16:00" in the iPad's own time zone.
    static func date(from text: String, calendar: Calendar = .current) -> Date? {
        let format = DateFormatter()
        format.locale = Locale(identifier: "en_US_POSIX")
        format.calendar = calendar
        format.timeZone = calendar.timeZone
        format.dateFormat = "yyyy-MM-dd'T'HH:mm"
        return format.date(from: String(text.prefix(16)))
    }

    static func text(from date: Date, calendar: Calendar = .current) -> String {
        let format = DateFormatter()
        format.locale = Locale(identifier: "en_US_POSIX")
        format.calendar = calendar
        format.timeZone = calendar.timeZone
        format.dateFormat = "yyyy-MM-dd'T'HH:mm"
        return format.string(from: date)
    }

    mutating func add(text: String, when: Date, again: Reminder.Repeat) {
        let trimmed = text.trimmingCharacters(in: .whitespaces)
        guard !trimmed.isEmpty, all.count < 30 else { return }
        all.append(Reminder(text: trimmed, when: when, again: again))
        all.sort { $0.when < $1.when }
    }

    /// Cancels the reminders whose text matches ("all" cancels every one).
    mutating func cancel(text: String) {
        let want = text.trimmingCharacters(in: .whitespaces).lowercased()
        if want.isEmpty || want == "all" {
            all.removeAll()
        } else {
            all.removeAll { $0.text.lowercased().contains(want) || want.contains($0.text.lowercased()) }
        }
    }

    mutating func removeAll() { all.removeAll() }

    /// Moves the clock on. Returns the reminders to say now. One that came due more than ten
    /// minutes ago (the app was closed, or it was Shabbat) is not said. Repeating ones move to
    /// their next time; `weekdays` never lands on a Saturday.
    mutating func advance(to now: Date, calendar: Calendar = .current) -> [Reminder] {
        var due: [Reminder] = []
        var kept: [Reminder] = []
        for var reminder in all {
            guard reminder.when <= now else { kept.append(reminder); continue }
            if now.timeIntervalSince(reminder.when) <= 600 { due.append(reminder) }
            guard reminder.again != .none else { continue }
            repeat {
                reminder.when = calendar.date(byAdding: .day, value: 1, to: reminder.when) ?? reminder.when.addingTimeInterval(86_400)
            } while reminder.when <= now || (reminder.again == .weekdays && calendar.component(.weekday, from: reminder.when) == 7)
            kept.append(reminder)
        }
        all = kept.sorted { $0.when < $1.when }
        return due
    }

    /// What the assistant is told.
    func report(calendar: Calendar = .current) -> [[String: Any]] {
        all.map { ["text": $0.text, "when": Self.text(from: $0.when, calendar: calendar), "repeat": $0.again.rawValue] }
    }
}
