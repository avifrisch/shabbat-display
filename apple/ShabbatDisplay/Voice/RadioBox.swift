import AVFoundation
import Foundation
import Observation

/// Live radio: finds a station by name in the Radio Browser directory (radio-browser.info, a free
/// community index) and plays its stream.
@MainActor
@Observable
final class RadioBox {
    /// The station on now, or nil.
    private(set) var station: String?
    private(set) var playing = false

    @ObservationIgnored private var player: AVPlayer?
    @ObservationIgnored private var heldForSpeech = false

    struct Station: Equatable {
        let name: String
        let stream: URL
    }

    /// The best match in the directory's answer: the most-listened station whose stream has an address.
    static func pick(from data: Data) -> Station? {
        guard let list = try? JSONSerialization.jsonObject(with: data) as? [[String: Any]] else { return nil }
        for entry in list {
            let address = (entry["url_resolved"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? entry["url"] as? String ?? ""
            if let name = entry["name"] as? String, let stream = URL(string: address), ["http", "https"].contains(stream.scheme ?? "") {
                return Station(name: name.trimmingCharacters(in: .whitespacesAndNewlines), stream: stream)
            }
        }
        return nil
    }

    static func search(_ name: String) -> URL {
        var parts = URLComponents(string: "https://all.api.radio-browser.info/json/stations/search")!
        parts.queryItems = [URLQueryItem(name: "name", value: name), URLQueryItem(name: "limit", value: "5"),
                            URLQueryItem(name: "order", value: "clickcount"), URLQueryItem(name: "reverse", value: "true"),
                            URLQueryItem(name: "hidebroken", value: "true")]
        return parts.url!
    }

    /// Returns false when no such station was found.
    func play(_ name: String) async -> Bool {
        var request = URLRequest(url: Self.search(name), timeoutInterval: 12)
        request.setValue("ShabbatDisplay/1.0 (personal home display)", forHTTPHeaderField: "User-Agent")
        guard let (data, _) = try? await URLSession.shared.data(for: request), let found = Self.pick(from: data) else { return false }
        stop()
        let player = AVPlayer(url: found.stream)
        self.player = player
        station = found.name
        playing = true
        player.play()
        return true
    }

    func control(_ command: String) {
        guard let player else { return }
        heldForSpeech = false
        switch command {
        case "pause": player.pause(); playing = false
        case "resume": player.play(); playing = true
        case "stop": stop()
        default: break
        }
    }

    func stop() {
        player?.pause()
        player = nil
        station = nil
        playing = false
        heldForSpeech = false
    }

    func holdForSpeech() {
        guard playing else { return }
        player?.pause()
        playing = false
        heldForSpeech = true
    }

    func carryOn() {
        guard heldForSpeech else { return }
        heldForSpeech = false
        player?.play()
        playing = true
    }
}
