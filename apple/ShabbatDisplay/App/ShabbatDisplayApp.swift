import SwiftUI
import UserNotifications

@main
struct ShabbatDisplayApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    @State private var model: AppModel
    @State private var voice: VoiceController
    @Environment(\.scenePhase) private var phase

    init() {
        let model = AppModel()
        _model = State(initialValue: model)
        _voice = State(initialValue: VoiceController(model: model))
    }

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(model)
                .environment(voice)
                .preferredColorScheme(.dark)
                .statusBarHidden()
                .persistentSystemOverlays(.hidden)
                .onChange(of: phase, initial: true) { _, phase in
                    // The screen stays on for as long as the display is in front.
                    UIApplication.shared.isIdleTimerDisabled = phase == .active && model.showsDisplay
                    if phase == .active { model.start() } else if phase == .background { model.stop() }
                    voice.setActive(phase == .active)
                }
                .onReceive(NotificationCenter.default.publisher(for: .pushTokenChanged)) { _ in
                    Task { await model.sendPushToken() }
                }
                .task { await typedRequest() }
        }
    }

    /// For trying the assistant without a microphone: launch with `-say "set a timer for ten minutes"`.
    private func typedRequest() async {
        #if DEBUG
        if let text = UserDefaults.standard.string(forKey: "speakfile"), !text.isEmpty {
            // Tries the closed-app path without Apple's push service: the sentence becomes a sound
            // file and a notification plays it in five seconds (put the app in the background).
            print("PUSH trial: \(text) in voice '\(SharedStore.voice)', folder \(SharedStore.soundsFolder?.path ?? "none")")
            let speech = SpokenFile()
            speech.make(text) { name in
                _ = speech
                print("PUSH spoken file: \(name ?? "not made")")
                guard let name else { return }
                let content = UNMutableNotificationContent()
                content.title = "Announcement"
                content.body = text
                content.sound = UNNotificationSound(named: UNNotificationSoundName(name))
                let request = UNNotificationRequest(identifier: UUID().uuidString, content: content,
                                                    trigger: UNTimeIntervalNotificationTrigger(timeInterval: 5, repeats: false))
                UNUserNotificationCenter.current().add(request)
            }
        }
        guard let request = UserDefaults.standard.string(forKey: "say"), !request.isEmpty else { return }
        try? await Task.sleep(for: .seconds(3))
        await voice.ask(request)
        #endif
    }
}
