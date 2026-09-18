import XCTest
@testable import BatteryMonitor

final class ModelDecodingTests: XCTestCase {
    func testDecodesDirectBatteryAndInverterTelemetry() throws {
        let data = Data(fixture.utf8)
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase

        let response = try decoder.decode(LiveResponse.self, from: data)

        XCTAssertEqual(response.collectorStatus, "online")
        XCTAssertEqual(response.rack.expectedBatteryCount, 3)
        XCTAssertEqual(response.snapshot.batteries.first?.lastReading?.socPercent, 82.4)
        XCTAssertEqual(response.snapshot.batteries.first?.lastReading?.cellVoltagesV?.count, 16)
        XCTAssertEqual(response.snapshot.inverter?.lastReading?.pvTotalPowerW, 4200)
        XCTAssertEqual(response.snapshot.inverter?.lastReading?.signedGridPowerW, 350)
    }

    private let fixture = #"""
    {
      "version":"1.0","build_commit":"abc123","collector_status":"online",
      "collector_error":null,"collector_reachable":true,
      "summary":{"battery_count":3,"online_count":3,"average_soc_percent":82.4,
        "total_power_w":-850,"total_current_a":-16.2,"average_voltage_v":52.4,
        "remaining_capacity_ah":247.2,"full_capacity_ah":300,
        "average_mosfet_temperature_c":25.2,"maximum_mosfet_temperature_c":26.0,
        "average_ambient_temperature_c":24.8,"maximum_cell_voltage_delta_v":0.012,
        "alarm_count":0,"fault_count":0},
      "rack":{"name":"Home Rack","builder":"Tran Thanh Tuan and son",
        "expected_battery_count":3,"observed_battery_count":3,"online_battery_count":3,
        "connection":"Modbus RTU over RS485","retention_days":1095,
        "batteries":[{"id":"rack-1","name":"Rack Battery 1","address":1,
          "ip_address":null,"model":"Eco-worthy","status":"ok","last_error":null,
          "last_polled_at":"2026-09-16T12:00:00Z","serial_number":"JBD1",
          "firmware_version":"1.0","rs485_protocol":"deye"}]},
      "snapshot":{"batteries":[{"id":"rack-1","address":1,"status":"ok",
        "last_polled_at":"2026-09-16T12:00:00Z","last_error":null,
        "last_reading":{"timestamp":"2026-09-16T12:00:00Z","voltage_v":52.4,
          "current_a":-5.4,"power_w":-283,"soc_percent":82.4,"remaining_capacity_ah":82.4,
          "full_capacity_ah":100,"rated_capacity_ah":100,"soh_percent":100,
          "cycle_count":14,"operation_status":"discharging","mosfet_state":["discharge"],
          "faults":[],"alarms":[],"mosfet_temperature_c":25.2,"ambient_temperature_c":24.8,
          "cell_voltage_delta_v":0.012,"cell_count":16,
          "cell_voltages_v":[3.27,3.27,3.28,3.27,3.28,3.27,3.27,3.28,3.27,3.28,3.27,3.27,3.28,3.27,3.28,3.27],
          "temperatures_c":[24.8,25.0,25.2,24.9]} }],
        "inverter":{"id":"renogy-x-8k","model":"Renogy X 8K","status":"ok","last_error":null,
          "last_reading":{"timestamp":"2026-09-16T12:00:00Z","pv_total_power_w":4200,
            "grid_import_power_w":350,"grid_export_power_w":0,"load_total_power_w":900,
            "home_load_total_power_w":3650,"faults":[],"alarms":[]}}}
    }
    """#
}

