import Foundation

/// Finds the wake phrase in what the recognizer heard.
struct WakePhrase: Equatable {
    static let standard = "hey display"

    let words: [String]

    /// Nil when the text has no letters or digits to listen for.
    init?(_ phrase: String) {
        let words = phrase.split(whereSeparator: \.isWhitespace).map(Self.plain).filter { !$0.isEmpty }
        guard !words.isEmpty, words.count <= 4 else { return nil }
        self.words = words
    }

    /// What was said after the phrase (possibly nothing), or nil if the phrase wasn't said.
    /// The last time it was said counts, so "hey display… hey display, set a timer" works.
    func command(in heard: String) -> String? {
        let tokens = heard.split(whereSeparator: \.isWhitespace).map(String.init)
        let plain = tokens.map(Self.plain)
        guard plain.count >= words.count else { return nil }
        for start in stride(from: plain.count - words.count, through: 0, by: -1) {
            let matches = words.indices.allSatisfy { offset in
                let heardWord = plain[start + offset]
                return heardWord == words[offset] || (offset == 0 && Self.soundsLike(heardWord, words[offset]))
            }
            if matches {
                return tokens[(start + words.count)...].joined(separator: " ")
                    .trimmingCharacters(in: CharacterSet(charactersIn: " ,.!?;:"))
            }
        }
        return nil
    }

    /// How the recognizer tends to write an opening "hey".
    private static func soundsLike(_ heard: String, _ word: String) -> Bool {
        word == "hey" && ["hay", "hi", "a", "okay", "ok"].contains(heard)
    }

    private static func plain(_ token: Substring) -> String { plain(String(token)) }

    private static func plain(_ token: String) -> String {
        String(token.lowercased().unicodeScalars.filter { CharacterSet.alphanumerics.contains($0) })
    }
}

/// While a timer rings, any of these stops it; no wake phrase needed.
enum StopWords {
    private static let words: Set<String> = ["stop", "cancel", "quiet", "enough", "okay", "ok", "thanks", "thank", "off", "silence"]

    static func heard(in text: String) -> Bool {
        text.lowercased().split { !$0.isLetter }.contains { words.contains(String($0)) }
    }
}
