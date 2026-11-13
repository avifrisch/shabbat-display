import Foundation
import HomeKit
import Observation

/// Apple Home: what is in the house, and changing it.
///
/// It never unlocks a door or opens a garage, and refuses a scene that would.
@MainActor
@Observable
final class HomeBox: NSObject, HMHomeManagerDelegate {
    /// The Home has been read at least once.
    private(set) var ready = false

    @ObservationIgnored private var manager: HMHomeManager?
    @ObservationIgnored private var lastRead = Date.distantPast

    enum Trouble: Error {
        case notReady, noSuchDevice(String), cantDoThat(String), noSuchScene(String), unsafeScene(String), failed(String)

        var sentence: String {
            switch self {
            case .notReady: "I can't see the Home yet. This iPad's Apple ID may not be a member of it."
            case .noSuchDevice(let name): "I couldn't find \(name) in the Home."
            case .cantDoThat(let name): "\(name) can't do that."
            case .noSuchScene(let name): "I couldn't find the scene \(name)."
            case .unsafeScene(let name): "\(name) unlocks or opens a door, so run it from the Home app."
            case .failed(let name): "\(name) didn't respond."
            }
        }
    }

    /// Asks iPadOS for the Home (the first time, with its permission question).
    func start() {
        guard manager == nil else { return }
        let manager = HMHomeManager()
        manager.delegate = self
        self.manager = manager
    }

    func stop() {
        manager?.delegate = nil
        manager = nil
        ready = false
    }

    nonisolated func homeManagerDidUpdateHomes(_ manager: HMHomeManager) {
        Task { @MainActor in
            self.ready = true
            self.readValues(force: true)
            #if DEBUG
            print("HOME homes: \(self.manager?.homes.count ?? 0), devices: \(self.devices.count), scenes: \(self.home?.actionSets.count ?? 0)")
            #endif
        }
    }

    private var home: HMHome? {
        guard let homes = manager?.homes else { return nil }
        return homes.first(where: \.isPrimary) ?? homes.first
    }

    // MARK: - What is there

    private struct Device {
        let name: String
        let room: String
        let kind: String
        let service: HMService
    }

    private static let kinds: [String: String] = [
        HMServiceTypeLightbulb: "light", HMServiceTypeSwitch: "switch", HMServiceTypeOutlet: "plug",
        HMServiceTypeFan: "fan", HMServiceTypeThermostat: "thermostat", HMServiceTypeWindowCovering: "shade",
        HMServiceTypeLockMechanism: "lock", HMServiceTypeGarageDoorOpener: "garage door",
        HMServiceTypeTemperatureSensor: "sensor",
    ]

    private var devices: [Device] {
        guard let home else { return [] }
        var found: [Device] = []
        for accessory in home.accessories {
            let services = accessory.services.filter { Self.kinds[$0.serviceType] != nil }
            for service in services {
                // One thing in the accessory goes by the accessory's name; several go by their own.
                let name = services.count == 1 ? accessory.name : service.name
                found.append(Device(name: name, room: accessory.room?.name ?? "", kind: Self.kinds[service.serviceType]!, service: service))
            }
        }
        return found
    }

    /// For the assistant: every device with its state, and the scenes. Nil until the Home has been read.
    var report: [String: Any]? {
        guard ready, let home else { return nil }
        return [
            "devices": devices.map { ["name": $0.name, "room": $0.room, "kind": $0.kind, "state": Self.state(of: $0)] },
            "scenes": home.actionSets.map(\.name),
        ]
    }

    private static func value(_ service: HMService, _ type: String) -> Any? {
        service.characteristics.first { $0.characteristicType == type }?.value
    }

    private static func number(_ service: HMService, _ type: String) -> Double? {
        (value(service, type) as? NSNumber)?.doubleValue
    }

    private static func state(of device: Device) -> String {
        let service = device.service
        switch device.kind {
        case "light":
            guard let on = number(service, HMCharacteristicTypePowerState) else { return "" }
            if on == 0 { return "off" }
            return number(service, HMCharacteristicTypeBrightness).map { "on, \(Int($0))%" } ?? "on"
        case "switch", "plug", "fan":
            return number(service, HMCharacteristicTypePowerState).map { $0 == 0 ? "off" : "on" } ?? ""
        case "thermostat":
            let now = number(service, HMCharacteristicTypeCurrentTemperature).map { "\(HomeMath.fahrenheit($0)) F" }
            let target = number(service, HMCharacteristicTypeTargetTemperature).map { "set to \(HomeMath.fahrenheit($0))" }
            return [now, target].compactMap { $0 }.joined(separator: ", ")
        case "sensor":
            return number(service, HMCharacteristicTypeCurrentTemperature).map { "\(HomeMath.fahrenheit($0)) F" } ?? ""
        case "shade":
            return number(service, HMCharacteristicTypeCurrentPosition).map { "\(Int($0))% open" } ?? ""
        case "lock":
            return number(service, HMCharacteristicTypeCurrentLockMechanismState).map { $0 == 1 ? "locked" : $0 == 0 ? "unlocked" : "unknown" } ?? ""
        case "garage door":
            return number(service, HMCharacteristicTypeCurrentDoorState).map { ["open", "closed", "opening", "closing"][safe: Int($0)] ?? "stopped" } ?? ""
        default:
            return ""
        }
    }

    private static let watched = [
        HMCharacteristicTypePowerState, HMCharacteristicTypeBrightness, HMCharacteristicTypeCurrentTemperature,
        HMCharacteristicTypeTargetTemperature, HMCharacteristicTypeCurrentPosition,
        HMCharacteristicTypeCurrentLockMechanismState, HMCharacteristicTypeCurrentDoorState,
    ]

    /// Asks the devices for their current state, at most once a minute.
    func readValues(force: Bool = false) {
        guard ready, force || Date().timeIntervalSince(lastRead) > 60 else { return }
        lastRead = Date()
        for device in devices {
            for characteristic in device.service.characteristics
            where Self.watched.contains(characteristic.characteristicType)
                && characteristic.properties.contains(HMCharacteristicPropertyReadable) {
                characteristic.readValue { _ in }
            }
        }
    }

    // MARK: - Changing things

    func set(device name: String, room: String, action: String, value: Int?) async throws {
        guard ready else { throw Trouble.notReady }
        let matches = devices.filter {
            $0.name.caseInsensitiveCompare(name) == .orderedSame && (room.isEmpty || $0.room.caseInsensitiveCompare(room) == .orderedSame)
        }
        guard let device = matches.first else { throw Trouble.noSuchDevice(name) }
        let service = device.service
        func write(_ type: String, _ newValue: Any) async throws {
            guard let characteristic = service.characteristics.first(where: { $0.characteristicType == type }),
                  characteristic.properties.contains(HMCharacteristicPropertyWritable) else { throw Trouble.cantDoThat(name) }
            do { try await characteristic.writeValue(newValue) } catch { throw Trouble.failed(name) }
        }
        switch (action, device.kind) {
        case ("on", "light"), ("on", "switch"), ("on", "plug"), ("on", "fan"):
            try await write(HMCharacteristicTypePowerState, true)
        case ("off", "light"), ("off", "switch"), ("off", "plug"), ("off", "fan"):
            try await write(HMCharacteristicTypePowerState, false)
        case ("brightness", "light"):
            guard let value else { throw Trouble.cantDoThat(name) }
            if value > 0 { try await write(HMCharacteristicTypePowerState, true) }
            try await write(HMCharacteristicTypeBrightness, min(100, max(0, value)))
        case ("temperature", "thermostat"):
            guard let value else { throw Trouble.cantDoThat(name) }
            try await write(HMCharacteristicTypeTargetTemperature, HomeMath.celsius(value))
        case ("position", "shade"):
            guard let value else { throw Trouble.cantDoThat(name) }
            try await write(HMCharacteristicTypeTargetPosition, min(100, max(0, value)))
        case ("lock", "lock"):
            // 1 is "secured". The app never writes 0.
            try await write(HMCharacteristicTypeTargetLockMechanismState, 1)
        case ("close", "garage door"):
            // 1 is "closed". The app never writes 0.
            try await write(HMCharacteristicTypeTargetDoorState, 1)
        default:
            throw Trouble.cantDoThat(name)
        }
        readValues(force: true)
    }

    func run(scene name: String) async throws {
        guard ready, let home else { throw Trouble.notReady }
        guard let scene = home.actionSets.first(where: { $0.name.caseInsensitiveCompare(name) == .orderedSame }) else {
            throw Trouble.noSuchScene(name)
        }
        for action in scene.actions {
            guard let write = action as? HMCharacteristicWriteAction<NSCopying> else { continue }
            let target = (write.targetValue as? NSNumber)?.intValue
            if HomeMath.opensADoor(characteristicType: write.characteristic.characteristicType, value: target) {
                throw Trouble.unsafeScene(scene.name)
            }
        }
        do { try await home.executeActionSet(scene) } catch { throw Trouble.failed(scene.name) }
        readValues(force: true)
    }
}

/// The arithmetic and the door rule, apart from HomeKit so they can be tested.
enum HomeMath {
    static func fahrenheit(_ celsius: Double) -> Int { Int((celsius * 9 / 5 + 32).rounded()) }

    /// Thermostats take half degrees Celsius.
    static func celsius(_ fahrenheit: Int) -> Double { ((Double(fahrenheit) - 32) * 5 / 9 * 2).rounded() / 2 }

    /// Whether writing this value would unlock a lock or open a garage door.
    static func opensADoor(characteristicType: String, value: Int?) -> Bool {
        (characteristicType == HMCharacteristicTypeTargetLockMechanismState || characteristicType == HMCharacteristicTypeTargetDoorState) && value != 1
    }
}

private extension Array {
    subscript(safe index: Int) -> Element? { indices.contains(index) ? self[index] : nil }
}
