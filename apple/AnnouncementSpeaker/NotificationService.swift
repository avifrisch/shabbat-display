import UserNotifications

/// Runs when an announcement arrives while the app is closed or behind another app: the
/// announcement is turned into speech and becomes the notification's own sound.
final class NotificationService: UNNotificationServiceExtension {
    private var deliver: ((UNNotificationContent) -> Void)?
    private var content: UNMutableNotificationContent?
    private let speech = SpokenFile()
    private let lock = NSLock()

    override func didReceive(_ request: UNNotificationRequest, withContentHandler contentHandler: @escaping (UNNotificationContent) -> Void) {
        deliver = contentHandler
        content = request.content.mutableCopy() as? UNMutableNotificationContent
        SharedStore.note("extension: a notification arrived")
        guard let content, let text = request.content.userInfo["announcement"] as? String, !text.isEmpty else {
            SharedStore.note("extension: no announcement text in it")
            return finish()
        }
        // The server sends nothing on Shabbat and Yom Tov. If one arrives anyway, it makes no sound.
        if HolySpans.state(marks: SharedStore.marks, now: Date()).isHoly {
            content.sound = nil
            SharedStore.note("extension: the calendar says Shabbat, so no sound")
            return finish()
        }
        speech.make(text) { [weak self] name in
            SharedStore.note("extension: speech file \(name ?? "not made"), sounds folder \(SharedStore.soundsFolder == nil ? "missing" : "there"), voice '\(SharedStore.voice)'")
            if let name { content.sound = UNNotificationSound(named: UNNotificationSoundName(name)) }
            self?.finish()
        }
    }

    /// Out of time: the notification goes out with the ordinary sound.
    override func serviceExtensionTimeWillExpire() {
        SharedStore.note("extension: ran out of time")
        speech.cancel()
        finish()
    }

    private func finish() {
        lock.lock()
        let deliver = self.deliver
        self.deliver = nil
        lock.unlock()
        if let deliver, let content { deliver(content) }
    }
}
