import Foundation

/// The handful of rack numbers the widget shows, pulled from `/api/live`.
struct MonitorSummary {
    var soc: Double?        // rack average state of charge, %
    var powerW: Double?     // net rack power, W (>0 charging, <0 discharging)
    var online: Int?
    var total: Int?
    var reachable: Bool
    var updated: Date

    static let placeholder = MonitorSummary(
        soc: 92, powerW: -540, online: 3, total: 3, reachable: true, updated: Date()
    )
}

enum MonitorClient {
    static func fetchSummary() async -> MonitorSummary {
        guard let base = AppConfig.baseURL,
              let url = URL(string: "/api/live", relativeTo: base) else {
            return MonitorSummary(reachable: false, updated: Date())
        }
        var request = URLRequest(url: url, timeoutInterval: 12)
        request.cachePolicy = .reloadIgnoringLocalCacheData
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse, http.statusCode == 200,
                  let root = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                return MonitorSummary(reachable: false, updated: Date())
            }
            let summary = root["summary"] as? [String: Any] ?? [:]
            let rack = root["rack"] as? [String: Any] ?? [:]
            func number(_ dict: [String: Any], _ key: String) -> Double? {
                (dict[key] as? NSNumber)?.doubleValue
            }
            return MonitorSummary(
                soc: number(summary, "average_soc_percent"),
                powerW: number(summary, "total_power_w"),
                online: number(summary, "online_count").map { Int($0) }
                    ?? number(rack, "online_battery_count").map { Int($0) },
                total: number(summary, "battery_count").map { Int($0) }
                    ?? number(rack, "expected_battery_count").map { Int($0) },
                reachable: true,
                updated: Date()
            )
        } catch {
            return MonitorSummary(reachable: false, updated: Date())
        }
    }
}
