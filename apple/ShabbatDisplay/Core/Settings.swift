import Foundation

/// What the iPad remembers between launches.
struct Settings {
    private let store: UserDefaults

    init(store: UserDefaults = .standard) { self.store = store }

    var server: ServerAddress? {
        get { store.string(forKey: "server").flatMap(ServerAddress.init) }
        nonmutating set { store.set(newValue?.display, forKey: "server") }
    }

    var screen: String {
        get {
            let name = store.string(forKey: "screen") ?? ""
            return validScreenName(name) ? name : "iPad"
        }
        nonmutating set { store.set(newValue, forKey: "screen") }
    }

    /// Whether this device shows the display itself. Nil = never chosen (an iPad shows it; a
    /// phone only receives announcements).
    var displayOn: Bool? {
        get { store.object(forKey: "displayOn") as? Bool }
        nonmutating set { store.set(newValue, forKey: "displayOn") }
    }

    /// Listening is off until someone turns it on in the settings.
    var voiceOn: Bool {
        get { store.bool(forKey: "voiceOn") }
        nonmutating set { store.set(newValue, forKey: "voiceOn") }
    }

    var wakePhrase: String {
        get {
            let phrase = store.string(forKey: "wakePhrase") ?? ""
            return WakePhrase(phrase) == nil ? WakePhrase.standard : phrase
        }
        nonmutating set { store.set(newValue, forKey: "wakePhrase") }
    }

    var reminders: [Reminder] {
        get {
            guard let data = store.data(forKey: "reminders") else { return [] }
            return (try? JSONDecoder().decode([Reminder].self, from: data)) ?? []
        }
        nonmutating set { store.set(try? JSONEncoder().encode(newValue), forKey: "reminders") }
    }

    /// Apple Home control, off until someone turns it on.
    var homeOn: Bool {
        get { store.bool(forKey: "homeOn") }
        nonmutating set { store.set(newValue, forKey: "homeOn") }
    }

    /// The voice answers are spoken in; empty = the best one installed.
    var voiceID: String {
        get { store.string(forKey: "voiceID") ?? "" }
        nonmutating set { store.set(newValue, forKey: "voiceID") }
    }

    /// Running timers, so one set before the app restarts still rings.
    var timers: [KitchenTimer] {
        get {
            guard let data = store.data(forKey: "timers") else { return [] }
            return (try? JSONDecoder().decode([KitchenTimer].self, from: data)) ?? []
        }
        nonmutating set { store.set(try? JSONEncoder().encode(newValue), forKey: "timers") }
    }

    /// The last calendar the server gave, so the Shabbat rule holds while the server is down.
    var marks: [HolyMark] {
        get {
            guard let data = store.data(forKey: "holyMarks") else { return [] }
            return (try? JSONDecoder().decode([HolyMark].self, from: data)) ?? []
        }
        nonmutating set { store.set(try? JSONEncoder().encode(newValue), forKey: "holyMarks") }
    }
}
