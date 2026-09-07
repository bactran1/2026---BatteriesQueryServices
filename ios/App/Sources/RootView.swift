import SwiftUI

struct RootView: View {
    @State private var urlString = AppConfig.baseURLString
    @State private var reloadToken = UUID()
    @State private var showSettings = false
    @State private var isLoading = true
    @State private var loadError: String?

    var body: some View {
        ZStack(alignment: .topTrailing) {
            WebView(
                url: AppConfig.baseURL,
                reloadToken: reloadToken,
                isLoading: $isLoading,
                loadError: $loadError
            )
            .ignoresSafeArea(.container, edges: .bottom)

            if isLoading && loadError == nil {
                ProgressView()
                    .controlSize(.large)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }

            if let loadError {
                ErrorView(
                    message: loadError,
                    urlString: urlString,
                    onRetry: reload,
                    onEditServer: { showSettings = true }
                )
            }

            Button {
                showSettings = true
            } label: {
                Image(systemName: "gearshape.fill")
                    .font(.system(size: 15, weight: .semibold))
                    .padding(10)
                    .background(.ultraThinMaterial, in: Circle())
            }
            .tint(.primary)
            .opacity(0.5)
            .padding(.top, 4)
            .padding(.trailing, 10)
            .accessibilityLabel("Server settings")
        }
        .sheet(isPresented: $showSettings) {
            SettingsView(urlString: $urlString, onSave: saveServer)
        }
    }

    private func reload() {
        loadError = nil
        reloadToken = UUID()
    }

    private func saveServer() {
        AppConfig.baseURLString = urlString
        urlString = AppConfig.baseURLString
        reload()
    }
}
