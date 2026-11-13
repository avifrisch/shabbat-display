import UIKit
import UserNotifications

/// Announcements as notifications, so they reach this device while the app is closed.
enum Push {
    enum State: Equatable {
        case unknown
        /// Notifications are switched off for the app in the device's Settings.
        case refused
        /// Waiting for Apple's address for this device, or for the display computer.
        case waiting
        /// The display computer has this device, but has no push key yet.
        case serverNotSetUp
        case ready
    }

    static var token: String {
        get { UserDefaults.standard.string(forKey: "pushToken") ?? "" }
        set { UserDefaults.standard.set(newValue, forKey: "pushToken") }
    }

    static var environment: String {
        #if DEBUG
        "development"
        #else
        "production"
        #endif
    }

    /// Asks to show notifications (the first time, iOS asks the person) and for Apple's address.
    @MainActor
    static func ask() async -> Bool {
        let allowed = (try? await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound])) ?? false
        if allowed { UIApplication.shared.registerForRemoteNotifications() }
        return allowed
    }

    static func body(token: String, screen: String, environment: String) -> Data {
        (try? JSONSerialization.data(withJSONObject: ["token": token, "screen": screen, "env": environment])) ?? Data()
    }

    /// The server's answer to a registration: nil when it wasn't taken.
    static func parse(_ data: Data) -> State? {
        guard let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any], root["ok"] as? Bool == true else { return nil }
        return root["set_up"] as? Bool == true ? .ready : .serverNotSetUp
    }

    /// Tells the display computer where to send this device's announcements.
    static func register(_ server: ServerAddress, screen: String) async -> State {
        let token = token
        guard !token.isEmpty else { return .waiting }
        var request = URLRequest(url: server.base.appendingPathComponent("api/push-register"), timeoutInterval: 8)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = body(token: token, screen: screen, environment: environment)
        guard let (data, _) = try? await URLSession.shared.data(for: request) else { return .waiting }
        return parse(data) ?? .waiting
    }
}

final class AppDelegate: NSObject, UIApplicationDelegate, UNUserNotificationCenterDelegate {
    func application(_ application: UIApplication,
                     didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
        UNUserNotificationCenter.current().delegate = self
        return true
    }

    func application(_ application: UIApplication, didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data) {
        // iOS reports the address after every request for it. Only a new one is news: telling the
        // display computer each time would ask again, and go round without end.
        let token = deviceToken.map { String(format: "%02x", $0) }.joined()
        guard token != Push.token else { return }
        Push.token = token
        NotificationCenter.default.post(name: .pushTokenChanged, object: nil)
    }

    func application(_ application: UIApplication, didFailToRegisterForRemoteNotificationsWithError error: Error) {
        #if DEBUG
        print("PUSH no address from Apple: \(error.localizedDescription)")
        #endif
    }

    /// With the app in front: a device that is listening already says announcements itself
    /// (it asks the display computer every few seconds), so the notification stays quiet there.
    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification) async -> UNNotificationPresentationOptions {
        // (A notification the app made itself, the DEBUG `-speakfile` trial, always sounds.)
        let pushed = notification.request.trigger is UNPushNotificationTrigger
        return pushed && Settings().voiceOn ? [] : [.banner, .list, .sound]
    }
}

extension Notification.Name {
    static let pushTokenChanged = Notification.Name("pushTokenChanged")
}
