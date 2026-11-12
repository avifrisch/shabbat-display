import SwiftUI

@main
struct ShabbatDisplayApp: App {
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
                    UIApplication.shared.isIdleTimerDisabled = phase == .active
                    if phase == .active { model.start() } else if phase == .background { model.stop() }
                    voice.setActive(phase == .active)
                }
                .task { await typedRequest() }
        }
    }

    /// For trying the assistant without a microphone: launch with `-say "set a timer for ten minutes"`.
    private func typedRequest() async {
        #if DEBUG
        guard let request = UserDefaults.standard.string(forKey: "say"), !request.isEmpty else { return }
        try? await Task.sleep(for: .seconds(3))
        await voice.ask(request)
        #endif
    }
}
