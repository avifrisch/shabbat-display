import SwiftUI

/// What the voice side shows over the display: the timers, what was heard and the answer.
struct VoiceOverlay: View {
    @Environment(VoiceController.self) private var voice

    var body: some View {
        ZStack {
            VStack(alignment: .trailing, spacing: 10) {
                if let station = voice.radio.station {
                    MusicChip(title: station, playing: voice.radio.playing, live: true) { command in
                        voice.radio.control(command)
                    }
                }
                ForEach(voice.reminders.all.prefix(3)) { reminder in
                    HStack(spacing: 10) {
                        Image(systemName: "bell")
                        Text(reminder.text).lineLimit(1).frame(maxWidth: 260, alignment: .leading)
                        Text(reminder.when, format: Calendar.current.isDateInToday(reminder.when) ? .dateTime.hour().minute() : .dateTime.weekday().hour().minute())
                            .fontWeight(.semibold)
                    }
                    .font(.title3)
                    .foregroundStyle(Theme.text)
                    .padding(.horizontal, 20)
                    .padding(.vertical, 11)
                    .background(.ultraThinMaterial, in: Capsule())
                }
                if let title = voice.music.title {
                    MusicChip(title: title, playing: voice.music.playing) { command in
                        Task { await voice.music.control(command) }
                    }
                }
                ForEach(voice.timers.all) { timer in
                    TimerChip(timer: timer) {
                        if timer.ringing { voice.silence() } else { voice.cancel(timer) }
                    }
                }
            }
            .padding(22)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottomTrailing)

            if let words {
                HStack(spacing: 14) {
                    Image(systemName: icon)
                        .font(.title2)
                        .foregroundStyle(Theme.gold)
                        .symbolEffect(.pulse, isActive: pulsing)
                    Text(words)
                        .font(.title2)
                        .foregroundStyle(Theme.text)
                        .lineLimit(3)
                        .multilineTextAlignment(.leading)
                }
                .padding(.horizontal, 26)
                .padding(.vertical, 16)
                .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 22))
                .overlay(RoundedRectangle(cornerRadius: 22).stroke(Theme.gold.opacity(0.35)))
                .frame(maxWidth: 760)
                .padding(.bottom, 26)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottom)
                .transition(.opacity)
            }

            if let code = voice.code {
                Button(action: voice.dismissCode) {
                    VStack(spacing: 14) {
                        Text(code.title).font(.title.weight(.semibold))
                        Image(uiImage: code.image)
                            .interpolation(.none)
                            .resizable()
                            .frame(width: 300, height: 300)
                            .padding(14)
                            .background(.white, in: RoundedRectangle(cornerRadius: 14))
                        Text(code.hint)
                            .font(.title3)
                            .multilineTextAlignment(.center)
                            .frame(maxWidth: 380)
                        Text("Tap to close").font(.footnote).foregroundStyle(Theme.text.opacity(0.5))
                    }
                    .foregroundStyle(Theme.text)
                    .padding(30)
                    .background(Theme.background.opacity(0.96), in: RoundedRectangle(cornerRadius: 28))
                    .overlay(RoundedRectangle(cornerRadius: 28).stroke(Theme.gold.opacity(0.5)))
                }
                .buttonStyle(.plain)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .transition(.opacity)
            }

            if voice.stage == .waiting {
                // Small and steady: the microphone is on.
                Image(systemName: "mic.fill")
                    .font(.footnote)
                    .foregroundStyle(Theme.text.opacity(0.35))
                    .padding(10)
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottomLeading)
                    .allowsHitTesting(false)
            }
        }
        .animation(.easeInOut(duration: 0.2), value: voice.stage)
        .animation(.easeInOut(duration: 0.2), value: voice.timers)
        .animation(.easeInOut(duration: 0.2), value: voice.code)
        .animation(.easeInOut(duration: 0.2), value: voice.reminders)
        .animation(.easeInOut(duration: 0.2), value: voice.radio.station)
        .animation(.easeInOut(duration: 0.2), value: voice.music.title)
    }

    private var words: String? {
        switch voice.stage {
        case .off, .waiting: nil
        case .hearing(let heard): heard.isEmpty ? "Listening…" : heard
        case .asking(let request): request
        case .answering(let answer): answer
        }
    }

    private var icon: String {
        switch voice.stage {
        case .answering: "speaker.wave.2.fill"
        case .asking: "ellipsis"
        default: "mic.fill"
        }
    }

    private var pulsing: Bool {
        if case .answering = voice.stage { return false }
        return true
    }
}

private struct TimerChip: View {
    let timer: KitchenTimer
    let tapped: () -> Void

    var body: some View {
        TimelineView(.periodic(from: .now, by: 1)) { context in
            Button(action: tapped) {
                HStack(spacing: 12) {
                    Image(systemName: timer.ringing ? "bell.and.waves.left.and.right.fill" : "timer")
                    Text(timer.name)
                    Text(timer.ringing ? "Done · tap to stop" : countdown(timer.ends.timeIntervalSince(context.date)))
                        .monospacedDigit()
                        .fontWeight(.semibold)
                }
                .font(timer.ringing ? .title : .title3)
                .foregroundStyle(timer.ringing ? Theme.background : Theme.text)
                .padding(.horizontal, 20)
                .padding(.vertical, timer.ringing ? 16 : 11)
                .background(timer.ringing ? AnyShapeStyle(Theme.gold) : AnyShapeStyle(.ultraThinMaterial), in: Capsule())
            }
            .buttonStyle(.plain)
        }
    }
}

private struct MusicChip: View {
    let title: String
    let playing: Bool
    var live = false
    let control: (String) -> Void

    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: live ? "antenna.radiowaves.left.and.right" : "music.note").foregroundStyle(Theme.gold)
            Text(title).lineLimit(1).frame(maxWidth: 320, alignment: .leading).padding(.trailing, 6)
            button(playing ? "pause.fill" : "play.fill", playing ? "pause" : "resume", playing ? "Pause" : "Play")
            if !live { button("forward.fill", "next", "Next") }
            button("xmark", "stop", "Stop the music")
        }
        .font(.title3)
        .foregroundStyle(Theme.text)
        .padding(.leading, 20)
        .padding(.trailing, 8)
        .padding(.vertical, 5)
        .background(.ultraThinMaterial, in: Capsule())
    }

    private func button(_ icon: String, _ command: String, _ label: String) -> some View {
        Button { control(command) } label: {
            Image(systemName: icon).frame(width: 44, height: 44).contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
    }
}
