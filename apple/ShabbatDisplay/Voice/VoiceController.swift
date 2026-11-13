import Foundation
import Observation

/// Hears the wake phrase, asks the display server, speaks the answer and runs the timers.
///
/// Nothing here runs on Shabbat or Yom Tov: `refresh()` turns the microphone off and clears
/// the timers unless the calendar positively says it is a weekday (`weekdayForCertain`).
@MainActor
@Observable
final class VoiceController {
    enum Stage: Equatable {
        /// The microphone is off.
        case off
        /// Waiting for the wake phrase.
        case waiting
        /// The wake phrase was heard; the words after it so far.
        case hearing(String)
        /// The request is with the display server.
        case asking(String)
        /// The answer, while it is spoken.
        case answering(String)
    }

    private(set) var stage: Stage = .off
    private(set) var timers: KitchenTimers
    /// Why listening isn't on although it is switched on, for the settings screen.
    private(set) var problem: String?
    private(set) var recognizesOnDevice = true
    /// A code for a phone to scan, while it is on screen.
    private(set) var code: PhoneCode?
    let music = MusicBox()
    let home = HomeBox()
    let radio = RadioBox()
    private(set) var reminders: Reminders
    private var announcementsSeen: Int?
    private var ticks = 0
    private var fetchingAnnouncements = false

    private let model: AppModel
    private let settings = Settings()
    private let listener = Listener()
    private let sounds = Sounds()
    private var listening = false
    private var active = false
    private var wake = WakePhrase(WakePhrase.standard)!
    private var chimed = false
    private var awaitingUntil = Date.distantPast
    private var history: [AssistantClient.Exchange] = []
    private var lastExchange = Date.distantPast
    private var clock: Task<Void, Never>?
    private var candles: Task<Void, Never>?
    private var lastAlarm = Date.distantPast
    private var busy = false
    private var askedAQuestion = false
    private var codeUntil = Date.distantPast

    init(model: AppModel) {
        self.model = model
        timers = KitchenTimers(Settings().timers)
        reminders = Reminders(Settings().reminders)
        listener.onEvent = { [weak self] event in
            Task { @MainActor in self?.handle(event) }
        }
    }

    var voiceOn: Bool { settings.voiceOn }
    var homeOn: Bool { settings.homeOn }
    var wakePhrase: String { settings.wakePhrase }

    /// The app came to the front or left it.
    func setActive(_ on: Bool) {
        active = on
        refresh()
        clock?.cancel()
        guard on else { return }
        clock = Task { [weak self] in
            while !Task.isCancelled {
                self?.tick()
                try? await Task.sleep(for: .seconds(1))
            }
        }
    }

    /// Saves the settings screen's choices. Asks for the microphone the first time it is switched on.
    func save(voiceOn: Bool, wakePhrase: String, homeOn: Bool) async {
        settings.wakePhrase = wakePhrase
        settings.homeOn = homeOn && voiceOn
        if voiceOn && !Listener.permitted {
            let allowed = await Listener.askPermission()
            settings.voiceOn = allowed
            problem = allowed ? nil : "The microphone or speech recognition isn't allowed. Turn them on in Settings → Shabbat Display."
        } else {
            settings.voiceOn = voiceOn
            problem = nil
        }
        stopListening()
        refresh()
    }

    /// Whether the microphone should be on right now.
    private var wanted: Bool {
        active && model.holy.weekdayForCertain && settings.voiceOn && model.server != nil
    }

    /// Brings the microphone in line with the settings, the calendar and whether the app is in front.
    func refresh() {
        let weekday = model.holy.weekdayForCertain
        if !weekday {
            // Shabbat, Yom Tov, or a calendar that can't say: no sound of any kind.
            sounds.stopSpeaking()
            music.stop()
            radio.stop()
            announcementsSeen = nil
            code = nil
            if !timers.all.isEmpty { timers.removeAll(); settings.timers = [] }
            history = []
        }
        scheduleCandles()
        // The Home is only looked at on weekdays, with voice and Home control both switched on.
        if weekday && active && settings.voiceOn && settings.homeOn { home.start() } else { home.stop() }
        let want = wanted
        if want && !listening {
            guard Listener.permitted else {
                problem = "The microphone or speech recognition isn't allowed. Turn them on in Settings → Shabbat Display."
                return
            }
            wake = WakePhrase(settings.wakePhrase) ?? WakePhrase(WakePhrase.standard)!
            listener.start(hints: [settings.wakePhrase])
            recognizesOnDevice = Listener.recognizesOnDevice
            listening = true
            stage = .waiting
        } else if !want && listening {
            stopListening()
        }
    }

    private func stopListening() {
        listener.stop()
        listening = false
        chimed = false
        awaitingUntil = .distantPast
        stage = .off
    }

    /// Runs `refresh()` at the minute of candle lighting, not up to 20 seconds after it.
    private func scheduleCandles() {
        candles?.cancel()
        guard case .weekday(let next) = model.holy else { return }
        candles = Task { [weak self] in
            try? await Task.sleep(for: .seconds(max(0, next.timeIntervalSinceNow) + 0.5))
            if !Task.isCancelled { self?.refresh() }
        }
    }

    // MARK: - Hearing

    private func handle(_ event: Listener.Event) {
        guard listening, !busy else { return }
        switch event {
        case .failed(let message):
            problem = message
            stopListening()
        case .partial(let words):
            if Date() < awaitingUntil {
                stage = .hearing(words)
            } else if let command = wake.command(in: words) {
                if !chimed { chimed = true; music.holdForSpeech(); radio.holdForSpeech(); sounds.chime() }
                stage = .hearing(command)
            }
        case .heard(let words):
            chimed = false
            if !timers.ringing.isEmpty, StopWords.heard(in: words) {
                silence()
            } else if Date() < awaitingUntil {
                awaitingUntil = .distantPast
                Task { await self.ask(words) }
            } else if let command = wake.command(in: words) {
                if command.isEmpty {
                    // Only the phrase so far: the next thing said within 8 seconds is the request.
                    awaitingUntil = Date().addingTimeInterval(8)
                    stage = .hearing("")
                } else {
                    Task { await self.ask(command) }
                }
            } else if case .hearing = stage {
                stage = .waiting
                radio.carryOn()
                Task { await self.music.carryOn() }
            }
        }
    }

    /// Sends a request to the display server and carries out the answer.
    func ask(_ request: String) async {
        guard model.holy.weekdayForCertain, let server = model.server, !busy else { return }
        if !timers.ringing.isEmpty, StopWords.heard(in: request) { return silence() }
        busy = true
        listener.mute(true)
        music.holdForSpeech()
        radio.holdForSpeech()
        stage = .asking(request)
        if Date().timeIntervalSince(lastExchange) > 180 { history = [] }
        let reply = await AssistantClient.ask(server, text: request, timers: timers.report(now: Date()), history: history,
                                              music: radio.station.map { ["playing": radio.playing, "title": "Radio: " + $0] } ?? music.report,
                                              home: home.report, reminders: reminders.report(), screen: model.screen, device: Push.token)
        // Shabbat may have begun while the answer was on its way.
        if model.holy.weekdayForCertain {
            var say: String
            if let reply {
                say = reply.error == "holy" ? "" : reply.say
                // Music that can't be played is said instead of "putting on…".
                if let trouble = await apply(reply.actions, server: server) { say = trouble }
                if reply.error == nil, !say.isEmpty {
                    history = Array((history + [AssistantClient.Exchange(q: request, a: say)]).suffix(3))
                    lastExchange = Date()
                }
            } else {
                say = "I can't reach the display computer."
            }
            if !say.isEmpty {
                stage = .answering(say)
                await sounds.say(say)
                askedAQuestion = reply?.error == nil && say.hasSuffix("?")
            }
        }
        if model.holy.weekdayForCertain { await music.carryOn(); radio.carryOn() } else { music.stop(); radio.stop() }
        busy = false
        listener.mute(false)
        if listening, askedAQuestion {
            // The display asked something back: the answer needs no wake phrase.
            askedAQuestion = false
            awaitingUntil = Date().addingTimeInterval(8)
            stage = .hearing("")
        } else {
            stage = listening ? .waiting : .off
        }
    }

    /// Carries out the answer's actions. Returns a sentence to say instead of the answer when one failed.
    private func apply(_ actions: [AssistantReply.Action], server: ServerAddress) async -> String? {
        var trouble: String?
        for action in actions {
            switch action {
            case .setTimer(let seconds, let label): timers.add(seconds: seconds, label: label, now: Date())
            case .cancelTimer(let label): timers.cancel(label: label)
            case .playMusic(let query, let kind):
                radio.stop()
                do { try await music.play(query: query, kind: kind) } catch {
                    trouble = (error as? MusicBox.Trouble ?? .failed).sentence
                }
            case .musicControl(let command):
                if radio.station != nil { radio.control(command) } else { await music.control(command) }
            case .playRadio(let station):
                music.stop()
                if await !radio.play(station) { trouble = "I couldn't find a station called \(station)." }
            case .setReminder(let when, let text, let again):
                if let date = Reminders.date(from: when) {
                    reminders.add(text: text, when: date, again: Reminder.Repeat(rawValue: again) ?? .none)
                    settings.reminders = reminders.all
                }
            case .cancelReminder(let text):
                reminders.cancel(text: text)
                settings.reminders = reminders.all
            case .homeSet(let device, let room, let what, let value):
                do { try await home.set(device: device, room: room, action: what, value: value) } catch {
                    trouble = (error as? HomeBox.Trouble ?? .failed(device)).sentence
                }
            case .homeScene(let name):
                do { try await home.run(scene: name) } catch {
                    trouble = (error as? HomeBox.Trouble ?? .failed(name)).sentence
                }
            case .showCode(let title, let url, let path):
                let link = url.flatMap(URL.init) ?? path.flatMap { URL(string: $0, relativeTo: server.base)?.absoluteURL }
                if let link, let shown = PhoneCode(title: title, link: link) {
                    code = shown
                    codeUntil = Date().addingTimeInterval(120)
                }
            }
        }
        if !actions.isEmpty { settings.timers = timers.all }
        return trouble
    }

    func dismissCode() { code = nil }

    var voiceID: String { settings.voiceID }

    /// Saves the answering voice and says a sentence in it (weekdays only).
    func tryVoice(_ id: String) {
        settings.voiceID = id
        guard model.holy.weekdayForCertain, !busy else { return }
        Task {
            listener.mute(true)
            await sounds.say("This is how I sound. Candle lighting is at four twenty-one.")
            listener.mute(false)
        }
    }

    // MARK: - Timers

    /// Stops whatever is ringing (a tap, or "stop").
    func silence() {
        timers.silence()
        settings.timers = timers.all
        sounds.stopSpeaking()
    }

    func cancel(_ timer: KitchenTimer) {
        timers.cancel(label: timer.label.isEmpty ? "all" : timer.label)
        settings.timers = timers.all
    }

    /// Chimes and says something the display itself has to say (a reminder, an announcement).
    private func say(_ sentences: [String]) {
        guard model.holy.weekdayForCertain, !busy else { return }
        busy = true
        Task {
            listener.mute(true)
            music.holdForSpeech()
            radio.holdForSpeech()
            let words = sentences.joined(separator: " ")
            stage = .answering(words)
            sounds.chime()
            try? await Task.sleep(for: .seconds(0.4))
            await sounds.say(words)
            if model.holy.weekdayForCertain { await music.carryOn(); radio.carryOn() }
            busy = false
            listener.mute(false)
            stage = listening ? .waiting : .off
        }
    }

    private func checkAnnouncements(_ server: ServerAddress) {
        fetchingAnnouncements = true
        Task {
            defer { fetchingAnnouncements = false }
            guard let batch = await AnnouncementFeed.fetch(server, since: announcementsSeen ?? 0, mine: model.screen) else { return }
            // The first answer only sets the mark: older announcements were for whoever was here then.
            let first = announcementsSeen == nil
            announcementsSeen = batch.last
            if !first, !batch.texts.isEmpty { say(batch.texts) }
        }
    }

    private func tick() {
        if wanted != listening || !model.holy.weekdayForCertain { refresh() }
        guard model.holy.weekdayForCertain else { return }
        music.look()
        home.readValues()
        ticks += 1
        let due = reminders.advance(to: Date())
        if !due.isEmpty || reminders.all != settings.reminders { settings.reminders = reminders.all }
        if !due.isEmpty, !busy { say(["Reminder."] + due.map { $0.text + "." }) }
        if ticks % 3 == 0, settings.voiceOn, !fetchingAnnouncements, let server = model.server { checkAnnouncements(server) }
        if code != nil, Date() > codeUntil { code = nil }
        if !busy, case .hearing = stage, awaitingUntil != .distantPast, Date() > awaitingUntil {
            // The wake phrase was said and nothing followed.
            awaitingUntil = .distantPast
            stage = listening ? .waiting : .off
            Task { await self.music.carryOn() }
        }
        let before = timers
        let started = timers.advance(to: Date())
        if timers != before { settings.timers = timers.all }
        if let first = started.first, !busy {
            lastAlarm = Date()
            Task {
                listener.mute(true)
                sounds.alarm()
                try? await Task.sleep(for: .seconds(0.9))
                await sounds.say(first.label.isEmpty ? "Your timer is done." : "The \(first.label) timer is done.")
                listener.mute(false)
            }
        } else if !timers.ringing.isEmpty, !busy, Date().timeIntervalSince(lastAlarm) > 4 {
            // Beeps with gaps, so "stop" can be heard between them.
            lastAlarm = Date()
            sounds.alarm()
        }
    }
}
