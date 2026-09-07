import SwiftUI
import WebKit

/// Full-screen WKWebView that renders the live dashboard exactly as the browser
/// does (same HTML/CSS/JS/WebGL). Adds pull-to-refresh and load state reporting.
struct WebView: UIViewRepresentable {
    let url: URL?
    let reloadToken: UUID
    @Binding var isLoading: Bool
    @Binding var loadError: String?

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    func makeUIView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.allowsInlineMediaPlayback = true
        configuration.mediaTypesRequiringUserActionForPlayback = []
        configuration.websiteDataStore = .default() // persist localStorage (theme/language)

        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = context.coordinator
        webView.allowsBackForwardNavigationGestures = false
        webView.scrollView.contentInsetAdjustmentBehavior = .never
        webView.isOpaque = false
        webView.backgroundColor = .clear

        let refresh = UIRefreshControl()
        refresh.addTarget(
            context.coordinator,
            action: #selector(Coordinator.handleRefresh(_:)),
            for: .valueChanged
        )
        webView.scrollView.refreshControl = refresh

        context.coordinator.webView = webView
        context.coordinator.load(url)
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {
        context.coordinator.parent = self
        if context.coordinator.reloadToken != reloadToken {
            context.coordinator.reloadToken = reloadToken
            context.coordinator.load(url)
        }
    }

    final class Coordinator: NSObject, WKNavigationDelegate {
        var parent: WebView
        weak var webView: WKWebView?
        var reloadToken: UUID

        init(_ parent: WebView) {
            self.parent = parent
            self.reloadToken = parent.reloadToken
        }

        func load(_ url: URL?) {
            guard let url, let webView else {
                // Deferred: load() runs during makeUIView/updateUIView, and
                // mutating SwiftUI state synchronously there is disallowed.
                setState(loading: false, error: "Invalid server address.")
                return
            }
            setState(loading: true, error: nil)
            webView.load(URLRequest(
                url: url,
                cachePolicy: .reloadIgnoringLocalCacheData,
                timeoutInterval: 30
            ))
        }

        private func setState(loading: Bool, error: String?) {
            DispatchQueue.main.async {
                self.parent.isLoading = loading
                self.parent.loadError = error
            }
        }

        @objc func handleRefresh(_ sender: UIRefreshControl) {
            webView?.reload()
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            parent.isLoading = false
            webView.scrollView.refreshControl?.endRefreshing()
        }

        func webView(
            _ webView: WKWebView,
            didFail navigation: WKNavigation!,
            withError error: Error
        ) {
            finish(with: error, webView)
        }

        func webView(
            _ webView: WKWebView,
            didFailProvisionalNavigation navigation: WKNavigation!,
            withError error: Error
        ) {
            finish(with: error, webView)
        }

        private func finish(with error: Error, _ webView: WKWebView) {
            parent.isLoading = false
            webView.scrollView.refreshControl?.endRefreshing()
            let nsError = error as NSError
            if nsError.code == NSURLErrorCancelled { return } // superseded by a newer load
            parent.loadError = nsError.localizedDescription
        }
    }
}
