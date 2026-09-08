import SwiftUI

struct ErrorView: View {
    let message: String
    let urlString: String
    var onRetry: () -> Void
    var onEditServer: () -> Void

    var body: some View {
        VStack(spacing: 14) {
            Image(systemName: "wifi.exclamationmark")
                .font(.system(size: 46))
                .foregroundStyle(.secondary)
            Text("Can't reach the dashboard")
                .font(.headline)
            Text(urlString)
                .font(.footnote.monospaced())
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
            Text(message)
                .font(.footnote)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
            HStack(spacing: 12) {
                Button("Change server URL", action: onEditServer)
                    .buttonStyle(.borderedProminent)
                Button("Retry", action: onRetry)
                    .buttonStyle(.bordered)
            }
            .padding(.top, 4)
        }
        .padding(28)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color(.systemBackground))
    }
}
