import SwiftUI

struct BatteriesView: View {
    @EnvironmentObject private var store: AppStore

    var body: some View {
        Group {
            if let rack = store.live?.rack, !rack.batteries.isEmpty {
                List(rack.batteries) { inventory in
                    NavigationLink {
                        BatteryDetailView(inventory: inventory, battery: store.battery(for: inventory))
                    } label: {
                        BatteryRow(inventory: inventory, battery: store.battery(for: inventory))
                    }
                }
                .listStyle(.insetGrouped)
                .refreshable { await store.refreshLive() }
            } else {
                EmptyStateView(
                    icon: "battery.0percent",
                    title: "No battery data",
                    message: "Battery details will appear after the app connects to the monitor."
                )
            }
        }
        .navigationTitle("Batteries")
    }
}

private struct BatteryRow: View {
    let inventory: BatteryInventory
    let battery: BatterySnapshot?

    private var reading: BatteryReading? { battery?.lastReading }
    private var soc: Double { max(0, min(100, reading?.socPercent ?? 0)) }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text(inventory.name).font(.headline)
                    Text(identityLine).font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                StatusBadge(status: battery?.status ?? inventory.status)
            }

            VStack(spacing: 5) {
                HStack {
                    Text("SOC").font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                    Spacer()
                    Text(ValueFormat.percent(reading?.socPercent)).font(.subheadline.weight(.semibold)).monospacedDigit()
                }
                ProgressView(value: soc, total: 100)
                    .tint(progressColor)
            }

            HStack(spacing: 16) {
                Label(ValueFormat.voltage(reading?.voltageV), systemImage: "bolt.circle")
                Label(ValueFormat.current(reading?.currentA), systemImage: "waveform.path.ecg")
                Label(ValueFormat.temperature(reading?.mosfetTemperatureC), systemImage: "thermometer.medium")
            }
            .font(.caption)
            .foregroundStyle(.secondary)
            .lineLimit(1)
            .minimumScaleFactor(0.72)
        }
        .padding(.vertical, 7)
    }

    private var identityLine: String {
        var values: [String] = []
        if let address = inventory.address { values.append("RS485 \(address)") }
        if let model = inventory.model, !model.isEmpty { values.append(model) }
        return values.joined(separator: " · ")
    }

    private var progressColor: Color {
        if soc < 20 { return .red }
        if soc < 40 { return .orange }
        return .batteryGreen
    }
}

struct BatteryDetailView: View {
    let inventory: BatteryInventory
    let battery: BatterySnapshot?
    @Environment(\.locale) private var locale

    private var reading: BatteryReading? { battery?.lastReading }
    private let columns = [GridItem(.adaptive(minimum: 130), spacing: 10)]

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Panel {
                    VStack(alignment: .leading, spacing: 12) {
                        HStack {
                            VStack(alignment: .leading, spacing: 3) {
                                Text(inventory.name).font(.title2.weight(.bold))
                                Text(inventory.model ?? L10n.text("Battery", locale: locale))
                                    .font(.subheadline)
                                    .foregroundStyle(.secondary)
                            }
                            Spacer()
                            StatusBadge(status: battery?.status ?? inventory.status)
                        }
                        HStack(alignment: .lastTextBaseline) {
                            Text(ValueFormat.percent(reading?.socPercent))
                                .font(.system(size: 42, weight: .bold, design: .rounded))
                                .monospacedDigit()
                            Spacer()
                            Text(operationState)
                                .font(.subheadline.weight(.semibold))
                                .foregroundStyle(.brandOrange)
                        }
                    }
                }

                LazyVGrid(columns: columns, spacing: 10) {
                    MetricTile(title: "Voltage", value: ValueFormat.voltage(reading?.voltageV), detail: nil, icon: "bolt.fill", color: .yellow)
                    MetricTile(title: "Current", value: ValueFormat.current(reading?.currentA), detail: nil, icon: "waveform.path.ecg", color: .cyan)
                    MetricTile(title: "Power", value: ValueFormat.power(reading?.powerW), detail: nil, icon: "poweroutlet.type.b.fill", color: .brandOrange)
                    MetricTile(title: "State of health", value: ValueFormat.percent(reading?.sohPercent), detail: cycleDetail, icon: "heart.fill", color: .pink)
                    MetricTile(title: "MOSFET", value: ValueFormat.temperature(reading?.mosfetTemperatureC), detail: nil, icon: "thermometer.medium", color: .orange)
                    MetricTile(title: "Cell delta", value: cellDelta, detail: cellRange, icon: "square.grid.4x3.fill", color: .purple)
                }

                if let cells = reading?.cellVoltagesV, !cells.isEmpty {
                    cellPanel(cells)
                }

                if let temperatures = reading?.temperaturesC, !temperatures.isEmpty {
                    sensorPanel(temperatures)
                }

                alertsPanel
                identityPanel
            }
            .padding()
        }
        .navigationTitle(inventory.name)
        .navigationBarTitleDisplayMode(.inline)
    }

    private func cellPanel(_ cells: [Double]) -> some View {
        Panel {
            VStack(alignment: .leading, spacing: 12) {
                Label("Cell voltages", systemImage: "square.grid.4x3.fill").font(.headline)
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 66), spacing: 7)], spacing: 7) {
                    ForEach(Array(cells.enumerated()), id: \.offset) { index, voltage in
                        VStack(spacing: 3) {
                            Text("C\(index + 1)").font(.caption2).foregroundStyle(.secondary)
                            Text(String(format: "%.3f", voltage))
                                .font(.caption.weight(.semibold))
                                .monospacedDigit()
                        }
                        .padding(.vertical, 7)
                        .frame(maxWidth: .infinity)
                        .background(cellColor(voltage, cells: cells).opacity(0.12), in: RoundedRectangle(cornerRadius: 6))
                    }
                }
            }
        }
    }

    private func sensorPanel(_ temperatures: [Double]) -> some View {
        Panel {
            VStack(alignment: .leading, spacing: 10) {
                Label("Temperature sensors", systemImage: "thermometer.medium").font(.headline)
                ForEach(Array(temperatures.enumerated()), id: \.offset) { index, temperature in
                    HStack {
                        Text("Sensor \(index + 1)")
                        Spacer()
                        Text(ValueFormat.temperature(temperature)).monospacedDigit()
                    }
                    .font(.subheadline)
                }
            }
        }
    }

    private var alertsPanel: some View {
        let alarms = reading?.alarms ?? []
        let faults = reading?.faults ?? []
        return Panel {
            VStack(alignment: .leading, spacing: 10) {
                Label("Alarms and faults", systemImage: "exclamationmark.triangle.fill").font(.headline)
                if alarms.isEmpty && faults.isEmpty {
                    Label("No active alarms or faults", systemImage: "checkmark.circle.fill")
                        .foregroundStyle(.batteryGreen)
                } else {
                    ForEach(alarms, id: \.self) { Text($0).foregroundStyle(.orange) }
                    ForEach(faults, id: \.self) { Text($0).foregroundStyle(.red) }
                }
            }
            .font(.subheadline)
        }
    }

    private var identityPanel: some View {
        Panel {
            VStack(alignment: .leading, spacing: 10) {
                Label("Battery information", systemImage: "info.circle.fill").font(.headline)
                detailRow("Address", value: inventory.address.map { String($0) } ?? "--")
                detailRow("Serial number", value: reading?.serialNumber ?? inventory.serialNumber ?? "--")
                detailRow("Firmware", value: reading?.firmwareVersion ?? inventory.firmwareVersion ?? "--")
                detailRow("IP address", value: inventory.ipAddress ?? "--")
            }
        }
    }

    private func detailRow(_ title: LocalizedStringKey, value: String) -> some View {
        HStack {
            Text(title).foregroundStyle(.secondary)
            Spacer()
            Text(value).monospacedDigit().multilineTextAlignment(.trailing)
        }
        .font(.subheadline)
    }

    private func cellColor(_ voltage: Double, cells: [Double]) -> Color {
        if voltage == cells.max() { return .orange }
        if voltage == cells.min() { return .cyan }
        return .secondary
    }

    private var operationState: String { reading?.operationStatus?.capitalized ?? L10n.text("Unavailable", locale: locale) }
    private var cycleDetail: String? { reading?.cycleCount.map { "\($0) " + L10n.text("cycles", locale: locale) } }
    private var cellDelta: String {
        guard let delta = reading?.cellVoltageDeltaV else { return "--" }
        return String(format: "%.0f mV", delta * 1_000)
    }
    private var cellRange: String? {
        guard let low = reading?.lowCellVoltageV, let high = reading?.highCellVoltageV else { return nil }
        return String(format: "%.3f–%.3f V", low, high)
    }
}
