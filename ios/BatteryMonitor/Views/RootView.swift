import SwiftUI

enum AppSection: String, CaseIterable, Identifiable {
    case home
    case batteries
    case history
    case savings
    case settings

    var id: String { rawValue }
    var title: LocalizedStringKey {
        switch self {
        case .home: "Home"
        case .batteries: "Batteries"
        case .history: "History"
        case .savings: "Savings"
        case .settings: "Settings"
        }
    }
    var icon: String {
        switch self {
        case .home: "house.fill"
        case .batteries: "battery.100percent"
        case .history: "chart.xyaxis.line"
        case .savings: "dollarsign.circle.fill"
        case .settings: "gearshape.fill"
        }
    }
}

struct RootView: View {
    @EnvironmentObject private var store: AppStore
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass
    @State private var tabSelection: AppSection = .home
    @State private var sidebarSelection: AppSection? = .home

    var body: some View {
        Group {
            if horizontalSizeClass == .regular {
                NavigationSplitView {
                    List(selection: $sidebarSelection) {
                        ForEach(AppSection.allCases) { section in
                            Label(section.title, systemImage: section.icon)
                                .tag(section)
                        }
                    }
                    .navigationTitle("Battery Monitor")
                } detail: {
                    NavigationStack { destination(sidebarSelection ?? .home) }
                }
            } else {
                TabView(selection: $tabSelection) {
                    ForEach(AppSection.allCases) { section in
                        NavigationStack { destination(section) }
                            .tabItem { Label(section.title, systemImage: section.icon) }
                            .tag(section)
                    }
                }
            }
        }
        .task(id: scenePhase) {
            guard scenePhase == .active else { return }
            await store.runRefreshLoop()
        }
    }

    @ViewBuilder
    private func destination(_ section: AppSection) -> some View {
        switch section {
        case .home: DashboardView()
        case .batteries: BatteriesView()
        case .history: HistoryView()
        case .savings: SavingsView()
        case .settings: SettingsView()
        }
    }
}
