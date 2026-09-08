import WidgetKit
import SwiftUI

struct SummaryEntry: TimelineEntry {
    let date: Date
    let summary: MonitorSummary
}

struct Provider: TimelineProvider {
    func placeholder(in context: Context) -> SummaryEntry {
        SummaryEntry(date: Date(), summary: .placeholder)
    }

    func getSnapshot(in context: Context, completion: @escaping (SummaryEntry) -> Void) {
        if context.isPreview {
            completion(SummaryEntry(date: Date(), summary: .placeholder))
            return
        }
        Task {
            let summary = await MonitorClient.fetchSummary()
            completion(SummaryEntry(date: Date(), summary: summary))
        }
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<SummaryEntry>) -> Void) {
        Task {
            let summary = await MonitorClient.fetchSummary()
            let entry = SummaryEntry(date: Date(), summary: summary)
            // WidgetKit rate-limits refreshes; ~15 min is a reasonable cadence.
            let next = Date().addingTimeInterval(15 * 60)
            completion(Timeline(entries: [entry], policy: .after(next)))
        }
    }
}

private struct WidgetBackground: ViewModifier {
    func body(content: Content) -> some View {
        if #available(iOS 17.0, *) {
            content.containerBackground(.fill.tertiary, for: .widget)
        } else {
            content.padding(12)
        }
    }
}

struct BatteryWidgetEntryView: View {
    var entry: SummaryEntry
    @Environment(\.widgetFamily) private var family

    private var s: MonitorSummary { entry.summary }

    private var socText: String { s.soc.map { "\(Int($0.rounded()))%" } ?? "--" }

    private var powerText: String {
        guard let p = s.powerW else { return "--" }
        return abs(p) >= 1000 ? String(format: "%.2f kW", p / 1000) : "\(Int(p.rounded())) W"
    }

    private var flowLabel: String {
        guard s.reachable else { return "Offline" }
        guard let p = s.powerW else { return "Idle" }
        if p > 25 { return "Charging" }
        if p < -25 { return "Discharging" }
        return "Idle"
    }

    private var accent: Color {
        guard s.reachable else { return .gray }
        guard let p = s.powerW else { return .orange }
        if p > 25 { return .green }
        if p < -25 { return .red }
        return .orange
    }

    var body: some View {
        Group {
            if family == .systemSmall { small } else { medium }
        }
        .modifier(WidgetBackground())
    }

    private var small: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text("Rack SOC").font(.caption2).foregroundStyle(.secondary)
                Spacer()
                Circle().fill(accent).frame(width: 8, height: 8)
            }
            Text(socText).font(.system(size: 34, weight: .bold, design: .rounded))
            Spacer(minLength: 0)
            Text(s.reachable ? "\(flowLabel) · \(powerText)" : "Offline")
                .font(.caption).foregroundStyle(.secondary).lineLimit(1)
        }
    }

    private var medium: some View {
        HStack(spacing: 16) {
            VStack(alignment: .leading, spacing: 4) {
                Text("Rack SOC").font(.caption2).foregroundStyle(.secondary)
                Text(socText)
                    .font(.system(size: 40, weight: .bold, design: .rounded))
                    .foregroundStyle(accent)
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 8) {
                stat(flowLabel, powerText)
                if let online = s.online, let total = s.total {
                    stat("Online", "\(online)/\(total)")
                }
                stat("Updated", s.updated.formatted(date: .omitted, time: .shortened))
            }
        }
    }

    private func stat(_ label: String, _ value: String) -> some View {
        VStack(alignment: .trailing, spacing: 1) {
            Text(label).font(.caption2).foregroundStyle(.secondary)
            Text(value).font(.callout.weight(.semibold))
        }
    }
}

struct BatteryWidget: Widget {
    let kind = "BatteryWidget"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: Provider()) { entry in
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
