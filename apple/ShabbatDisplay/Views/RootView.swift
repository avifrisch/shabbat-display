import SwiftUI

struct RootView: View {
    @Environment(AppModel.self) private var model
    @Environment(VoiceController.self) private var voice
    @State private var link: URL?

    var body: some View {
        @Bindable var model = model
        ZStack(alignment: .topLeading) {
            Theme.background.ignoresSafeArea()
            if !model.showsDisplay {
                AnnouncementsOnlyView()
            } else if let url = model.pageURL {
                DisplayWebView(url: url, reloadToken: model.reloadToken,
                               loaded: { model.pageLoaded = $0 },
                               opened: { if !model.holy.isHoly { link = $0 } })
                    .ignoresSafeArea()
                    .opacity(model.pageLoaded ? 1 : 0)
                if !model.pageLoaded {
                    WaitingView(down: model.link == .down)
                }
            } else {
                WaitingView(down: false)
            }
            VoiceOverlay()
            // Hold the top-left corner for two seconds to open the settings. Off on Shabbat and Yom Tov.
            Color.clear
                .frame(width: 70, height: 70)
                .contentShape(Rectangle())
                .onLongPressGesture(minimumDuration: 2) {
                    if !model.holy.isHoly { model.showingSettings = true }
                }
        }
        .sheet(isPresented: $model.showingSettings) {
            SetupView().environment(model).environment(voice)
        }
        .fullScreenCover(item: $link) { url in
            LinkView(url: url) { link = nil }
        }
    }
}

extension URL: @retroactive Identifiable {
    public var id: String { absoluteString }
}

enum Theme {
    static let background = Color(red: 0x0D / 255, green: 0x17 / 255, blue: 0x26 / 255)
    static let text = Color(red: 0.93, green: 0.90, blue: 0.84)
    static let gold = Color(red: 0xE5 / 255, green: 0xBA / 255, blue: 0x5E / 255)
}

/// A phone, or a tablet that only receives announcements: nothing to watch, just where it stands.
struct AnnouncementsOnlyView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        VStack(spacing: 22) {
            Image(systemName: "megaphone.fill")
                .font(.system(size: 54))
                .foregroundStyle(Theme.gold)
            Text("Announcements")
                .font(.largeTitle.weight(.semibold))
                .foregroundStyle(Theme.text)
            Text(status)
                .font(.title3)
                .multilineTextAlignment(.center)
                .foregroundStyle(Theme.text.opacity(0.7))
            if !model.holy.isHoly {
                Button("Settings") { model.showingSettings = true }
                    .buttonStyle(.bordered)
                    .tint(Theme.gold)
            }
        }
        .padding(32)
        .frame(maxWidth: 520)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var status: String {
        switch model.push {
        case .ready: "Announcements from the kitchen display arrive on this device, even while this app is closed. You can close it."
        case .refused: "Notifications are off for Shabbat Display. Turn them on in Settings → Notifications → Shabbat Display."
        case .serverNotSetUp: "This device is ready. The display computer still needs its Apple push key."
        case .waiting, .unknown: model.server == nil ? "Enter the display computer's address in the settings." : "Setting up. This device has to be on the home Wi-Fi once."
        }
    }
}

/// A clock for while the display can't be shown, like the Windows screen saver's.
struct WaitingView: View {
    let down: Bool

    var body: some View {
        TimelineView(.periodic(from: .now, by: 1)) { context in
            VStack(spacing: 18) {
                Text(context.date, format: .dateTime.hour().minute())
                    .font(.system(size: 150, weight: .light, design: .rounded))
                    .monospacedDigit()
                    .foregroundStyle(Theme.text)
                Text(down ? "Display not reachable. Trying again every 20 seconds." : "Connecting to the display…")
                    .font(.title2)
                    .foregroundStyle(Theme.text.opacity(0.6))
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }
}
