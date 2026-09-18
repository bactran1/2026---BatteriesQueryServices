import SwiftUI

struct SavingsView: View {
    @EnvironmentObject private var store: AppStore
    @Environment(\.locale) private var locale
    @State private var selection: SavingsSelection = .month

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Picker("Savings period", selection: $selection) {
                    ForEach(SavingsSelection.allCases) { Text($0.title).tag($0) }
                }
                .pickerStyle(.segmented)

                if let response = store.savings, let period = selection.period(from: response.periods) {
                    savingsHero(period)

                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 145), spacing: 10)], spacing: 10) {
                        MetricTile(title: "Solar generated", value: ValueFormat.energy(period.solarGenerationKwh), detail: nil, icon: "sun.max.fill", color: .solarYellow)
                        MetricTile(title: "Grid purchased", value: ValueFormat.energy(period.gridImportKwh), detail: estimatedCost(period), icon: "transmission", color: .gridBlue)
                        MetricTile(title: "Energy consumed", value: ValueFormat.energy(period.consumptionKwh), detail: nil, icon: "house.fill", color: .orange)
                        MetricTile(title: "Daily savings", value: ValueFormat.money(period.averageSavingsPerObservedDayUsdLow, period.averageSavingsPerObservedDayUsdHigh), detail: observedDays(period), icon: "calendar", color: .batteryGreen)
                    }

                    tariffPanel(response.tariff)
                } else {
                    EmptyStateView(
                        icon: "dollarsign.circle",
                        title: "Savings are not available",
                        message: "Savings appear after the monitor has recorded solar and grid energy."
                    )
                    .frame(minHeight: 360)
                }
            }
            .padding()
        }
        .navigationTitle("Energy Savings")
        .refreshable { await store.refreshSecondary() }
    }

    private func savingsHero(_ period: SavingsPeriod) -> some View {
        Panel {
            VStack(alignment: .leading, spacing: 16) {
                Label("Estimated savings", systemImage: "leaf.fill")
                    .font(.headline)
                    .foregroundStyle(.batteryGreen)
                Text(ValueFormat.money(period.estimatedSavingsUsdLow, period.estimatedSavingsUsdHigh))
                    .font(.system(size: 42, weight: .bold, design: .rounded))
                    .monospacedDigit()
                    .minimumScaleFactor(0.72)
                VStack(alignment: .leading, spacing: 6) {
                    HStack {
                        Text("Solar share").font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                        Spacer()
                        Text(ValueFormat.percent(period.solarSharePercent)).font(.caption.weight(.semibold))
                    }
                    ProgressView(value: period.solarSharePercent ?? 0, total: 100).tint(.batteryGreen)
                }
            }
        }
    }

    private func tariffPanel(_ tariff: UtilityTariff) -> some View {
        Panel {
            VStack(alignment: .leading, spacing: 10) {
                Label("Rate information", systemImage: "doc.text.fill").font(.headline)
                Text("\(tariff.provider) · \(tariff.schedule)").font(.subheadline.weight(.semibold))
                Text(tariff.region).font(.caption).foregroundStyle(.secondary)
                if let low = tariff.effectiveRateLowUsdPerKwh, let high = tariff.effectiveRateHighUsdPerKwh {
                    Text(L10n.format("$%.3f–$%.3f per kWh variable rate", locale: locale, low, high))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Text("Estimates value recorded solar production at the configured utility rate. Actual bills may differ.")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }
        }
    }

    private func estimatedCost(_ period: SavingsPeriod) -> String? {
        let value = ValueFormat.money(period.estimatedGridCostUsdLow, period.estimatedGridCostUsdHigh)
        return value == "--" ? nil : L10n.text("Estimated cost", locale: locale) + " " + value
    }

    private func observedDays(_ period: SavingsPeriod) -> String? {
        period.observedDays.map { "\($0) " + L10n.text("observed days", locale: locale) }
    }
}

private enum SavingsSelection: String, CaseIterable, Identifiable {
    case today, month, year, retained
    var id: String { rawValue }
    var title: LocalizedStringKey {
        switch self {
        case .today: "Today"
        case .month: "Month"
        case .year: "Year"
        case .retained: "All"
        }
    }
    func period(from periods: SavingsPeriods) -> SavingsPeriod? {
        switch self {
        case .today: periods.today
        case .month: periods.month
        case .year: periods.year
        case .retained: periods.retained
        }
    }
}
