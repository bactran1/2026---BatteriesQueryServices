import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var settings: AppSettings
    @EnvironmentObject private var store: AppStore
    @FocusState private var addressFocused: Bool

    var body: some View {
        Form {
            Section {
                TextField("Monitor address", text: $settings.monitorURL)
                    .textInputAutocapitalization(.never)
                    .keyboardType(.URL)
                    .autocorrectionDisabled()
                    .focused($addressFocused)
                    .submitLabel(.done)
                    .onSubmit { reconnect() }

                Button { reconnect() } label: {
                    Label("Save and connect", systemImage: "network")
                }

                if let message = store.connectionTestMessage {
                    Text(message).font(.caption).foregroundStyle(.secondary)
                }
            } header: {
                Text("Monitor connection")
            } footer: {
                Text("Enter the address of the x86 monitor host, not the Raspberry Pi collector. Example: http://192.168.1.50:8080")
            }

            Section("Updates") {
                Picker("Live refresh", selection: $settings.refreshSeconds) {
                    Text("5 seconds").tag(5.0)
                    Text("10 seconds").tag(10.0)
                    Text("30 seconds").tag(30.0)
                }
            }

            Section("Appearance") {
                Picker("Theme", selection: $settings.appearance) {
                    Text("System").tag(AppSettings.Appearance.system)
                    Text("Light").tag(AppSettings.Appearance.light)
                    Text("Dark").tag(AppSettings.Appearance.dark)
                }
                Picker("Language", selection: $settings.language) {
                    Text("English").tag("en")
                    Text("Tiếng Việt").tag("vi")
                }
            }

            Section("About") {
                LabeledContent("App", value: "Battery Monitor")
                LabeledContent("Platform", value: "iPhone + iPad")
                LabeledContent("Data source", value: "Monitor API")
                if let build = store.live?.buildCommit, !build.isEmpty {
                    LabeledContent("Server build", value: String(build.prefix(8)))
                }
            }
        }
        .navigationTitle("Settings")
    }

    private func reconnect() {
        addressFocused = false
        Task {
            await store.testConnection()
            await store.reconnect()
        }
    }
}
