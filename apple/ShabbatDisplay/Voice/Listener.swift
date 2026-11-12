import AVFoundation
import Speech

/// The microphone and the speech recognizer.
///
/// The recognizer doesn't run all day. A cheap loudness check watches the microphone, and a
/// stretch of sound (with the 0.8 s before it) is handed to the recognizer until it goes quiet.
/// The caller decides what the words mean. While `muted`, nothing is heard at all.
final class Listener {
    enum Event {
        /// Words so far in the stretch being heard.
        case partial(String)
        /// A stretch has ended; these are its words.
        case heard(String)
        /// Listening couldn't start or has stopped by itself.
        case failed(String)
    }

    /// Called on the main queue.
    var onEvent: ((Event) -> Void)?

    private let queue = DispatchQueue(label: "com.avifrischlaw.shabbatdisplay.listener")
    private let engine = AVAudioEngine()
    private var recognizer: SFSpeechRecognizer?
    private var observers: [NSObjectProtocol] = []

    // Everything below is touched only on `queue`.
    private var running = false
    private var muted = false
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private var taskNumber = 0
    private var taskStarted = Date.distantPast
    private var lastWords = ""
    private var recent: [AVAudioPCMBuffer] = []
    private var recentSeconds = 0.0
    private var floor: Float = 0.004
    private var loudRun = 0
    private var lastLoud = Date.distantPast
    private var segmentStarted = Date.distantPast

    private static let keepBefore = 0.8        // seconds of sound kept from before a stretch
    private static let quietEnds = 1.2         // seconds of quiet that end a stretch
    private static let longest = 20.0          // seconds; a stretch never runs longer

    /// Whether this iPad recognizes speech without sending the sound to Apple.
    static var recognizesOnDevice: Bool {
        SFSpeechRecognizer(locale: Locale(identifier: "en-US"))?.supportsOnDeviceRecognition ?? false
    }

    static func askPermission() async -> Bool {
        let mic = await AVAudioApplication.requestRecordPermission()
        guard mic else { return false }
        let speech = await withCheckedContinuation { done in
            SFSpeechRecognizer.requestAuthorization { done.resume(returning: $0 == .authorized) }
        }
        return speech
    }

    static var permitted: Bool {
        AVAudioApplication.shared.recordPermission == .granted && SFSpeechRecognizer.authorizationStatus() == .authorized
    }

    func start(hints: [String]) {
        queue.async { self.startOnQueue(hints: hints) }
    }

    func stop() {
        queue.async { self.stopOnQueue() }
    }

    /// Stop hearing (while the display itself is speaking) or hear again.
    func mute(_ on: Bool) {
        queue.async {
            self.muted = on
            if on { self.dropSegment() }
            self.recent.removeAll()
            self.recentSeconds = 0
            self.loudRun = 0
        }
    }

    private var hints: [String] = []

    private func startOnQueue(hints: [String]) {
        self.hints = hints
        guard !running else { return }
        guard let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "en-US")), recognizer.isAvailable else {
            return fail("Speech recognition isn't available on this iPad right now.")
        }
        self.recognizer = recognizer
        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.playAndRecord, mode: .default, options: [.defaultToSpeaker])
            try session.setActive(true)
            let input = engine.inputNode
            let format = input.outputFormat(forBus: 0)
            guard format.sampleRate > 0, format.channelCount > 0 else { return fail("The microphone isn't available.") }
            input.removeTap(onBus: 0)
            input.installTap(onBus: 0, bufferSize: 2048, format: format) { [weak self] buffer, _ in
                guard let self, let copy = Self.copy(buffer) else { return }
                let level = Self.level(copy)
                self.queue.async { self.take(copy, level: level) }
            }
            engine.prepare()
            try engine.start()
        } catch {
            engine.inputNode.removeTap(onBus: 0)
            return fail("The microphone couldn't be started (\(error.localizedDescription)).")
        }
        running = true
        watchForChanges()
    }

    private func stopOnQueue() {
        guard running else { return }
        running = false
        observers.forEach(NotificationCenter.default.removeObserver)
        observers.removeAll()
        dropSegment()
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
        recent.removeAll()
        recentSeconds = 0
        // Hands the microphone back, so the iPad's recording indicator goes out.
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }

    private func fail(_ message: String) {
        DispatchQueue.main.async { self.onEvent?(.failed(message)) }
    }

    /// A phone call, a headset or iPadOS itself can take the microphone away; start again after.
    private func watchForChanges() {
        let center = NotificationCenter.default
        let restart: (Notification) -> Void = { [weak self] _ in
            self?.queue.asyncAfter(deadline: .now() + 1) {
                guard let self, self.running else { return }
                let hints = self.hints
                self.stopOnQueue()
                self.startOnQueue(hints: hints)
            }
        }
        observers = [
            center.addObserver(forName: .AVAudioEngineConfigurationChange, object: engine, queue: nil, using: restart),
            center.addObserver(forName: AVAudioSession.mediaServicesWereResetNotification, object: nil, queue: nil, using: restart),
            center.addObserver(forName: AVAudioSession.interruptionNotification, object: nil, queue: nil) { note in
                let ended = note.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt == AVAudioSession.InterruptionType.ended.rawValue
                if ended { restart(note) }
            },
        ]
    }

    // MARK: - Sound in

    private func take(_ buffer: AVAudioPCMBuffer, level: Float) {
        guard running, !muted else { return }
        let now = Date()
        let seconds = Double(buffer.frameLength) / buffer.format.sampleRate
        let loud = level > max(floor * 3, 0.008)
        // The floor follows steady noise (a tap running, a fan): up slowly, down quickly.
        floor = min(0.05, level > floor ? floor * 0.998 + level * 0.002 : floor * 0.9 + level * 0.1)

        if let request {
            request.append(buffer)
            if loud { lastLoud = now }
            if now.timeIntervalSince(lastLoud) > Self.quietEnds || now.timeIntervalSince(segmentStarted) > Self.longest {
                request.endAudio()
                self.request = nil
            }
            return
        }

        recent.append(buffer)
        recentSeconds += seconds
        while recentSeconds > Self.keepBefore, let first = recent.first {
            recentSeconds -= Double(first.frameLength) / first.format.sampleRate
            recent.removeFirst()
        }
        loudRun = loud ? loudRun + 1 : 0
        // The recognizer takes one stretch at a time; a stuck one is given up after 5 seconds.
        if task != nil, now.timeIntervalSince(taskStarted) > Self.longest + 5 { dropSegment() }
        if loudRun >= 2, task == nil { beginSegment(now: now) }
    }

    private func beginSegment(now: Date) {
        guard let recognizer, recognizer.isAvailable else { return }
        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true
        request.requiresOnDeviceRecognition = recognizer.supportsOnDeviceRecognition
        request.contextualStrings = hints
        request.addsPunctuation = false
        recent.forEach(request.append)
        recent.removeAll()
        recentSeconds = 0
        loudRun = 0
        lastLoud = now
        segmentStarted = now
        taskStarted = now
        lastWords = ""
        taskNumber += 1
        let number = taskNumber
        self.request = request
        task = recognizer.recognitionTask(with: request) { [weak self] result, error in
            let words = result?.bestTranscription.formattedString
            let done = result?.isFinal == true || error != nil
            self?.queue.async { self?.result(number: number, words: words, done: done) }
        }
    }

    private func result(number: Int, words: String?, done: Bool) {
        guard number == taskNumber, task != nil else { return }
        if let words, !words.isEmpty { lastWords = words }
        let heard = lastWords
        if done {
            task = nil
            request = nil
            lastWords = ""
            if !heard.isEmpty { DispatchQueue.main.async { self.onEvent?(.heard(heard)) } }
        } else if !heard.isEmpty {
            DispatchQueue.main.async { self.onEvent?(.partial(heard)) }
        }
    }

    private func dropSegment() {
        taskNumber += 1
        task?.cancel()
        task = nil
        request = nil
        lastWords = ""
    }

    // MARK: - Buffers

    private static func copy(_ buffer: AVAudioPCMBuffer) -> AVAudioPCMBuffer? {
        guard let copy = AVAudioPCMBuffer(pcmFormat: buffer.format, frameCapacity: buffer.frameLength) else { return nil }
        copy.frameLength = buffer.frameLength
        let source = UnsafeMutableAudioBufferListPointer(buffer.mutableAudioBufferList)
        let target = UnsafeMutableAudioBufferListPointer(copy.mutableAudioBufferList)
        for (from, to) in zip(source, target) {
            guard let fromData = from.mData, let toData = to.mData else { return nil }
            memcpy(toData, fromData, Int(min(from.mDataByteSize, to.mDataByteSize)))
        }
        return copy
    }

    /// Root mean square of the first channel, 0…1.
    private static func level(_ buffer: AVAudioPCMBuffer) -> Float {
        guard let samples = buffer.floatChannelData?[0], buffer.frameLength > 0 else { return 0 }
        var sum: Float = 0
        for index in 0..<Int(buffer.frameLength) { sum += samples[index] * samples[index] }
        return (sum / Float(buffer.frameLength)).squareRoot()
    }
}
