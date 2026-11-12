import SwiftUI

/// What the voice side shows over the display: the timers, what was heard and the answer.
struct VoiceOverlay: View {
    @Environment(VoiceController.self) private var voice

    var body: some View {
        ZStack {
            VStack(alignment: .trailing, spacing: 10) {
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
