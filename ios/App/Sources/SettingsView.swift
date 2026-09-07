import SwiftUI

struct SettingsView: View {
    @Binding var urlString: String
    var onSave: () -> Void
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("http://raspberrypi.local:8080", text: $urlString)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled(true)
                        .keyboardType(.URL)
                        .submitLabel(.done)
                        .onSubmit(save)
                } header: {
                    Text("Monitor server")
                } footer: {
                    Text("The address of the Battery Monitor server on your network.")
                }

                Section {
                    Button("Reset to default") {
                        urlString = AppConfig.defaultURLString
                    }
                }
            }
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save", action: save)
                }
            }
        }
    }

    private func save() {
        onSave()
        dismiss()
    }
}
