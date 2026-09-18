import SwiftUI

@main
@MainActor
struct BatteryMonitorApp: App {
    @StateObject private var settings: AppSettings
    @StateObject private var store: AppStore

    init() {
        let settings = AppSettings()
        _settings = StateObject(wrappedValue: settings)
        _store = StateObject(wrappedValue: AppStore(settings: settings))
    }

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(settings)
                .environmentObject(store)
                .environment(\.locale, Locale(identifier: settings.language))
                .preferredColorScheme(settings.appearance.colorScheme)
                .tint(.brandOrange)
        }
    }
}
