import AVFoundation

/// The display's own voice and its two sounds.
final class Sounds: NSObject, AVSpeechSynthesizerDelegate {
    private let synthesizer = AVSpeechSynthesizer()
    private var finished: CheckedContinuation<Void, Never>?
    private lazy var chimePlayer = try? AVAudioPlayer(data: Self.tone(hertz: [880], seconds: 0.12, volume: 0.25))
    private lazy var alarmPlayer = try? AVAudioPlayer(data: Self.tone(hertz: [1046, 0, 1046, 0, 1046], seconds: 0.14, volume: 0.6))

    override init() {
        super.init()
        synthesizer.delegate = self
    }

    /// Says the sentence and returns when it has been said (or stopped).
    @MainActor
    func say(_ sentence: String) async {
        guard !sentence.isEmpty else { return }
        stopSpeaking()
        let utterance = AVSpeechUtterance(string: sentence)
        utterance.voice = SpokenVoice.chosen(Settings().voiceID)
        await withCheckedContinuation { done in
            finished = done
            synthesizer.speak(utterance)
        }
    }

    @MainActor
    func stopSpeaking() {
        if synthesizer.isSpeaking { synthesizer.stopSpeaking(at: .immediate) }
        finished?.resume()
        finished = nil
    }

    /// A short note: the wake phrase was heard.
    func chime() { play(chimePlayer) }

    /// Three beeps: a timer is ringing.
    func alarm() { play(alarmPlayer) }

    private func play(_ player: AVAudioPlayer?) {
        player?.currentTime = 0
        player?.play()
    }

    func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) { end() }
    func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didCancel utterance: AVSpeechUtterance) { end() }

    private func end() {
        DispatchQueue.main.async {
            self.finished?.resume()
            self.finished = nil
        }
    }

    /// A WAV file of sine notes played one after another (0 Hz is a rest), each with soft edges.
    static func tone(hertz: [Double], seconds: Double, volume: Double) -> Data {
        let rate = 44_100.0
        let perNote = Int(rate * seconds)
        var samples: [Int16] = []
        for note in hertz {
            for index in 0..<perNote {
                let edge = min(1, Double(min(index, perNote - index)) / (rate * 0.01))
                let value = note == 0 ? 0 : sin(2 * .pi * note * Double(index) / rate) * volume * edge
                samples.append(Int16(value * Double(Int16.max)))
            }
        }
        var data = Data()
        func put<T: FixedWidthInteger>(_ value: T) { withUnsafeBytes(of: value.littleEndian) { data.append(contentsOf: $0) } }
        let bytes = UInt32(samples.count * 2)
        data.append(contentsOf: Array("RIFF".utf8)); put(36 + bytes)
        data.append(contentsOf: Array("WAVEfmt ".utf8)); put(UInt32(16)); put(UInt16(1)); put(UInt16(1))
        put(UInt32(rate)); put(UInt32(rate * 2)); put(UInt16(2)); put(UInt16(16))
        data.append(contentsOf: Array("data".utf8)); put(bytes)
        samples.forEach(put)
        return data
    }
}

/// The voices the iPad can answer in. Apple's better ones ("Enhanced", "Premium") are free
/// downloads in the iPad's Settings; Siri's own voices aren't offered to apps.
enum SpokenVoice {
    struct Choice: Identifiable, Equatable {
        let id: String
        let name: String
        /// 0 standard, 1 enhanced, 2 premium.
        let rank: Int

        var label: String { name + (rank == 2 ? " (Premium)" : rank == 1 ? " (Enhanced)" : "") }
    }

    /// The English voices on this iPad, best first, without the novelty ones.
    static func choices(from voices: [AVSpeechSynthesisVoice] = AVSpeechSynthesisVoice.speechVoices()) -> [Choice] {
        voices
            .filter { $0.language.hasPrefix("en") && !$0.voiceTraits.contains(.isNoveltyVoice) && !$0.voiceTraits.contains(.isPersonalVoice) }
            .map { Choice(id: $0.identifier, name: $0.name + ($0.language == "en-US" ? "" : " · " + accent($0.language)), rank: rank($0.quality)) }
            .sorted { ($1.rank, $0.name) < ($0.rank, $1.name) }
    }

    /// The saved voice if it is still installed, else the best American English one.
    static func chosen(_ id: String) -> AVSpeechSynthesisVoice? {
        if !id.isEmpty, let saved = AVSpeechSynthesisVoice(identifier: id) { return saved }
        let american = AVSpeechSynthesisVoice.speechVoices()
            .filter { $0.language == "en-US" && !$0.voiceTraits.contains(.isNoveltyVoice) && !$0.voiceTraits.contains(.isPersonalVoice) }
            .max { rank($0.quality) < rank($1.quality) }
        return american ?? AVSpeechSynthesisVoice(language: "en-US")
    }

    static func rank(_ quality: AVSpeechSynthesisVoiceQuality) -> Int {
        switch quality {
        case .premium: 2
        case .enhanced: 1
        default: 0
        }
    }

    private static func accent(_ language: String) -> String {
        ["en-GB": "British", "en-AU": "Australian", "en-IE": "Irish", "en-ZA": "South African", "en-IN": "Indian"][language] ?? language
    }
}
