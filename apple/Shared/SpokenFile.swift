import AVFoundation

/// Turns a sentence into a sound file a notification can play, so an announcement is heard
/// in words while the app is closed. iOS plays notification sounds of up to 30 seconds.
final class SpokenFile: NSObject, AVSpeechSynthesizerDelegate {
    static let prefix = "announcement-"

    private let synthesizer = AVSpeechSynthesizer()
    private let lock = NSLock()
    private var file: AVAudioFile?
    private var finished = false
    private var frames: AVAudioFramePosition = 0
    private var name = ""
    private var done: ((String?) -> Void)?

    /// Writes `text` as speech into the shared sounds folder and hands back the file's name,
    /// or nil when it couldn't be made. `done` is called once, on any thread.
    func make(_ text: String, done: @escaping (String?) -> Void) {
        guard let folder = SharedStore.soundsFolder else { return done(nil) }
        Self.clean(folder)
        name = Self.prefix + UUID().uuidString + ".caf"
        self.done = done
        synthesizer.delegate = self
        let url = folder.appendingPathComponent(name)
        let utterance = AVSpeechUtterance(string: text)
        utterance.voice = AVSpeechSynthesisVoice(identifier: SharedStore.voice) ?? AVSpeechSynthesisVoice(language: "en-US")
        synthesizer.write(utterance) { [self] buffer in
            guard let pcm = buffer as? AVAudioPCMBuffer else { return }
            // An empty buffer is the end of the speech (so is the delegate's didFinish, whichever comes first).
            if pcm.frameLength == 0 { return end(made: true) }
            lock.lock()
            defer { lock.unlock() }
            guard !finished else { return }
            do {
                if file == nil {
                    file = try AVAudioFile(forWriting: url, settings: Self.settings(pcm.format),
                                           commonFormat: pcm.format.commonFormat, interleaved: pcm.format.isInterleaved)
                }
                try file?.write(from: pcm)
                #if DEBUG
                if frames == 0 { print("PUSH speech arriving: \(pcm.format)") }
                #endif
                frames += AVAudioFramePosition(pcm.frameLength)
            } catch {
                #if DEBUG
                print("PUSH speech file: \(error)")
                #endif
                lock.unlock()
                end(made: false)
                lock.lock()
            }
        }
    }

    func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) { end(made: true) }
    func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didCancel utterance: AVSpeechUtterance) { end(made: false) }

    /// Closes the file and reports, once.
    private func end(made: Bool) {
        lock.lock()
        guard !finished else { return lock.unlock() }
        finished = true
        file = nil
        let done = self.done, result = made && frames > 0 ? name : nil
        self.done = nil
        lock.unlock()
        done?(result)
    }

    /// Gives up (the extension's time ran out).
    func cancel() {
        end(made: false)
        synthesizer.stopSpeaking(at: .immediate)
    }

    /// 16-bit linear PCM, one of the formats a notification sound may have.
    static func settings(_ format: AVAudioFormat) -> [String: Any] {
        [AVFormatIDKey: kAudioFormatLinearPCM, AVSampleRateKey: format.sampleRate,
         AVNumberOfChannelsKey: format.channelCount, AVLinearPCMBitDepthKey: 16,
         AVLinearPCMIsFloatKey: false, AVLinearPCMIsBigEndianKey: false]
    }

    /// Whether the display computer sent this as a critical alert, and how loud: `aps.sound` is then
    /// `{"critical": 1, "volume": 0.8}` instead of a name. Nil for an ordinary notification.
    static func criticalVolume(_ userInfo: [AnyHashable: Any]) -> Float? {
        guard let aps = userInfo["aps"] as? [String: Any], let sound = aps["sound"] as? [String: Any],
              (sound["critical"] as? NSNumber)?.intValue == 1 else { return nil }
        return min(1, max(0.1, (sound["volume"] as? NSNumber)?.floatValue ?? 1))
    }

    /// Removes announcement files older than ten minutes.
    static func clean(_ folder: URL, now: Date = Date()) {
        let files = (try? FileManager.default.contentsOfDirectory(at: folder, includingPropertiesForKeys: [.contentModificationDateKey])) ?? []
        for file in files where file.lastPathComponent.hasPrefix(prefix) {
            let made = (try? file.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
            if now.timeIntervalSince(made) > 600 { try? FileManager.default.removeItem(at: file) }
        }
    }
}
