import Foundation

enum MonitorAPIError: LocalizedError {
    case invalidBaseURL
    case invalidResponse
    case serverStatus(Int)
    case decoding(Error)

    var errorDescription: String? {
        switch self {
        case .invalidBaseURL:
            return String(localized: "The monitor address is not valid.")
        case .invalidResponse:
            return String(localized: "The monitor returned an invalid response.")
        case .serverStatus(let status):
            return String(localized: "The monitor returned HTTP \(status).")
        case .decoding:
            return String(localized: "The monitor data format is not supported.")
        }
    }
}

struct MonitorAPI: Sendable {
    let baseURL: URL
    private let session: URLSession
    private let decoder: JSONDecoder

    init(baseURLString: String, session: URLSession = .shared) throws {
        let trimmed = baseURLString.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let url = URL(string: trimmed), let scheme = url.scheme,
              ["http", "https"].contains(scheme), url.host != nil else {
            throw MonitorAPIError.invalidBaseURL
        }
        baseURL = url
        self.session = session
        decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        decoder.dateDecodingStrategy = .iso8601
    }

    func live() async throws -> LiveResponse {
        try await get("api/live")
    }

    func weather() async throws -> WeatherResponse {
        try await get("api/weather")
    }

    func powerHistory(range: String) async throws -> PowerHistoryResponse {
        try await get("api/power-history", query: [URLQueryItem(name: "range", value: range)])
    }

    func savings(timeZone: String = TimeZone.current.identifier) async throws -> SavingsResponse {
        try await get("api/savings", query: [URLQueryItem(name: "timezone", value: timeZone)])
    }

    private func get<T: Decodable>(_ path: String, query: [URLQueryItem] = []) async throws -> T {
        var url = baseURL.appendingPathComponent(path)
        if !query.isEmpty {
            guard var components = URLComponents(url: url, resolvingAgainstBaseURL: false) else {
                throw MonitorAPIError.invalidBaseURL
            }
            components.queryItems = query
            guard let queryURL = components.url else { throw MonitorAPIError.invalidBaseURL }
            url = queryURL
        }

        var request = URLRequest(url: url)
        request.timeoutInterval = 8
        request.cachePolicy = .reloadIgnoringLocalCacheData
        request.setValue("application/json", forHTTPHeaderField: "Accept")

        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw MonitorAPIError.invalidResponse
        }
        guard (200..<300).contains(http.statusCode) else {
            throw MonitorAPIError.serverStatus(http.statusCode)
        }
        do {
            return try decoder.decode(T.self, from: data)
        } catch {
            throw MonitorAPIError.decoding(error)
        }
    }
}

actor DashboardCacheStore {
    private let fileURL: URL

    init(fileManager: FileManager = .default) {
        let base = fileManager.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? fileManager.temporaryDirectory
        let directory = base.appendingPathComponent("BatteryMonitor", isDirectory: true)
        try? fileManager.createDirectory(at: directory, withIntermediateDirectories: true)
        fileURL = directory.appendingPathComponent("last-known-dashboard.json")
    }

    func load() -> DashboardCache? {
        guard let data = try? Data(contentsOf: fileURL) else { return nil }
        return try? JSONDecoder().decode(DashboardCache.self, from: data)
    }

    func save(_ cache: DashboardCache) {
        guard let data = try? JSONEncoder().encode(cache) else { return }
        try? data.write(to: fileURL, options: .atomic)
    }
}

