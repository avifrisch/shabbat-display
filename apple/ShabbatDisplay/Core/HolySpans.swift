import Foundation

/// A candle lighting or havdalah from the server's Hebcal calendar.
struct HolyMark: Codable, Equatable {
    enum Kind: String, Codable { case candles, havdalah }
    let kind: Kind
    let date: Date
}

/// Whether it is Shabbat or Yom Tov now, as far as this iPad can tell.
enum HolyState: Equatable {
    /// Between a candle lighting and the next havdalah.
    case holy(until: Date?)
    /// A weekday, with the next candle lighting known.
    case weekday(nextCandles: Date)
    /// No calendar, or one too old to say. Treated like Shabbat for anything that must be off then.
    case unknown

    /// Anything that must never run on Shabbat or Yom Tov (the microphone, speech, music)
    /// asks this. It is true only when the calendar positively says it is a weekday.
    var weekdayForCertain: Bool {
        if case .weekday = self { return true }
        return false
    }

    var isHoly: Bool {
        if case .holy = self { return true }
        return false
    }
}

enum HolySpans {
    /// The marks in the `calendar` source of `/api/state`.
    static func marks(fromState json: Data) -> [HolyMark]? {
        guard let root = try? JSONSerialization.jsonObject(with: json) as? [String: Any],
              let data = root["data"] as? [String: Any],
              let calendar = data["calendar"] as? [String: Any],
              let items = calendar["items"] as? [[String: Any]] else { return nil }
        let marks = items.compactMap { item -> HolyMark? in
            guard let category = item["category"] as? String, let kind = HolyMark.Kind(rawValue: category),
                  let text = item["date"] as? String, let date = parse(text) else { return nil }
            return HolyMark(kind: kind, date: date)
        }
        return marks.sorted { $0.date < $1.date }
    }

    /// The same rule as the page's `holyState()`: holy from the last candle lighting until
    /// the next havdalah, so a second night's candles stay inside the span. Unlike the page,
    /// a calendar that has run out (no candle lighting ahead) answers `.unknown`, not weekday.
    static func state(marks: [HolyMark], now: Date) -> HolyState {
        let sorted = marks.sorted { $0.date < $1.date }
        let last = sorted.last { $0.date <= now }
        if let last, last.kind == .candles {
            return .holy(until: sorted.first { $0.kind == .havdalah && $0.date > now }?.date)
        }
        if let next = sorted.first(where: { $0.kind == .candles && $0.date > now }) {
            return .weekday(nextCandles: next.date)
        }
        return .unknown
    }

    static func parse(_ text: String) -> Date? {
        let withZone = ISO8601DateFormatter()
        withZone.formatOptions = [.withInternetDateTime]
        if let date = withZone.date(from: text) { return date }
        withZone.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return withZone.date(from: text)
    }
}
