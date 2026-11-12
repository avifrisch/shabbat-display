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
        utterance.voice = AVSpeechSynthesisVoice(language: "en-US")
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
