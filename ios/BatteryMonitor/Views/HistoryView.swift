import Charts
import SwiftUI

struct HistoryView: View {
    @EnvironmentObject private var store: AppStore
    @State private var range = "24h"
    @State private var selectedTime: Date?

    private let ranges = ["6h", "24h", "7d", "30d", "365d"]

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Picker("Time range", selection: $range) {
                    ForEach(ranges, id: \.self) { Text(rangeLabel($0)).tag($0) }
                }
                .pickerStyle(.segmented)

                if let points = store.history?.points, !points.isEmpty {
                    powerPanel(points)
                    socPanel(points)
                } else {
                    EmptyStateView(
                        icon: "chart.xyaxis.line",
                        title: "No history available",
                        message: "Recorded power and SOC will appear after history loads from the monitor."
                    )
                    .frame(minHeight: 360)
                }
            }
            .padding()
        }
        .navigationTitle("Power History")
        .task(id: range) { await store.refreshHistory(range: range) }
        .refreshable { await store.refreshHistory(range: range) }
    }

    private func powerPanel(_ points: [PowerHistoryPoint]) -> some View {
        Panel {
            VStack(alignment: .leading, spacing: 12) {
                Text("Power").font(.headline)
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 12) {
                        seriesKey("Solar", color: .solarYellow)
                        seriesKey("Home", color: .orange)
                        seriesKey("Backup", color: .pink)
                        seriesKey("Grid", color: .gridBlue)
                        seriesKey("Battery", color: .batteryGreen)
                    }
                }
                if let nearest = nearestPoint(in: points) {
                    selectedReadout(nearest)
                }
                Chart(powerSamples(points)) { sample in
                    LineMark(
                        x: .value("Time", sample.date),
                        y: .value("Power", sample.value / 1_000),
                        series: .value("Series", sample.series.rawValue)
                    )
                    .foregroundStyle(by: .value("Series", sample.series.rawValue))
                    .interpolationMethod(.catmullRom)
                    .lineStyle(StrokeStyle(lineWidth: 2))
                }
                .chartForegroundStyleScale([
                    PowerSeries.solar.rawValue: Color.solarYellow,
                    PowerSeries.home.rawValue: Color.orange,
                    PowerSeries.backup.rawValue: Color.pink,
                    PowerSeries.grid.rawValue: Color.gridBlue,
                    PowerSeries.battery.rawValue: Color.batteryGreen,
                ])
                .chartLegend(.hidden)
                .chartYAxisLabel("kW")
                .chartXSelection(value: $selectedTime)
                .frame(height: 260)
            }
        }
    }

    private func socPanel(_ points: [PowerHistoryPoint]) -> some View {
        Panel {
            VStack(alignment: .leading, spacing: 12) {
                Text("Rack SOC").font(.headline)
                Chart(points.filter { $0.batterySocPercent != nil }) { point in
                    AreaMark(
                        x: .value("Time", point.date),
                        y: .value("SOC", point.batterySocPercent ?? 0)
                    )
                    .foregroundStyle(.linearGradient(
                        colors: [.batteryGreen.opacity(0.35), .batteryGreen.opacity(0.02)],
                        startPoint: .top,
                        endPoint: .bottom
                    ))
                    LineMark(
                        x: .value("Time", point.date),
                        y: .value("SOC", point.batterySocPercent ?? 0)
                    )
                    .foregroundStyle(.batteryGreen)
                    .lineStyle(StrokeStyle(lineWidth: 2))
                }
                .chartYScale(domain: 0...100)
                .chartYAxisLabel("%")
                .chartXSelection(value: $selectedTime)
                .frame(height: 180)
            }
        }
    }

    private func selectedReadout(_ point: PowerHistoryPoint) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack {
                Text(point.date, format: .dateTime.month().day().hour().minute())
                    .font(.caption.weight(.semibold))
                Spacer()
                Button { selectedTime = nil } label: { Image(systemName: "xmark.circle.fill") }
                    .buttonStyle(.plain)
                    .foregroundStyle(.secondary)
                    .accessibilityLabel("Close readout")
            }
            ViewThatFits(in: .horizontal) {
                HStack(spacing: 12) { readoutValues(point) }
                VStack(alignment: .leading, spacing: 3) { readoutValues(point) }
            }
            .font(.caption2)
            .foregroundStyle(.secondary)
        }
        .padding(10)
        .background(.primary.opacity(0.05), in: RoundedRectangle(cornerRadius: 6))
    }

    @ViewBuilder
    private func readoutValues(_ point: PowerHistoryPoint) -> some View {
        readoutValue("Solar", value: ValueFormat.power(point.solarPowerW))
        readoutValue("Home", value: ValueFormat.power(point.homeLoadPowerW))
        readoutValue("Grid", value: ValueFormat.power(point.gridPowerW))
        readoutValue("SOC", value: ValueFormat.percent(point.batterySocPercent))
    }

    private func seriesKey(_ title: LocalizedStringKey, color: Color) -> some View {
        HStack(spacing: 5) {
            Circle().fill(color).frame(width: 7, height: 7)
            Text(title).font(.caption2.weight(.semibold)).foregroundStyle(.secondary)
        }
    }

    private func readoutValue(_ title: LocalizedStringKey, value: String) -> some View {
        HStack(spacing: 3) {
            Text(title)
            Text(value).monospacedDigit()
        }
    }

    private func nearestPoint(in points: [PowerHistoryPoint]) -> PowerHistoryPoint? {
        guard let selectedTime else { return nil }
        return points.min { abs($0.date.timeIntervalSince(selectedTime)) < abs($1.date.timeIntervalSince(selectedTime)) }
    }

    private func powerSamples(_ points: [PowerHistoryPoint]) -> [PowerSample] {
        points.flatMap { point in
            [
                point.solarPowerW.map { PowerSample(date: point.date, value: $0, series: .solar) },
                point.homeLoadPowerW.map { PowerSample(date: point.date, value: $0, series: .home) },
                point.loadPowerW.map { PowerSample(date: point.date, value: $0, series: .backup) },
                point.gridPowerW.map { PowerSample(date: point.date, value: $0, series: .grid) },
                point.batteryPowerW.map { PowerSample(date: point.date, value: $0, series: .battery) },
            ].compactMap { $0 }
        }
    }

    private func rangeLabel(_ value: String) -> LocalizedStringKey {
        switch value {
        case "6h": "6H"
        case "24h": "24H"
        case "7d": "7D"
        case "30d": "30D"
        default: "1Y"
        }
    }
}

private enum PowerSeries: String {
    case solar = "Solar"
    case home = "Home"
    case backup = "Backup"
    case grid = "Grid"
    case battery = "Battery"
}

private struct PowerSample: Identifiable {
    let date: Date
    let value: Double
    let series: PowerSeries
    var id: String { "\(series.rawValue)-\(date.timeIntervalSince1970)" }
}
