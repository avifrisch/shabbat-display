import XCTest
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
