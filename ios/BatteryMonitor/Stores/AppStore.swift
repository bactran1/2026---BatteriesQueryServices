import Combine
import Foundation

@MainActor
final class AppStore: ObservableObject {
    @Published private(set) var live: LiveResponse?
    @Published private(set) var weather: WeatherResponse?
    @Published private(set) var savings: SavingsResponse?
    @Published private(set) var history: PowerHistoryResponse?
    @Published private(set) var isRefreshing = false
    @Published private(set) var isUsingCachedData = false
    @Published private(set) var lastUpdated: Date?
    @Published private(set) var errorMessage: String?
    @Published private(set) var connectionTestMessage: String?

    let settings: AppSettings
    private let cache = DashboardCacheStore()
    private var loadedCache = false
    private var lastSecondaryRefresh: Date?

    init(settings: AppSettings) {
        self.settings = settings
    }

    var batteries: [BatterySnapshot] { live?.snapshot.batteries ?? [] }

    func battery(for inventory: BatteryInventory) -> BatterySnapshot? {
        batteries.first { $0.id == inventory.id || ($0.address != nil && $0.address == inventory.address) }
    }

    func runRefreshLoop() async {
        await loadCacheIfNeeded()
        await refreshAll()
        while !Task.isCancelled {
            do {
                try await Task.sleep(for: .seconds(settings.refreshSeconds))
            } catch {
                return
            }
            await refreshLive()
            if lastSecondaryRefresh.map({ Date().timeIntervalSince($0) >= 600 }) ?? true {
                await refreshSecondary()
            }
        }
    }

    func refreshAll() async {
        guard !isRefreshing else { return }
        isRefreshing = true
        defer { isRefreshing = false }
        await refreshLive()
        await refreshSecondary()
    }

    func refreshLive() async {
        do {
            let api = try MonitorAPI(baseURLString: settings.resolvedMonitorURL)
            live = try await api.live()
            lastUpdated = Date()
            isUsingCachedData = false
            errorMessage = nil
            await persistCache()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func refreshSecondary() async {
        do {
            let api = try MonitorAPI(baseURLString: settings.resolvedMonitorURL)
            async let nextWeather = api.weather()
            async let nextSavings = api.savings()
            let (weatherValue, savingsValue) = try await (nextWeather, nextSavings)
            weather = weatherValue
            savings = savingsValue
            lastSecondaryRefresh = Date()
            await persistCache()
        } catch {
            if live == nil { errorMessage = error.localizedDescription }
        }
    }

    func refreshHistory(range: String) async {
        do {
            let api = try MonitorAPI(baseURLString: settings.resolvedMonitorURL)
            history = try await api.powerHistory(range: range)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func testConnection() async {
        connectionTestMessage = L10n.text("Testing...", language: settings.language)
        do {
            let api = try MonitorAPI(baseURLString: settings.resolvedMonitorURL)
            let response = try await api.live()
            connectionTestMessage = String(
                format: L10n.text("Connected to %@", language: settings.language),
                response.rack.name
            )
        } catch {
            connectionTestMessage = error.localizedDescription
        }
    }

    func reconnect() async {
        errorMessage = nil
        lastSecondaryRefresh = nil
        await refreshAll()
    }

    private func loadCacheIfNeeded() async {
        guard !loadedCache else { return }
        loadedCache = true
        guard let saved = await cache.load() else { return }
        live = saved.live
        weather = saved.weather
        savings = saved.savings
        lastUpdated = saved.savedAt
        isUsingCachedData = saved.live != nil
    }

    private func persistCache() async {
        await cache.save(DashboardCache(
            savedAt: lastUpdated ?? Date(),
            live: live,
            weather: weather,
            savings: savings
        ))
    }
}
