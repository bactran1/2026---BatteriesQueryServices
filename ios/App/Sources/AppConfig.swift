import Foundation

/// Where the dashboard lives. Defaults to the `MonitorBaseURL` bundled in
/// Info.plist and can be changed at runtime from the in-app Settings sheet.
enum AppConfig {
    private static let baseURLKey = "monitor_base_url"

    static var defaultURLString: String {
        (Bundle.main.object(forInfoDictionaryKey: "MonitorBaseURL") as? String)
            ?? "http://raspberrypi.local:8080"
    }

    static var baseURLString: String {
        get { UserDefaults.standard.string(forKey: baseURLKey) ?? defaultURLString }
        set { UserDefaults.standard.set(normalized(newValue), forKey: baseURLKey) }
    }

    static var baseURL: URL? { URL(string: normalized(baseURLString)) }

    /// Accept casual input ("pi.local:8080") and turn it into a valid URL.
    static func normalized(_ raw: String) -> String {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty { return defaultURLString }
        return trimmed.contains("://") ? trimmed : "http://\(trimmed)"
    }
}
