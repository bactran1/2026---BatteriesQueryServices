import Foundation

struct LiveResponse: Codable, Sendable {
    let version: String?
    let buildCommit: String?
    let collectorStatus: String
    let collectorError: String?
    let collectorReachable: Bool?
    let summary: RackSummary
    let rack: RackInfo
    let snapshot: MonitorSnapshot
}

struct RackSummary: Codable, Sendable {
    let batteryCount: Int?
    let onlineCount: Int?
    let averageSocPercent: Double?
    let totalPowerW: Double?
    let totalCurrentA: Double?
    let averageVoltageV: Double?
    let remainingCapacityAh: Double?
    let fullCapacityAh: Double?
    let averageMosfetTemperatureC: Double?
    let maximumMosfetTemperatureC: Double?
    let averageAmbientTemperatureC: Double?
    let maximumCellVoltageDeltaV: Double?
    let alarmCount: Int?
    let faultCount: Int?
}

struct RackInfo: Codable, Sendable {
    let name: String
    let builder: String?
    let expectedBatteryCount: Int
    let observedBatteryCount: Int
    let onlineBatteryCount: Int
    let connection: String?
    let retentionDays: Int?
    let batteries: [BatteryInventory]
}

struct BatteryInventory: Codable, Identifiable, Hashable, Sendable {
    let id: String
    let name: String
    let address: Int?
    let ipAddress: String?
    let model: String?
    let status: String
    let lastError: String?
    let lastPolledAt: String?
    let serialNumber: String?
    let firmwareVersion: String?
    let rs485Protocol: String?
}

struct MonitorSnapshot: Codable, Sendable {
    let batteries: [BatterySnapshot]
    let inverter: InverterSnapshot?
}

struct BatterySnapshot: Codable, Identifiable, Sendable {
    let id: String
    let address: Int?
    let status: String
    let lastPolledAt: String?
    let lastError: String?
    let lastReading: BatteryReading?
}

struct BatteryReading: Codable, Sendable {
    let timestamp: String?
    let voltageV: Double?
    let currentA: Double?
    let powerW: Double?
    let socPercent: Double?
    let remainingCapacityAh: Double?
    let fullCapacityAh: Double?
    let ratedCapacityAh: Double?
    let sohPercent: Double?
    let cycleCount: Int?
    let operationStatus: String?
    let mosfetState: [String]?
    let faults: [String]?
    let alarms: [String]?
    let mosfetTemperatureC: Double?
    let ambientTemperatureC: Double?
    let highCellNumber: Int?
    let highCellVoltageV: Double?
    let lowCellNumber: Int?
    let lowCellVoltageV: Double?
    let averageCellVoltageV: Double?
    let cellVoltageDeltaV: Double?
    let highTemperatureC: Double?
    let lowTemperatureC: Double?
    let averageTemperatureC: Double?
    let chargeVoltageLimitV: Double?
    let chargeCurrentLimitA: Double?
    let dischargeVoltageLimitV: Double?
    let dischargeCurrentLimitA: Double?
    let cellCount: Int?
    let cellVoltagesV: [Double]?
    let temperatureSensorCount: Int?
    let temperaturesC: [Double]?
    let firmwareVersion: String?
    let serialNumber: String?
}

struct InverterSnapshot: Codable, Sendable {
    let id: String?
    let model: String?
    let status: String
    let lastError: String?
    let lastReading: InverterReading?
}

struct InverterReading: Codable, Sendable {
    let timestamp: String?
    let pvTotalPowerW: Double?
    let gridImportPowerW: Double?
    let gridExportPowerW: Double?
    let gridTotalPowerW: Double?
    let loadTotalPowerW: Double?
    let homeLoadTotalPowerW: Double?
    let inverterTemperatureC: Double?
    let operatingMode: String?
    let faults: [String]?
    let alarms: [String]?

    var signedGridPowerW: Double? {
        if gridImportPowerW != nil || gridExportPowerW != nil {
            return (gridImportPowerW ?? 0) - (gridExportPowerW ?? 0)
        }
        return gridTotalPowerW.map { -$0 }
    }
}

struct WeatherResponse: Codable, Sendable {
    let status: String
    let source: String?
    let location: String?
    let observedAt: String?
    let temperatureC: Double?
    let apparentTemperatureC: Double?
    let relativeHumidityPercent: Double?
    let precipitationMm: Double?
    let weatherCode: Int?
    let weatherLabel: String?
    let cloudCoverPercent: Double?
    let windSpeedKmh: Double?
    let isDay: Bool?
    let solarIrradianceWM2: Double?
    let directNormalIrradianceWM2: Double?
    let solarElevationDegrees: Double?
    let solarAzimuthDegrees: Double?
}

struct PowerHistoryResponse: Codable, Sendable {
    let range: String
    let bucketSeconds: Int?
    let points: [PowerHistoryPoint]
}

struct PowerHistoryPoint: Codable, Identifiable, Sendable {
    let unix: Double
    let timestamp: String?
    let gridPowerW: Double?
    let batteryPowerW: Double?
    let solarPowerW: Double?
    let homeLoadPowerW: Double?
    let loadPowerW: Double?
    let batterySocPercent: Double?

    var id: Double { unix }
    var date: Date { Date(timeIntervalSince1970: unix) }
}

struct SavingsResponse: Codable, Sendable {
    let currency: String
    let defaultPeriod: String?
    let selectedDate: String?
    let periods: SavingsPeriods
    let tariff: UtilityTariff
}

struct SavingsPeriods: Codable, Sendable {
    let date: SavingsPeriod?
    let today: SavingsPeriod?
    let month: SavingsPeriod?
    let year: SavingsPeriod?
    let retained: SavingsPeriod?
}

struct SavingsPeriod: Codable, Sendable {
    let solarGenerationKwh: Double?
    let gridImportKwh: Double?
    let consumptionKwh: Double?
    let observedDays: Int?
    let estimatedSavingsUsdLow: Double?
    let estimatedSavingsUsdHigh: Double?
    let estimatedGridCostUsdLow: Double?
    let estimatedGridCostUsdHigh: Double?
    let solarSharePercent: Double?
    let averageSavingsPerObservedDayUsdLow: Double?
    let averageSavingsPerObservedDayUsdHigh: Double?
}

struct UtilityTariff: Codable, Sendable {
    let provider: String
    let schedule: String
    let region: String
    let effectiveDate: String?
    let effectiveRateLowUsdPerKwh: Double?
    let effectiveRateHighUsdPerKwh: Double?
}

struct DashboardCache: Codable, Sendable {
    let savedAt: Date
    let live: LiveResponse?
    let weather: WeatherResponse?
    let savings: SavingsResponse?
}

