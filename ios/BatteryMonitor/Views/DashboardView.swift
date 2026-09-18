import SwiftUI

struct DashboardView: View {
    @EnvironmentObject private var store: AppStore
    @Environment(\.locale) private var locale

    private let columns = [GridItem(.adaptive(minimum: 145, maximum: 250), spacing: 10)]

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 16) {
                header

                if let live = store.live {
                    EnergyFlowView(live: live)

                    LazyVGrid(columns: columns, spacing: 10) {
                        MetricTile(
                            title: "Rack SOC",
                            value: ValueFormat.percent(live.summary.averageSocPercent),
                            detail: "\(live.rack.onlineBatteryCount)/\(live.rack.expectedBatteryCount) " + L10n.text("batteries online", locale: locale),
                            icon: "battery.100percent",
                            color: .batteryGreen
                        )
                        MetricTile(
                            title: "Battery power",
                            value: ValueFormat.power(live.summary.totalPowerW),
                            detail: batteryState(live.summary.totalPowerW),
                            icon: "bolt.fill",
                            color: .brandOrange
                        )
                        MetricTile(
                            title: "Capacity",
                            value: capacity(live.summary),
                            detail: L10n.text("Direct battery telemetry", locale: locale),
                            icon: "gauge.with.dots.needle.50percent",
                            color: .cyan
                        )
                        MetricTile(
                            title: "Rack temperature",
                            value: ValueFormat.temperature(live.summary.averageMosfetTemperatureC),
                            detail: maximumTemperature(live.summary.maximumMosfetTemperatureC),
                            icon: "thermometer.medium",
                            color: .pink
                        )
                    }

                    if let weather = store.weather {
                        WeatherPanel(weather: weather)
                    }

                    healthPanel(live)
                } else {
                    EmptyStateView(
                        icon: "network.slash",
                        title: "Connect to your monitor",
                        message: "Set the monitor address in Settings. The iPhone or iPad must be able to reach the monitor host on your local network."
                    )
                    .frame(minHeight: 320)
                }
            }
            .padding()
        }
        .navigationTitle("Home Energy")
        .refreshable { await store.refreshAll() }
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button { Task { await store.refreshAll() } } label: {
                    Image(systemName: "arrow.clockwise")
                }
                .disabled(store.isRefreshing)
                .accessibilityLabel("Refresh")
            }
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(store.live?.rack.name ?? L10n.text("Home energy system", locale: locale))
                        .font(.title2.weight(.bold))
                    if let builder = store.live?.rack.builder, !builder.isEmpty {
                        Text(builder)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                Spacer()
                StatusBadge(status: store.live?.collectorStatus ?? "offline")
            }
            if store.isUsingCachedData {
                Label("Showing the last saved reading", systemImage: "clock.arrow.circlepath")
                    .font(.caption)
                    .foregroundStyle(.orange)
            } else if let date = store.lastUpdated {
                Text(date, style: .relative)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            if let error = store.errorMessage {
                Text(error)
                    .font(.caption)
                    .foregroundStyle(.red)
            }
        }
    }

    private func healthPanel(_ live: LiveResponse) -> some View {
        Panel {
            VStack(alignment: .leading, spacing: 12) {
                Label("System health", systemImage: "heart.text.square.fill")
                    .font(.headline)
                HStack {
                    healthItem("Alarms", value: live.summary.alarmCount ?? 0, color: .orange)
                    Divider()
                    healthItem("Faults", value: live.summary.faultCount ?? 0, color: .red)
                    Divider()
                    healthItem("Cell delta", value: millivolts(live.summary.maximumCellVoltageDeltaV), color: .cyan)
                }
            }
        }
    }

    private func healthItem(_ title: LocalizedStringKey, value: Int, color: Color) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title).font(.caption).foregroundStyle(.secondary)
            Text("\(value)").font(.headline).foregroundStyle(value == 0 ? .primary : color)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func healthItem(_ title: LocalizedStringKey, value: String, color: Color) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title).font(.caption).foregroundStyle(.secondary)
            Text(value).font(.headline).foregroundStyle(color)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func batteryState(_ power: Double?) -> String {
        guard let power else { return L10n.text("Unavailable", locale: locale) }
        if power > 25 { return L10n.text("Charging", locale: locale) }
        if power < -25 { return L10n.text("Discharging", locale: locale) }
        return L10n.text("Standby", locale: locale)
    }

    private func capacity(_ summary: RackSummary) -> String {
        guard let remaining = summary.remainingCapacityAh, let full = summary.fullCapacityAh else { return "--" }
        return String(format: "%.0f / %.0f Ah", remaining, full)
    }

    private func maximumTemperature(_ value: Double?) -> String? {
        guard let value else { return nil }
        return L10n.format("Maximum %.1f°C", locale: locale, value)
    }

    private func millivolts(_ value: Double?) -> String {
        guard let value else { return "--" }
        return String(format: "%.0f mV", value * 1_000)
    }
}

private struct WeatherPanel: View {
    let weather: WeatherResponse
    @Environment(\.locale) private var locale

    var body: some View {
        Panel {
            HStack(spacing: 14) {
                Image(systemName: weatherSymbol)
                    .font(.system(size: 30, weight: .medium))
                    .symbolRenderingMode(.multicolor)
                    .frame(width: 42)
                VStack(alignment: .leading, spacing: 3) {
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Text(ValueFormat.temperature(weather.temperatureC))
                            .font(.title3.weight(.semibold))
                        Text(weatherDescription)
                            .font(.subheadline.weight(.medium))
                    }
                    Text(weatherDetails)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    if let irradiance = weather.solarIrradianceWM2 {
                        Label(String(format: "%.0f W/m²", irradiance), systemImage: "sun.max.fill")
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(.solarYellow)
                    }
                }
                Spacer(minLength: 0)
            }
        }
    }

    private var weatherDetails: String {
        var details: [String] = []
        if let humidity = weather.relativeHumidityPercent { details.append(String(format: "%.0f%% RH", humidity)) }
        if let wind = weather.windSpeedKmh { details.append(String(format: "%.0f km/h", wind)) }
        if let elevation = weather.solarElevationDegrees { details.append(String(format: "%.0f° sun", elevation)) }
        return details.joined(separator: " · ")
    }

    private var weatherSymbol: String {
        switch weather.weatherCode ?? -1 {
        case 0: "sun.max.fill"
        case 1...3: "cloud.sun.fill"
        case 45...48: "cloud.fog.fill"
        case 51...67, 80...82: "cloud.rain.fill"
        case 71...77, 85...86: "cloud.snow.fill"
        case 95...99: "cloud.bolt.rain.fill"
        default: "cloud.fill"
        }
    }

    private var weatherDescription: String {
        let key: String
        switch weather.weatherCode ?? -1 {
        case 0: key = "Clear sky"
        case 1...3: key = "Partly cloudy"
        case 45...48: key = "Fog"
        case 51...67, 80...82: key = "Rain"
        case 71...77, 85...86: key = "Snow"
        case 95...99: key = "Thunderstorm"
        default: key = "Current weather"
        }
        return L10n.text(key, locale: locale)
    }
}
