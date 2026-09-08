import Foundation

/// Server address shared by the app and the widget. Stored in an App Group so a
/// change in the app's Settings is picked up by the widget; falls back to
/// `.standard` (and the default constant) when the group is unavailable.
enum AppConfig {
    static let appGroup = "group.com.trant.batterymonitor"
    static let defaultURLString = "http://192.168.1.114:8080"

    private static let baseURLKey = "monitor_base_url"
    private static var defaults: UserDefaults {
        UserDefaults(suiteName: appGroup) ?? .standard
    }

    static var baseURLString: String {
        get { defaults.string(forKey: baseURLKey) ?? defaultURLString }
        set { defaults.set(normalized(newValue), forKey: baseURLKey) }
    }

    static var baseURL: URL? { URL(string: normalized(baseURLString)) }

    /// Accept casual input ("192.168.1.114:8080") and turn it into a valid URL.
    static func normalized(_ raw: String) -> String {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty { return defaultURLString }
        return trimmed.contains("://") ? trimmed : "http://\(trimmed)"
    }
}
