import Foundation
import UIKit
import Observation

@MainActor
@Observable
final class AppModel {
    enum Link: Equatable { case unknown, up, down }

    private let settings = Settings()

    private(set) var server: ServerAddress?
    private(set) var screen: String
    private(set) var link: Link = .unknown
    private(set) var marks: [HolyMark]
    /// Whether the display page is on screen (loaded and not failed).
    var pageLoaded = false
    /// Raised to make the web view load the page again.
    private(set) var reloadToken = 0
    var showingSettings = false
    /// Whether this device shows the display, or only receives announcements (a phone).
    private(set) var showsDisplay: Bool
    /// Where announcements as notifications stand on this device.
    private(set) var push: Push.State = .unknown

    private var watcher: Task<Void, Never>?

    init() {
        server = settings.server
        screen = settings.screen
        marks = settings.marks
        showsDisplay = settings.displayOn ?? (UIDevice.current.userInterfaceIdiom == .pad)
        SharedStore.marks = settings.marks
        showingSettings = settings.server == nil
    }

    var holy: HolyState { HolySpans.state(marks: marks, now: Date()) }

    var pageURL: URL? { server?.page(screen: screen) }

    func save(server: ServerAddress, screen: String, showsDisplay: Bool) {
        settings.displayOn = showsDisplay
        self.showsDisplay = showsDisplay
        settings.server = server
        settings.screen = screen
        self.server = server
        self.screen = settings.screen
        link = .unknown
        pageLoaded = false
        reloadToken += 1
        start()
    }

    func reload() {
        pageLoaded = false
        reloadToken += 1
    }

    /// Checks the server every 20 seconds and the calendar every 15 minutes.
    func start() {
        watcher?.cancel()
        guard let server else { return }
        let screen = screen
        SharedStore.voice = SpokenVoice.chosen(settings.voiceID)?.identifier ?? ""
        Task { await self.registerForAnnouncements() }
        watcher = Task { [weak self] in
            var tick = 0
            while !Task.isCancelled {
                let up = await Self.answers(server.health)
                guard let self, !Task.isCancelled else { return }
                self.link = up ? .up : .down
                if up && !self.pageLoaded { self.reloadToken += 1 }
                if up && tick % 45 == 0, let marks = await Self.fetchMarks(server.state(screen: screen)) {
                    self.marks = marks
                    self.settings.marks = marks
                    SharedStore.marks = marks
                }
                if up || tick % 45 != 0 { tick += 1 }
                try? await Task.sleep(for: .seconds(20))
            }
        }
    }

    /// Asks for notifications and gives the display computer this device's address for them.
    func registerForAnnouncements() async {
        guard server != nil else { return }
        guard await Push.ask() else {
            push = .refused
            return
        }
        await sendPushToken()
    }

    /// Gives the display computer this device's address for announcements, without asking iOS again.
    func sendPushToken() async {
        guard let server, push != .refused else { return }
        push = await Push.register(server, screen: screen)
    }

    func stop() {
        watcher?.cancel()
        watcher = nil
    }

    static func answers(_ url: URL) async -> Bool {
        var request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 5)
        request.httpMethod = "GET"
        guard let (_, response) = try? await URLSession.shared.data(for: request) else { return false }
        return (response as? HTTPURLResponse)?.statusCode == 200
    }

    private static func fetchMarks(_ url: URL) async -> [HolyMark]? {
        let request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 15)
        guard let (data, response) = try? await URLSession.shared.data(for: request),
              (response as? HTTPURLResponse)?.statusCode == 200,
              let marks = HolySpans.marks(fromState: data), !marks.isEmpty else { return nil }
        return marks
    }
}
