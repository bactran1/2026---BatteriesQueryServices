import SwiftUI

struct SettingsView: View {
    @Binding var urlString: String
    var onSave: () -> Void

    @Environment(\.dismiss) private var dismiss
    // Edit a local draft so the field is always freely editable and Cancel
    // reverts; the bound value is only written on Save.
    @State private var draft = ""
    @FocusState private var focused: Bool

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    HStack {
                        TextField("http://192.168.1.114:8080", text: $draft)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled(true)
                            .keyboardType(.URL)
                            .focused($focused)
                            .submitLabel(.go)
                            .onSubmit(commit)
                        if !draft.isEmpty {
                            Button {
                                draft = ""
                                focused = true
                            } label: {
                                Image(systemName: "xmark.circle.fill")
                                    .foregroundStyle(.secondary)
                            }
                            .buttonStyle(.plain)
                            .accessibilityLabel("Clear address")
                        }
                    }
                } header: {
                    Text("Monitor server")
                } footer: {
                    Text("The address of the Battery Monitor server on your network, e.g. http://192.168.1.114:8080")
                }

                Section {
                    Button("Use default (\(AppConfig.defaultURLString))") {
                        draft = AppConfig.defaultURLString
                        focused = true
                    }
                }
            }
            .navigationTitle("Server URL")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save", action: commit).bold()
                }
            }
            .onAppear {
                draft = urlString
                focused = true
            }
        }
    }

    private func commit() {
        urlString = draft
        onSave()
        dismiss()
    }
}
