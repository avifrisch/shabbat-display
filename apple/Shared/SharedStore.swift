import Foundation

/// What the app shares with its notification extension (the part that speaks an announcement
/// while the app is closed): the calendar's candle-lighting marks and the chosen voice.
enum SharedStore {
    static let group = "group.com.avifrischlaw.shabbatdisplay"

    private static var store: UserDefaults? { UserDefaults(suiteName: group) }

    static var marks: [HolyMark] {
        get {
            guard let data = store?.data(forKey: "holyMarks") else { return [] }
            return (try? JSONDecoder().decode([HolyMark].self, from: data)) ?? []
        }
        set { store?.set(try? JSONEncoder().encode(newValue), forKey: "holyMarks") }
    }

    /// The identifier of the voice announcements are spoken in; empty = the device's own.
    static var voice: String {
        get { store?.string(forKey: "voice") ?? "" }
        set { store?.set(newValue, forKey: "voice") }
    }

    /// Where a notification's sound file has to be for iOS to play it.
    static var soundsFolder: URL? {
        guard let base = FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: group) else { return nil }
        let folder = base.appendingPathComponent("Library/Sounds", isDirectory: true)
        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        return folder
    }
}
