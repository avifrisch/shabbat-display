import Foundation
import MusicKit
import Observation

/// Apple Music on the display: finds what was asked for and plays it.
@MainActor
@Observable
final class MusicBox {
    /// "Come Together - The Beatles", or nil when nothing is queued.
    private(set) var title: String?
    private(set) var playing = false

    private let player = ApplicationMusicPlayer.shared
    private var pausedForSpeech = false

    enum Trouble: Error {
        case notAllowed, noSubscription, notFound, failed

        /// What the display says.
        var sentence: String {
            switch self {
            case .notAllowed: "I'm not allowed to use Apple Music. Turn it on for Shabbat Display in the iPad's Settings."
            case .noSubscription: "This iPad isn't signed in to an Apple Music subscription."
            case .notFound: "I couldn't find that on Apple Music."
            case .failed: "Apple Music didn't answer. This app may still need MusicKit switched on in the developer account."
            }
        }
    }

    /// For the assistant: what is on now.
    var report: [String: Any] { ["playing": playing, "title": title ?? ""] }

    /// Reads the player's state; called once a second.
    func look() {
        let status = player.state.playbackStatus
        playing = status == .playing
        if let entry = player.queue.currentEntry, status != .stopped {
            title = [entry.title, entry.subtitle].compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: " - ")
        } else {
            title = nil
        }
    }

    func play(query: String, kind: String) async throws {
        guard await MusicAuthorization.request() == .authorized else { throw Trouble.notAllowed }
        do {
            guard try await MusicSubscription.current.canPlayCatalogContent else { throw Trouble.noSubscription }
            try await queue(query: query, kind: kind)
            try await player.play()
        } catch let trouble as Trouble {
            throw trouble
        } catch {
            throw Trouble.failed
        }
        pausedForSpeech = false
        look()
    }

    private func queue(query: String, kind: String) async throws {
        switch kind {
        case "song":
            var request = MusicCatalogSearchRequest(term: query, types: [Song.self])
            request.limit = 1
            guard let song = try await request.response().songs.first else { throw Trouble.notFound }
            player.queue = [song]
        case "album":
            var request = MusicCatalogSearchRequest(term: query, types: [Album.self])
            request.limit = 1
            guard let album = try await request.response().albums.first else { throw Trouble.notFound }
            player.queue = [album]
        case "playlist":
            var request = MusicCatalogSearchRequest(term: query, types: [Playlist.self])
            request.limit = 1
            guard let playlist = try await request.response().playlists.first else { throw Trouble.notFound }
            player.queue = [playlist]
        case "station":
            var request = MusicCatalogSearchRequest(term: query, types: [Station.self])
            request.limit = 1
            guard let station = try await request.response().stations.first else { throw Trouble.notFound }
            player.queue = [station]
        case "artist":
            var request = MusicCatalogSearchRequest(term: query, types: [Artist.self])
            request.limit = 1
            guard let artist = try await request.response().artists.first else { throw Trouble.notFound }
            try await queue(artist: artist)
        default:
            var request = MusicCatalogSearchRequest(term: query, types: [Song.self, Album.self, Artist.self, Playlist.self, Station.self])
            request.limit = 3
            request.includeTopResults = true
            let response = try await request.response()
            switch response.topResults.first {
            case .song(let song): player.queue = [song]
            case .album(let album): player.queue = [album]
            case .playlist(let playlist): player.queue = [playlist]
            case .station(let station): player.queue = [station]
            case .artist(let artist): try await queue(artist: artist)
            default:
                if let playlist = response.playlists.first { player.queue = [playlist] }
                else if let album = response.albums.first { player.queue = [album] }
                else if let song = response.songs.first { player.queue = [song] }
                else if let station = response.stations.first { player.queue = [station] }
                else { throw Trouble.notFound }
            }
        }
    }

    /// An artist plays as their most-played songs.
    private func queue(artist: Artist) async throws {
        let songs = try await artist.with([.topSongs]).topSongs ?? []
        guard !songs.isEmpty else { throw Trouble.notFound }
        player.queue = ApplicationMusicPlayer.Queue(for: songs)
    }

    func control(_ command: String) async {
        pausedForSpeech = false
        switch command {
        case "pause": player.pause()
        case "resume": try? await player.play()
        case "next": try? await player.skipToNextEntry()
        case "previous": try? await player.skipToPreviousEntry()
        case "stop": stop()
        default: break
        }
        look()
    }

    func stop() {
        pausedForSpeech = false
        guard title != nil || player.state.playbackStatus != .stopped else { return }
        player.stop()
        player.queue = []
        look()
    }

    /// Goes quiet while someone is talking to the display or it is answering…
    func holdForSpeech() {
        look()
        guard playing else { return }
        player.pause()
        pausedForSpeech = true
    }

    /// …and carries on after, unless the request itself changed the music.
    func carryOn() async {
        guard pausedForSpeech else { return }
        pausedForSpeech = false
        try? await player.play()
        look()
    }
}
