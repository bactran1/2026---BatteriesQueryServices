import SwiftUI

struct EnergyFlowView: View {
    let live: LiveResponse
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.locale) private var locale

    private var inverter: InverterReading? { live.snapshot.inverter?.lastReading }
    private var batteryPower: Double? { live.summary.totalPowerW }
    private var solarPower: Double? { inverter?.pvTotalPowerW }
    private var gridPower: Double? { inverter?.signedGridPowerW }
    private var homePower: Double? { inverter?.homeLoadTotalPowerW }
    private var backupPower: Double? { inverter?.loadTotalPowerW }

    var body: some View {
        Panel {
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Live power flow").font(.headline)
                        Text(flowSummary)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    Image(systemName: "bolt.horizontal.circle.fill")
                        .font(.title2)
                        .foregroundStyle(.brandOrange)
                }

                GeometryReader { proxy in
                    TimelineView(.animation(minimumInterval: reduceMotion ? 1 : 1 / 24)) { timeline in
                        let phase = timeline.date.timeIntervalSinceReferenceDate
                        ZStack {
                            flowCanvas(size: proxy.size, phase: phase)
                            node("Solar", icon: "sun.max.fill", value: ValueFormat.power(solarPower), color: .solarYellow)
                                .position(point(.solar, in: proxy.size))
                            node("Grid", icon: "transmission", value: gridLabel, color: .gridBlue)
                                .position(point(.grid, in: proxy.size))
                            node("Inverter", icon: "bolt.fill", value: inverterState, color: .brandOrange)
                                .position(point(.inverter, in: proxy.size))
                            node("Battery", icon: "battery.100percent", value: batteryLabel, color: .batteryGreen)
                                .position(point(.battery, in: proxy.size))
                            node("Home", icon: "house.fill", value: ValueFormat.power(homePower), color: .orange)
                                .position(point(.home, in: proxy.size))
                            node("Backup", icon: "powerplug.fill", value: ValueFormat.power(backupPower), color: .pink)
                                .position(point(.backup, in: proxy.size))
                        }
                    }
                }
                .frame(height: 305)
                .accessibilityElement(children: .contain)
            }
        }
    }

    private func flowCanvas(size: CGSize, phase: TimeInterval) -> some View {
        Canvas { context, canvasSize in
            let segments: [(FlowNode, FlowNode, Color, Bool, Bool)] = [
                (.solar, .inverter, .solarYellow, active(solarPower), false),
                (.grid, .inverter, .gridBlue, active(gridPower), (gridPower ?? 0) < 0),
                (.inverter, .home, .orange, active(homePower), false),
                (.inverter, .backup, .pink, active(backupPower), false),
                (.inverter, .battery, .batteryGreen, active(batteryPower), (batteryPower ?? 0) < 0),
            ]
            for (start, end, color, isActive, reverse) in segments {
                var path = Path()
                path.move(to: point(start, in: canvasSize))
                path.addLine(to: point(end, in: canvasSize))
                context.stroke(path, with: .color(color.opacity(0.2)), style: StrokeStyle(lineWidth: 4, lineCap: .round))
                guard isActive else { continue }
                let direction = reverse ? -1.0 : 1.0
                let offset = reduceMotion ? 0 : direction * phase * 28
                context.stroke(
                    path,
                    with: .color(color),
                    style: StrokeStyle(lineWidth: 4, lineCap: .round, dash: [3, 12], dashPhase: CGFloat(offset))
                )
            }
        }
        .allowsHitTesting(false)
    }

    private func node(_ title: LocalizedStringKey, icon: String, value: String, color: Color) -> some View {
        VStack(spacing: 4) {
            Image(systemName: icon)
                .font(.system(size: 18, weight: .semibold))
                .foregroundStyle(color)
            Text(title)
                .font(.caption2.weight(.semibold))
                .foregroundStyle(.secondary)
            Text(value)
                .font(.caption.weight(.bold))
                .monospacedDigit()
                .lineLimit(1)
                .minimumScaleFactor(0.65)
        }
        .padding(.vertical, 8)
        .padding(.horizontal, 7)
        .frame(width: 92, height: 70)
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 8, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .stroke(color.opacity(0.28), lineWidth: 1)
        }
    }

    private func point(_ node: FlowNode, in size: CGSize) -> CGPoint {
        switch node {
        case .solar: CGPoint(x: size.width * 0.28, y: 48)
        case .grid: CGPoint(x: size.width * 0.78, y: 48)
        case .inverter: CGPoint(x: size.width * 0.52, y: 150)
        case .battery: CGPoint(x: size.width * 0.20, y: 255)
        case .home: CGPoint(x: size.width * 0.52, y: 255)
        case .backup: CGPoint(x: size.width * 0.82, y: 255)
        }
    }

    private func active(_ value: Double?) -> Bool { abs(value ?? 0) > 25 }

    private var gridLabel: String {
        guard let gridPower else { return "--" }
        let suffix = gridPower < -25 ? L10n.text("export", locale: locale) : L10n.text("import", locale: locale)
        return "\(ValueFormat.power(abs(gridPower))) \(suffix)"
    }

    private var batteryLabel: String {
        let soc = ValueFormat.percent(live.summary.averageSocPercent)
        guard let batteryPower, abs(batteryPower) > 25 else { return soc }
        return "\(soc) · \(ValueFormat.power(abs(batteryPower)))"
    }

    private var inverterState: String {
        guard let inverter = live.snapshot.inverter else { return L10n.text("Unavailable", locale: locale) }
        return inverter.status == "ok" ? L10n.text("Online", locale: locale) : inverter.status.capitalized
    }

    private var flowSummary: String {
        if active(solarPower) { return L10n.text("Solar is supplying the home", locale: locale) }
        if (gridPower ?? 0) > 25 { return L10n.text("Grid power is supplying the home", locale: locale) }
        if (batteryPower ?? 0) < -25 { return L10n.text("Battery is supplying the home", locale: locale) }
        return L10n.text("System is standing by", locale: locale)
    }
}

private enum FlowNode {
    case solar, grid, inverter, battery, home, backup
}
