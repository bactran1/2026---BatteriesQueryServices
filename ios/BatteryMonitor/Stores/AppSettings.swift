import SwiftUI

@MainActor
final class AppSettings: ObservableObject {
    enum Appearance: String, CaseIterable, Identifiable {
        case system
        case light
        case dark

        var id: String { rawValue }
        var colorScheme: ColorScheme? {
            switch self {
            case .system: nil
            case .light: .light
            case .dark: .dark
            }
        }
    }

    private enum Key {
        static let monitorURL = "monitorURL"
        static let refreshSeconds = "refreshSeconds"
        static let appearance = "appearance"
        static let language = "language"
    }

    @Published var monitorURL: String {
        didSet {
            defaults.set(monitorURL, forKey: Key.monitorURL)
            AppConfig.baseURLString = monitorURL
        }
    }
    @Published var refreshSeconds: Double {
        didSet { defaults.set(refreshSeconds, forKey: Key.refreshSeconds) }
    }
    @Published var appearance: Appearance {
        didSet { defaults.set(appearance.rawValue, forKey: Key.appearance) }
    }
    @Published var language: String {
        didSet { defaults.set(language, forKey: Key.language) }
    }

    private let defaults: UserDefaults

    var resolvedMonitorURL: String { AppConfig.normalized(monitorURL) }

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        monitorURL = defaults.string(forKey: Key.monitorURL) ?? AppConfig.baseURLString
        let savedRefresh = defaults.double(forKey: Key.refreshSeconds)
        refreshSeconds = savedRefresh > 0 ? savedRefresh : 5
        appearance = Appearance(rawValue: defaults.string(forKey: Key.appearance) ?? "") ?? .system
        language = defaults.string(forKey: Key.language) ?? "en"
        AppConfig.baseURLString = monitorURL
    }
}
