import SwiftUI
import WidgetKit

struct SummaryEntry: TimelineEntry {
    let date: Date
    let summary: MonitorSummary
}

struct SummaryProvider: TimelineProvider {
    func placeholder(in context: Context) -> SummaryEntry {
        SummaryEntry(date: Date(), summary: .placeholder)
    }

    func getSnapshot(in context: Context, completion: @escaping (SummaryEntry) -> Void) {
        guard !context.isPreview else {
            completion(SummaryEntry(date: Date(), summary: .placeholder))
            return
        }
        Task {
            completion(SummaryEntry(date: Date(), summary: await MonitorClient.fetchSummary()))
        }
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<SummaryEntry>) -> Void) {
        Task {
            let entry = SummaryEntry(date: Date(), summary: await MonitorClient.fetchSummary())
            completion(Timeline(entries: [entry], policy: .after(Date().addingTimeInterval(15 * 60))))
        }
    }
}

struct BatteryWidgetEntryView: View {
    let entry: SummaryEntry
    @Environment(\.widgetFamily) private var family

    private var summary: MonitorSummary { entry.summary }
    private var socText: String { summary.soc.map { "\(Int($0.rounded()))%" } ?? "--" }
    private var powerText: String {
        guard let power = summary.powerW else { return "--" }
        return abs(power) >= 1_000
            ? String(format: "%.2f kW", power / 1_000)
            : "\(Int(power.rounded())) W"
    }
    private var flowLabel: LocalizedStringKey {
        guard summary.reachable else { return "Offline" }
        guard let power = summary.powerW else { return "Standby" }
        if power > 25 { return "Charging" }
        if power < -25 { return "Discharging" }
        return "Standby"
    }
    private var accent: Color {
        guard summary.reachable else { return .gray }
        guard let power = summary.powerW else { return .orange }
        if power > 25 { return .green }
        if power < -25 { return .red }
        return .orange
    }

    var body: some View {
        Group {
            if family == .systemSmall { small } else { medium }
        }
        .containerBackground(.fill.tertiary, for: .widget)
    }

    private var small: some View {
        VStack(alignment: .leading, spacing: 7) {
            HStack {
                Text("Rack SOC").font(.caption2).foregroundStyle(.secondary)
                Spacer()
                Circle().fill(accent).frame(width: 8, height: 8)
            }
            Text(socText)
                .font(.system(size: 34, weight: .bold, design: .rounded))
                .monospacedDigit()
            Spacer(minLength: 0)
            Text(flowLabel).font(.caption.weight(.semibold))
            Text(powerText).font(.caption).foregroundStyle(.secondary).monospacedDigit()
        }
    }

    private var medium: some View {
        HStack(spacing: 16) {
            VStack(alignment: .leading, spacing: 4) {
                Text("Rack SOC").font(.caption2).foregroundStyle(.secondary)
                Text(socText)
                    .font(.system(size: 40, weight: .bold, design: .rounded))
                    .foregroundStyle(accent)
                    .monospacedDigit()
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 8) {
                stat(flowLabel, powerText)
                if let online = summary.online, let total = summary.total {
                    stat("Online", "\(online)/\(total)")
                }
                VStack(alignment: .trailing, spacing: 1) {
                    Text("Updated").font(.caption2).foregroundStyle(.secondary)
                    Text(summary.updated, style: .time).font(.callout.weight(.semibold))
                }
            }
        }
    }

    private func stat(_ label: LocalizedStringKey, _ value: String) -> some View {
        VStack(alignment: .trailing, spacing: 1) {
            Text(label).font(.caption2).foregroundStyle(.secondary)
            Text(value).font(.callout.weight(.semibold)).monospacedDigit()
        }
    }
}

struct BatteryWidget: Widget {
    let kind = "BatteryWidget"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: SummaryProvider()) { entry in
            BatteryWidgetEntryView(entry: entry)
        }
        .configurationDisplayName("Battery Monitor")
        .description("Rack state of charge and live power.")
        .supportedFamilies([.systemSmall, .systemMedium])
    }
}

@main
struct BatteryWidgetBundle: WidgetBundle {
    var body: some Widget { BatteryWidget() }
}

