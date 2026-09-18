import SwiftUI

extension Color {
    static let brandOrange = Color(red: 1.0, green: 0.39, blue: 0.0)
    static let solarYellow = Color(red: 0.95, green: 0.82, blue: 0.12)
    static let gridBlue = Color(red: 0.25, green: 0.68, blue: 0.95)
    static let batteryGreen = Color(red: 0.16, green: 0.72, blue: 0.38)
}

enum L10n {
    static func text(_ key: String, locale: Locale) -> String {
        let language = locale.language.languageCode?.identifier ?? "en"
        return text(key, language: language)
    }

    static func text(_ key: String, language: String) -> String {
        guard let path = Bundle.main.path(forResource: language, ofType: "lproj"),
              let bundle = Bundle(path: path) else {
            return NSLocalizedString(key, comment: "")
        }
        return NSLocalizedString(key, bundle: bundle, comment: "")
    }

    static func format(_ key: String, locale: Locale, _ arguments: CVarArg...) -> String {
        String(format: text(key, locale: locale), locale: locale, arguments: arguments)
    }
}

struct Panel<Content: View>: View {
    private let content: Content

    init(@ViewBuilder content: () -> Content) {
        self.content = content()
    }

    var body: some View {
        content
            .padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 8, style: .continuous))
            .overlay {
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .stroke(.primary.opacity(0.08), lineWidth: 1)
            }
    }
}

struct MetricTile: View {
    let title: LocalizedStringKey
    let value: String
    let detail: String?
    let icon: String
    let color: Color

    var body: some View {
        Panel {
            HStack(alignment: .top, spacing: 12) {
                Image(systemName: icon)
                    .font(.system(size: 18, weight: .semibold))
                    .foregroundStyle(color)
                    .frame(width: 28, height: 28)
                    .background(color.opacity(0.12), in: RoundedRectangle(cornerRadius: 6))
                VStack(alignment: .leading, spacing: 4) {
                    Text(title)
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                    Text(value)
                        .font(.title3.weight(.semibold))
                        .monospacedDigit()
                        .lineLimit(1)
                        .minimumScaleFactor(0.72)
                    if let detail {
                        Text(detail)
                            .font(.caption2)
                            .foregroundStyle(.tertiary)
                            .lineLimit(2)
                    }
                }
            }
        }
    }
}

struct StatusBadge: View {
    let status: String

    private var color: Color {
        switch status.lowercased() {
        case "online", "ok": .batteryGreen
        case "degraded", "stale": .orange
        default: .red
        }
    }

    var body: some View {
        HStack(spacing: 6) {
            Circle().fill(color).frame(width: 7, height: 7)
            Text(statusLabel)
                .font(.caption.weight(.semibold))
        }
        .foregroundStyle(color)
        .padding(.horizontal, 9)
        .padding(.vertical, 5)
        .background(color.opacity(0.12), in: Capsule())
        .accessibilityElement(children: .combine)
    }

    private var statusLabel: LocalizedStringKey {
        switch status.lowercased() {
        case "ok", "online": "Online"
        case "degraded": "Degraded"
        case "stale": "Stale"
        default: "Offline"
        }
    }
}

struct EmptyStateView: View {
    let icon: String
    let title: LocalizedStringKey
    let message: LocalizedStringKey

    var body: some View {
        ContentUnavailableView {
            Label(title, systemImage: icon)
        } description: {
            Text(message)
        }
    }
}

enum ValueFormat {
    static func power(_ watts: Double?) -> String {
        guard let watts else { return "--" }
        if abs(watts) >= 1_000 {
            return String(format: "%.2f kW", watts / 1_000)
        }
        return String(format: "%.0f W", watts)
    }

    static func percent(_ value: Double?) -> String {
        guard let value else { return "--" }
        return String(format: "%.1f%%", value)
    }

    static func voltage(_ value: Double?) -> String {
        guard let value else { return "--" }
        return String(format: "%.2f V", value)
    }

    static func current(_ value: Double?) -> String {
        guard let value else { return "--" }
        return String(format: "%.2f A", value)
    }

    static func temperature(_ value: Double?) -> String {
        guard let value else { return "--" }
        return String(format: "%.1f°C", value)
    }

    static func energy(_ value: Double?) -> String {
        guard let value else { return "--" }
        return String(format: "%.1f kWh", value)
    }

    static func money(_ low: Double?, _ high: Double?) -> String {
        guard let low else { return "--" }
        guard let high, abs(high - low) >= 0.01 else { return String(format: "$%.2f", low) }
        return String(format: "$%.2f–$%.2f", low, high)
    }
}
