import SwiftUI
import WebKit

/// The display page from the server, full screen.
struct DisplayWebView: UIViewRepresentable {
    let url: URL
    let reloadToken: Int
    /// The page finished loading (true) or failed or was lost (false).
    let loaded: (Bool) -> Void
    /// The page asked for a new window (the shul bulletin).
    let opened: (URL) -> Void

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.allowsInlineMediaPlayback = true
        let view = WKWebView(frame: .zero, configuration: config)
        view.navigationDelegate = context.coordinator
        view.uiDelegate = context.coordinator
        view.isOpaque = false
        view.backgroundColor = UIColor(Theme.background)
        view.scrollView.backgroundColor = UIColor(Theme.background)
        view.scrollView.isScrollEnabled = false
        view.scrollView.bounces = false
        view.scrollView.contentInsetAdjustmentBehavior = .never
        view.scrollView.pinchGestureRecognizer?.isEnabled = false
        view.allowsLinkPreview = false
        context.coordinator.load(url, token: reloadToken, in: view)
        return view
    }

    func updateUIView(_ view: WKWebView, context: Context) {
        context.coordinator.parent = self
        context.coordinator.load(url, token: reloadToken, in: view)
    }

    final class Coordinator: NSObject, WKNavigationDelegate, WKUIDelegate {
        var parent: DisplayWebView
        private var shown: (URL, Int)?

        init(_ parent: DisplayWebView) { self.parent = parent }

        func load(_ url: URL, token: Int, in view: WKWebView) {
            if let shown, shown == (url, token) { return }
            shown = (url, token)
            view.load(URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 15))
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            parent.loaded(true)
        }

        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
            parent.loaded(false)
        }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
            parent.loaded(false)
        }

        /// An old iPad drops the page's process when memory runs short; the model loads it again.
        func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
            parent.loaded(false)
        }

        /// The page stays on the display server; anything else is refused.
        func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction) async -> WKNavigationActionPolicy {
            guard let target = action.request.url else { return .cancel }
            if target.scheme == "about" { return .allow }
            guard target.host == parent.url.host, target.port == parent.url.port else { return .cancel }
            if action.targetFrame?.isMainFrame == true, target.path != "/", target.path != "/index.html" {
                parent.opened(target)
                return .cancel
            }
            return .allow
        }

        /// `target="_blank"` (Open the bulletin): shown over the display instead of in Safari.
        func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                     for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
            if let target = action.request.url, target.host == parent.url.host, target.port == parent.url.port {
                parent.opened(target)
            }
            return nil
        }
    }
}

/// A file from the display server (the bulletin PDF), with a way back. Closes itself after 5 minutes.
struct LinkView: View {
    let url: URL
    let close: () -> Void

    var body: some View {
        ZStack(alignment: .topTrailing) {
            FileWebView(url: url).ignoresSafeArea()
            Button(action: close) {
                Label("Back to the display", systemImage: "xmark")
                    .font(.title3.weight(.semibold))
                    .padding(.horizontal, 18)
                    .padding(.vertical, 12)
                    .background(.ultraThickMaterial, in: Capsule())
            }
            .padding(20)
        }
        .task {
            try? await Task.sleep(for: .seconds(300))
            if !Task.isCancelled { close() }
        }
    }
}

private struct FileWebView: UIViewRepresentable {
    let url: URL

    func makeUIView(context: Context) -> WKWebView {
        let view = WKWebView()
        view.load(URLRequest(url: url))
        return view
    }

    func updateUIView(_ view: WKWebView, context: Context) {}
}
