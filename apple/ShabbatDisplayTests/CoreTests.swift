import AVFoundation
import XCTest
import HomeKit
@testable import ShabbatDisplay

final class ServerAddressTests: XCTestCase {
    func testBareAddressGetsHttpAndThePort() {
        XCTAssertEqual(ServerAddress("192.168.4.109")?.base.absoluteString, "http://192.168.4.109:8765")
        XCTAssertEqual(ServerAddress("  desktop-h72vkdj  ")?.display, "desktop-h72vkdj:8765")
    }

    func testTypedPortAndPathAreKeptAndDropped() {
        XCTAssertEqual(ServerAddress("http://192.168.4.109:9000/?screen=x#y")?.base.absoluteString, "http://192.168.4.109:9000")
        XCTAssertEqual(ServerAddress("https://display.example")?.base.absoluteString, "https://display.example")
    }

    func testNonsenseIsRefused() {
        XCTAssertNil(ServerAddress(""))
        XCTAssertNil(ServerAddress("ftp://192.168.4.109"))
        XCTAssertNil(ServerAddress("http://"))
    }

    func testPageAndStateURLs() {
        let server = ServerAddress("192.168.4.109")!
        XCTAssertEqual(server.page(screen: "Kitchen iPad").absoluteString, "http://192.168.4.109:8765/?screen=Kitchen%20iPad")
        XCTAssertEqual(server.state(screen: "iPad").absoluteString, "http://192.168.4.109:8765/api/state?screen=iPad&preview=1")
        XCTAssertEqual(server.health.absoluteString, "http://192.168.4.109:8765/health")
    }

    func testScreenNames() {
        XCTAssertTrue(validScreenName("Avi's iPad-2.0"))
        XCTAssertFalse(validScreenName(""))
        XCTAssertFalse(validScreenName("a/b"))
        XCTAssertFalse(validScreenName(" iPad"))
        XCTAssertFalse(validScreenName(String(repeating: "a", count: 41)))
        XCTAssertFalse(validScreenName("אייפד"))
    }
}

final class HolySpansTests: XCTestCase {
    private func at(_ text: String) -> Date { HolySpans.parse(text)! }

    private let week: [HolyMark] = [
        HolyMark(kind: .havdalah, date: HolySpans.parse("2026-11-07T17:25:00-05:00")!),
        HolyMark(kind: .candles, date: HolySpans.parse("2026-11-13T16:17:00-05:00")!),
        HolyMark(kind: .havdalah, date: HolySpans.parse("2026-11-14T17:19:00-05:00")!),
        HolyMark(kind: .candles, date: HolySpans.parse("2026-11-20T16:12:00-05:00")!),
    ]

    func testWeekdayKnowsTheNextCandles() {
        XCTAssertEqual(HolySpans.state(marks: week, now: at("2026-11-12T09:00:00-05:00")),
                       .weekday(nextCandles: at("2026-11-13T16:17:00-05:00")))
    }

    func testHolyFromCandlesToHavdalah() {
        XCTAssertEqual(HolySpans.state(marks: week, now: at("2026-11-13T16:17:00-05:00")),
                       .holy(until: at("2026-11-14T17:19:00-05:00")))
        XCTAssertEqual(HolySpans.state(marks: week, now: at("2026-11-14T12:00:00-05:00")),
                       .holy(until: at("2026-11-14T17:19:00-05:00")))
        XCTAssertTrue(HolySpans.state(marks: week, now: at("2026-11-14T17:19:00-05:00")).weekdayForCertain)
    }

    func testSecondNightCandlesStayInTheSpan() {
        let yomTov = [
            HolyMark(kind: .candles, date: at("2026-09-11T18:52:00-04:00")),
            HolyMark(kind: .candles, date: at("2026-09-12T19:49:00-04:00")),
            HolyMark(kind: .havdalah, date: at("2026-09-13T19:47:00-04:00")),
            HolyMark(kind: .candles, date: at("2026-09-18T18:40:00-04:00")),
        ]
        XCTAssertEqual(HolySpans.state(marks: yomTov, now: at("2026-09-12T22:00:00-04:00")),
                       .holy(until: at("2026-09-13T19:47:00-04:00")))
    }

    func testCalendarThatRanOutIsUnknownNotWeekday() {
        XCTAssertEqual(HolySpans.state(marks: [], now: Date()), .unknown)
        XCTAssertEqual(HolySpans.state(marks: week, now: at("2026-11-25T09:00:00-05:00")), .holy(until: nil))
        let stale = Array(week.dropLast())
        let state = HolySpans.state(marks: stale, now: at("2026-11-25T09:00:00-05:00"))
        XCTAssertEqual(state, .unknown)
        XCTAssertFalse(state.weekdayForCertain)
    }

    func testMarksFromState() throws {
        let json = """
        {"now": "2026-11-12T09:00:00", "data": {"calendar": {"items": [
          {"category": "parashat", "date": "2026-11-14", "title": "Parashat Toldot"},
          {"category": "havdalah", "date": "2026-11-14T17:19:00-05:00", "title": "Havdalah"},
          {"category": "candles", "date": "2026-11-13T16:17:00-05:00", "title": "Candle lighting"},
          {"category": "candles", "date": "not a date"}
        ]}}}
        """
        let marks = try XCTUnwrap(HolySpans.marks(fromState: Data(json.utf8)))
        XCTAssertEqual(marks.map(\.kind), [.candles, .havdalah])
        XCTAssertNil(HolySpans.marks(fromState: Data("{}".utf8)))
    }
}

final class WakePhraseTests: XCTestCase {
    private let wake = WakePhrase("Hey Display")!

    func testRequestAfterThePhrase() {
        XCTAssertEqual(wake.command(in: "Hey display set a timer for 10 minutes"), "set a timer for 10 minutes")
        XCTAssertEqual(wake.command(in: "so anyway, hey, Display! what's 2 1/2 cups doubled?"), "what's 2 1/2 cups doubled")
        XCTAssertEqual(wake.command(in: "hay display add milk"), "add milk")
        XCTAssertEqual(wake.command(in: "a display add milk"), "add milk")
    }

    func testPhraseAloneAndPhraseTwice() {
        XCTAssertEqual(wake.command(in: "hey display"), "")
        XCTAssertEqual(wake.command(in: "hey display um hey display add eggs"), "add eggs")
    }

    func testOrdinaryTalkIsNotTheWakePhrase() {
        XCTAssertNil(wake.command(in: "the display is nice"))
        XCTAssertNil(wake.command(in: "hey this plays music"))
        XCTAssertNil(wake.command(in: "display"))
        XCTAssertNil(wake.command(in: ""))
    }

    func testPhrasesThatCantBeUsed() {
        XCTAssertNil(WakePhrase(""))
        XCTAssertNil(WakePhrase("?!"))
        XCTAssertNil(WakePhrase("one two three four five"))
        XCTAssertEqual(WakePhrase("  Computer ")?.command(in: "computer, lights"), "lights")
    }

    func testStopWords() {
        XCTAssertTrue(StopWords.heard(in: "Okay, stop!"))
        XCTAssertTrue(StopWords.heard(in: "thanks"))
        XCTAssertFalse(StopWords.heard(in: "the stopwatch is offline"))
    }
}

final class KitchenTimersTests: XCTestCase {
    private let start = Date(timeIntervalSince1970: 1_800_000_000)

    func testTimersRingInOrderAndGoQuiet() {
        var timers = KitchenTimers()
        timers.add(seconds: 600, label: "pasta", now: start)
        timers.add(seconds: 60, label: "", now: start)
        XCTAssertEqual(timers.all.map(\.label), ["", "pasta"])
        XCTAssertEqual(timers.advance(to: start.addingTimeInterval(59)).count, 0)
        XCTAssertEqual(timers.advance(to: start.addingTimeInterval(60)).map(\.name), ["Timer"])
        XCTAssertEqual(timers.advance(to: start.addingTimeInterval(61)).count, 0, "it rings once")
        XCTAssertEqual(timers.ringing.count, 1)
        timers.silence()
        XCTAssertEqual(timers.all.map(\.label), ["pasta"])
        XCTAssertEqual(timers.advance(to: start.addingTimeInterval(600)).map(\.name), ["Pasta"])
        XCTAssertEqual(timers.advance(to: start.addingTimeInterval(600 + 181)).count, 0)
        XCTAssertTrue(timers.all.isEmpty, "a timer nobody stops goes quiet after three minutes")
    }

    func testATimerThatEndedWhileTheAppWasClosedIsDropped() {
        var timers = KitchenTimers()
        timers.add(seconds: 60, label: "eggs", now: start)
        XCTAssertTrue(timers.advance(to: start.addingTimeInterval(3600)).isEmpty)
        XCTAssertTrue(timers.all.isEmpty)
    }

    func testCancelByLabel() {
        var timers = KitchenTimers()
        for label in ["pasta", "rice", "challah dough"] { timers.add(seconds: 600, label: label, now: start) }
        timers.cancel(label: "Rice")
        XCTAssertEqual(timers.all.map(\.label), ["pasta", "challah dough"])
        timers.cancel(label: "challah")
        XCTAssertEqual(timers.all.map(\.label), ["pasta"])
        timers.cancel(label: "soup")
        XCTAssertEqual(timers.all.count, 1)
        timers.cancel(label: "all")
        XCTAssertTrue(timers.all.isEmpty)
    }

    func testBadLengthsAreIgnoredAndTheReport() {
        var timers = KitchenTimers()
        timers.add(seconds: 0, label: "x", now: start)
        timers.add(seconds: 90_000, label: "x", now: start)
        XCTAssertTrue(timers.all.isEmpty)
        timers.add(seconds: 90, label: "tea", now: start)
        let report = timers.report(now: start.addingTimeInterval(30))
        XCTAssertEqual(report.first?["seconds_left"] as? Int, 60)
        XCTAssertEqual(report.first?["label"] as? String, "tea")
        XCTAssertEqual(countdown(3725), "1:02:05")
        XCTAssertEqual(countdown(59.2), "1:00")
    }
}

final class AssistantReplyTests: XCTestCase {
    func testAnAnswerWithActions() throws {
        let json = #"{"ok": true, "say": " Pasta timer set. ", "actions": [{"type": "set_timer", "seconds": 600, "label": "pasta"}, {"type": "cancel_timer", "label": "all"}, {"type": "launch_rocket"}, {"type": "set_timer", "seconds": 0}]}"#
        let reply = try XCTUnwrap(AssistantReply.parse(Data(json.utf8)))
        XCTAssertEqual(reply, AssistantReply(say: "Pasta timer set.", actions: [.setTimer(seconds: 600, label: "pasta"), .cancelTimer(label: "all")], error: nil))
    }

    func testMusicAndCodeActions() throws {
        let json = #"{"ok": true, "say": "Jazz.", "actions": [{"type": "play_music", "query": "quiet jazz", "kind": "any"}, {"type": "play_music", "query": ""}, {"type": "music_control", "command": "next"}, {"type": "music_control", "command": "louder"}, {"type": "show_code", "url": "https://www.walmart.com/sc/cart/addToCart?items=1_2", "title": "Walmart cart"}, {"type": "show_code", "path": "/shop", "title": "Shopping list"}, {"type": "show_code", "url": "javascript:alert(1)"}, {"type": "show_code", "path": "//evil.example/x"}]}"#
        let reply = try XCTUnwrap(AssistantReply.parse(Data(json.utf8)))
        XCTAssertEqual(reply.actions, [
            .playMusic(query: "quiet jazz", kind: "any"), .musicControl("next"),
            .showCode(title: "Walmart cart", url: "https://www.walmart.com/sc/cart/addToCart?items=1_2", path: nil),
            .showCode(title: "Shopping list", url: nil, path: "/shop"),
        ])
    }

    func testPhoneCode() throws {
        let cart = try XCTUnwrap(PhoneCode(title: "", link: URL(string: "https://www.walmart.com/sc/cart/addToCart?items=1_2")!))
        XCTAssertEqual(cart.title, "Open on your phone")
        XCTAssertGreaterThan(cart.image.size.width, 200)
        XCTAssertTrue(cart.hint.contains("check out there"))
        let page = URL(string: "/shop", relativeTo: ServerAddress("192.168.4.109")!.base)!.absoluteURL
        XCTAssertEqual(page.absoluteString, "http://192.168.4.109:8765/shop")
        XCTAssertTrue(try XCTUnwrap(PhoneCode(title: "Shopping list", link: page)).hint.contains("home Wi-Fi"))
    }

    func testARefusalAndNonsense() throws {
        let reply = try XCTUnwrap(AssistantReply.parse(Data(#"{"ok": false, "error": "budget_month", "say": "I've reached this month's spending limit."}"#.utf8)))
        XCTAssertEqual(reply.error, "budget_month")
        XCTAssertEqual(reply.say, "I've reached this month's spending limit.")
        XCTAssertNil(AssistantReply.parse(Data("not json".utf8)))
    }

    func testTheRequestBody() throws {
        let data = AssistantClient.body(text: "how long", timers: [["label": "tea", "seconds_left": 60, "ringing": false]],
                                        history: [AssistantClient.Exchange(q: "q1", a: "a1")])
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        XCTAssertEqual(json["text"] as? String, "how long")
        XCTAssertEqual((json["history"] as? [[String: String]])?.first, ["q": "q1", "a": "a1"])
        XCTAssertEqual((json["timers"] as? [[String: Any]])?.first?["seconds_left"] as? Int, 60)
    }
}

final class SpokenVoiceTests: XCTestCase {
    func testQualityRanksAndLabels() {
        XCTAssertEqual(SpokenVoice.rank(.premium), 2)
        XCTAssertEqual(SpokenVoice.rank(.enhanced), 1)
        XCTAssertEqual(SpokenVoice.rank(.default), 0)
        XCTAssertEqual(SpokenVoice.Choice(id: "a", name: "Zoe", rank: 2).label, "Zoe (Premium)")
        XCTAssertEqual(SpokenVoice.Choice(id: "b", name: "Samantha", rank: 0).label, "Samantha")
    }

    func testRoboticVoicesAreLeftOut() {
        XCTAssertFalse(SpokenVoice.natural(identifier: "com.apple.eloquence.en-US.Rocko"))
        XCTAssertFalse(SpokenVoice.natural(identifier: "com.apple.speech.synthesis.voice.Fred"))
        XCTAssertTrue(SpokenVoice.natural(identifier: "com.apple.voice.compact.en-US.Samantha"))
        XCTAssertTrue(SpokenVoice.natural(identifier: "com.apple.voice.premium.en-US.Zoe"))
    }

    func testChoicesAreEnglishBestFirstAndAFallbackAlwaysExists() {
        let choices = SpokenVoice.choices()
        XCTAssertEqual(choices.map(\.rank), choices.map(\.rank).sorted(by: >))
        XCTAssertNotNil(SpokenVoice.chosen(""))
        XCTAssertNotNil(SpokenVoice.chosen("com.example.not-installed"))
    }
}

final class HomeTests: XCTestCase {
    func testTemperatures() {
        XCTAssertEqual(HomeMath.fahrenheit(20), 68)
        XCTAssertEqual(HomeMath.fahrenheit(21.5), 71)
        XCTAssertEqual(HomeMath.celsius(70), 21.0)
        XCTAssertEqual(HomeMath.celsius(68), 20.0)
        XCTAssertEqual(HomeMath.celsius(73), 23.0)
    }

    func testOnlyLockingAndClosingArePassed() {
        let lock = "00000019-0000-1000-8000-0026BB765291"   // target lock state
        XCTAssertTrue(HomeMath.opensADoor(characteristicType: HMCharacteristicTypeTargetLockMechanismState, value: 0))
        XCTAssertFalse(HomeMath.opensADoor(characteristicType: HMCharacteristicTypeTargetLockMechanismState, value: 1))
        XCTAssertTrue(HomeMath.opensADoor(characteristicType: HMCharacteristicTypeTargetDoorState, value: 0))
        XCTAssertTrue(HomeMath.opensADoor(characteristicType: HMCharacteristicTypeTargetDoorState, value: nil))
        XCTAssertFalse(HomeMath.opensADoor(characteristicType: HMCharacteristicTypePowerState, value: 0))
        _ = lock
    }

    func testHomeActions() throws {
        let json = #"{"ok": true, "say": "Okay.", "actions": [{"type": "home_set", "device": "Lamp", "room": "Den", "action": "brightness", "value": 30}, {"type": "home_set", "device": "Front door", "action": "unlock"}, {"type": "home_set", "device": "Front door", "action": "lock"}, {"type": "home_scene", "name": "Good Night"}, {"type": "home_scene", "name": ""}]}"#
        let reply = try XCTUnwrap(AssistantReply.parse(Data(json.utf8)))
        XCTAssertEqual(reply.actions, [.homeSet(device: "Lamp", room: "Den", action: "brightness", value: 30),
                                       .homeSet(device: "Front door", room: "", action: "lock", value: nil),
                                       .homeScene("Good Night")])
    }
}

final class RemindersTests: XCTestCase {
    private var calendar: Calendar = {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "America/New_York")!
        return calendar
    }()

    private func at(_ text: String) -> Date { Reminders.date(from: text, calendar: calendar)! }

    func testTimesGoBothWays() {
        XCTAssertEqual(Reminders.text(from: at("2026-11-12T16:00"), calendar: calendar), "2026-11-12T16:00")
        XCTAssertNotNil(Reminders.date(from: "2026-11-12T16:00:30", calendar: calendar))
        XCTAssertNil(Reminders.date(from: "tomorrow", calendar: calendar))
    }

    func testAReminderIsSaidOnceWhenDue() {
        var reminders = Reminders()
        reminders.add(text: " take the challah out ", when: at("2026-11-12T16:00"), again: .none)
        XCTAssertTrue(reminders.advance(to: at("2026-11-12T15:59"), calendar: calendar).isEmpty)
        XCTAssertEqual(reminders.advance(to: at("2026-11-12T16:00"), calendar: calendar).map(\.text), ["take the challah out"])
        XCTAssertTrue(reminders.all.isEmpty)
    }

    func testOneMissedByMoreThanTenMinutesIsDroppedSilently() {
        var reminders = Reminders()
        reminders.add(text: "old", when: at("2026-11-12T16:00"), again: .none)
        XCTAssertTrue(reminders.advance(to: at("2026-11-12T16:11"), calendar: calendar).isEmpty)
        XCTAssertTrue(reminders.all.isEmpty)
    }

    func testDailyAndWeekdayRepeats() {
        var reminders = Reminders()
        reminders.add(text: "vitamins", when: at("2026-11-12T08:00"), again: .daily)
        reminders.add(text: "wake up", when: at("2026-11-13T07:00"), again: .weekdays)   // a Friday
        XCTAssertEqual(reminders.advance(to: at("2026-11-12T08:00"), calendar: calendar).map(\.text), ["vitamins"])
        XCTAssertEqual(reminders.advance(to: at("2026-11-13T07:00"), calendar: calendar).map(\.text), ["wake up"])
        let next = Dictionary(uniqueKeysWithValues: reminders.all.map { ($0.text, Reminders.text(from: $0.when, calendar: calendar)) })
        XCTAssertEqual(next["vitamins"], "2026-11-13T08:00")
        XCTAssertEqual(next["wake up"], "2026-11-15T07:00", "Saturday is skipped")
        // The app was closed for three days: the daily one comes back at its next time, said once at most.
        XCTAssertTrue(reminders.advance(to: at("2026-11-16T12:00"), calendar: calendar).isEmpty)
        XCTAssertEqual(reminders.all.first { $0.text == "vitamins" }.map { Reminders.text(from: $0.when, calendar: calendar) }, "2026-11-17T08:00")
    }

    func testCancelAndReport() {
        var reminders = Reminders()
        reminders.add(text: "take the challah out", when: at("2026-11-12T16:00"), again: .none)
        reminders.add(text: "wake up", when: at("2026-11-13T07:00"), again: .weekdays)
        XCTAssertEqual(reminders.report(calendar: calendar).last?["repeat"] as? String, "weekdays")
        reminders.cancel(text: "Challah")
        XCTAssertEqual(reminders.all.map(\.text), ["wake up"])
        reminders.cancel(text: "all")
        XCTAssertTrue(reminders.all.isEmpty)
    }
}

final class FeedsTests: XCTestCase {
    func testAnnouncementsFromOtherScreensOnly() throws {
        let json = #"{"ok": true, "last": 7, "items": [{"id": 6, "text": "Dinner is ready.", "from": "Kitchen"}, {"id": 7, "text": "My own.", "from": "iPad"}, {"id": 8, "text": ""}]}"#
        XCTAssertEqual(AnnouncementFeed.parse(Data(json.utf8), mine: "iPad"), AnnouncementFeed.Batch(last: 7, texts: ["Dinner is ready."]))
        XCTAssertNil(AnnouncementFeed.parse(Data("{}".utf8), mine: "iPad"))
    }

    func testRadioStationChoice() throws {
        let json = #"[{"name": "No stream", "url": ""}, {"name": " WNYC-FM ", "url": "http://old", "url_resolved": "https://fm939.wnyc.org/wnycfm"}, {"name": "Other", "url_resolved": "https://x"}]"#
        let station = try XCTUnwrap(RadioBox.pick(from: Data(json.utf8)))
        XCTAssertEqual(station, RadioBox.Station(name: "WNYC-FM", stream: URL(string: "https://fm939.wnyc.org/wnycfm")!))
        XCTAssertNil(RadioBox.pick(from: Data("[]".utf8)))
        XCTAssertTrue(RadioBox.search("BBC World").absoluteString.contains("name=BBC%20World"))
        XCTAssertEqual(RadioBox.queries(for: "1010 WINS"), ["1010 WINS", "WINS"])
        XCTAssertEqual(RadioBox.queries(for: "WNYC"), ["WNYC"])
        XCTAssertEqual(RadioBox.queries(for: "the Kol Israel radio station"), ["the Kol Israel radio station", "Israel", "Kol"])
    }

    func testReminderAndRadioActions() throws {
        let json = #"{"ok": true, "say": "Okay.", "actions": [{"type": "set_reminder", "when": "2026-11-12T16:00", "text": "challah", "repeat": "none"}, {"type": "cancel_reminder", "text": "challah"}, {"type": "play_radio", "station": "WNYC"}, {"type": "play_radio", "station": ""}]}"#
        XCTAssertEqual(try XCTUnwrap(AssistantReply.parse(Data(json.utf8))).actions,
                       [.setReminder(when: "2026-11-12T16:00", text: "challah", again: "none"), .cancelReminder("challah"), .playRadio("WNYC")])
    }
}

final class PushTests: XCTestCase {
    func testRegistration() throws {
        let body = try XCTUnwrap(JSONSerialization.jsonObject(with: Push.body(token: "ab12", screen: "Dov's iPhone", environment: "development")) as? [String: String])
        XCTAssertEqual(body, ["token": "ab12", "screen": "Dov's iPhone", "env": "development"])
        XCTAssertEqual(Push.parse(Data(#"{"ok": true, "set_up": true}"#.utf8)), .ready)
        XCTAssertEqual(Push.parse(Data(#"{"ok": true, "set_up": false}"#.utf8)), .serverNotSetUp)
        XCTAssertNil(Push.parse(Data(#"{"ok": false, "error": "no"}"#.utf8)))
        XCTAssertNil(Push.parse(Data("not found".utf8)))
    }

    func testTheRequestSaysWhichDeviceAsked() throws {
        let body = try XCTUnwrap(JSONSerialization.jsonObject(with: AssistantClient.body(text: "x", timers: [], history: [], device: "ab12")) as? [String: Any])
        XCTAssertEqual(body["device"] as? String, "ab12")
    }

    func testWhetherTheDisplayShowsIsRemembered() {
        let store = UserDefaults(suiteName: "push-tests")!
        store.removePersistentDomain(forName: "push-tests")
        let settings = Settings(store: store)
        XCTAssertNil(settings.displayOn)
        settings.displayOn = false
        XCTAssertEqual(settings.displayOn, false)
    }

    func testASoundFileANotificationCanPlay() {
        let format = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 22_050, channels: 1, interleaved: false)!
        let settings = SpokenFile.settings(format)
        XCTAssertEqual(settings[AVFormatIDKey] as? AudioFormatID, kAudioFormatLinearPCM)
        XCTAssertEqual(settings[AVLinearPCMBitDepthKey] as? Int, 16)
        XCTAssertEqual(settings[AVLinearPCMIsFloatKey] as? Bool, false)
    }

    func testOldAnnouncementFilesAreRemoved() throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let old = folder.appendingPathComponent(SpokenFile.prefix + "old.caf"), other = folder.appendingPathComponent("chime.caf")
        try Data("x".utf8).write(to: old)
        try Data("x".utf8).write(to: other)
        SpokenFile.clean(folder, now: Date().addingTimeInterval(5))
        XCTAssertTrue(FileManager.default.fileExists(atPath: old.path))
        SpokenFile.clean(folder, now: Date().addingTimeInterval(700))
        XCTAssertFalse(FileManager.default.fileExists(atPath: old.path))
        XCTAssertTrue(FileManager.default.fileExists(atPath: other.path))
    }
}
