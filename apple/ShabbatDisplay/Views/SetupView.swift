import SwiftUI

/// Where the display server is and what this screen is called.
struct SetupView: View {
    @Environment(AppModel.self) private var model
    @Environment(VoiceController.self) private var voice
    @Environment(\.dismiss) private var dismiss
    @State private var address = ""
    @State private var screen = ""
    @State private var voiceOn = false
    @State private var wakePhrase = ""
    @State private var checking = false
    @State private var problem: String?

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("192.168.4.109", text: $address)
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                } header: {
                    Text("Display computer")
                } footer: {
                    Text("The address of the computer that runs the Shabbat Display: the same one you would open in Safari. Port 8765 is assumed.")
                }
                Section {
                    TextField("iPad", text: $screen)
                        .autocorrectionDisabled()
                } header: {
                    Text("This screen's name")
                } footer: {
                    Text("The Display Manager lists this screen under this name, so it can have its own rotation.")
                }
                Section {
                    Toggle("Listen for requests", isOn: $voiceOn)
                    if voiceOn {
                        LabeledContent("Wake phrase") {
                            TextField(WakePhrase.standard, text: $wakePhrase)
                                .multilineTextAlignment(.trailing)
                                .textInputAutocapitalization(.never)
                                .autocorrectionDisabled()
                        }
                    }
                } header: {
                    Text("Voice")
                } footer: {
                    VStack(alignment: .leading, spacing: 6) {
                        Text("Say the wake phrase, then a request: a timer, the shopping list, a question. The microphone is off from candle lighting to havdalah, and whenever the calendar can't be read.")
                        if voiceOn && !voice.recognizesOnDevice {
                            Text("This iPad can't recognize speech by itself, so what it hears after a sound is sent to Apple to be turned into words.")
                        }
                        if let trouble = voice.problem {
                            Text(trouble).foregroundStyle(.red)
                        }
                    }
                }
                if let problem {
                    Section { Text(problem).foregroundStyle(.red) }
                }
            }
            .navigationTitle("Shabbat Display")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                if model.server != nil {
                    ToolbarItem(placement: .cancellationAction) {
                        Button("Cancel") { dismiss() }
                    }
                }
                ToolbarItem(placement: .confirmationAction) {
                    if checking {
                        ProgressView()
                    } else {
                        Button("Connect") { Task { await connect() } }
                            .disabled(address.trimmingCharacters(in: .whitespaces).isEmpty)
                    }
                }
            }
            .onChange(of: address) { problem = nil }
            .onChange(of: screen) { problem = nil }
            .onAppear {
                address = model.server?.display ?? ""
                screen = model.screen
                voiceOn = voice.voiceOn
                wakePhrase = voice.wakePhrase
            }
        }
        .interactiveDismissDisabled(model.server == nil)
    }

    private func connect() async {
        let name = screen.trimmingCharacters(in: .whitespaces)
        guard let server = ServerAddress(address) else {
            problem = "That doesn't look like an address. Try something like 192.168.4.109."
            return
        }
        let phrase = wakePhrase.trimmingCharacters(in: .whitespaces)
        guard phrase.isEmpty || WakePhrase(phrase) != nil else {
            problem = "A wake phrase is one to four words, such as \"hey display\"."
            return
        }
        guard validScreenName(name.isEmpty ? "iPad" : name) else {
            problem = "A screen name can have letters, digits, spaces and . _ ' - and up to 40 characters."
            return
        }
        checking = true
        defer { checking = false }
        guard await AppModel.answers(server.health) else {
            problem = "The display isn't answering at \(server.display). Check that the computer is on, that this iPad is on the home Wi-Fi, and that the iPad was allowed to find devices on the local network (Settings → Shabbat Display)."
            return
        }
        model.save(server: server, screen: name.isEmpty ? "iPad" : name)
        await voice.save(voiceOn: voiceOn, wakePhrase: phrase.isEmpty ? WakePhrase.standard : phrase)
        // A refused microphone stays on screen; everything else is done.
        if voiceOn && !voice.voiceOn {
            voiceOn = false
            return
        }
        dismiss()
    }
}
