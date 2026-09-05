const state = {
  batteries: [],
  inverter: null,
  selectedBatteryId: null,
  range: "24h",
  history: [],
  powerSeries: new Set(["grid_power_w", "battery_power_w", "solar_power_w", "load_power_w"]),
  energyView: "month",
  energyDate: localCalendarDateValue(new Date()),
  energyTimezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
  energyHistory: [],
  energySummary: {},
  energySummaryPeriod: null,
  energyWindowStart: null,
  energyWindowEnd: null,
  storage: {},
  rack: {},
  collectorState: "offline",
  collectorOnline: false,
  lastLiveReceivedAt: 0,
  lastHistoryRefreshAt: 0,
  lastEnergyRefreshAt: 0,
  lastEventsRefreshAt: 0,
  refreshInProgress: false,
  resourceErrors: { live: null, history: null, energy: null, events: null },
  theme: "light",
  chartGeometry: null,
  chartHover: null,
  chartReveal: 1,
  renderedSoc: new Map(),
  language: document.documentElement.lang === "vi" ? "vi" : "en",
  livePayload: null,
  summary: {},
  events: [],
};

const translations = {
  en: {
    "page.title": "Battery Monitor",
    "app.title": "Battery Monitor",
    "logo.alt": "Tran T logo",
    "brand.builderDefault": "The system is built by Tran Thanh Tuan and son",
    "brand.builder": "The system is built by {builder} and son",
    "language.switchTitle": "Switch language",
    "language.switchLabel": "Switch between English and Vietnamese",
    "theme.switchTitle": "Switch appearance",
    "theme.switchLabel": "Switch between light and dark theme",
    "status.starting": "Starting",
    "status.noReadings": "No readings yet",
    "status.connecting": "Connecting to collector",
    "status.noLiveReadings": "No live readings yet",
    "status.dataRelative": "Data {relative}",
    "status.lastError": "Last error: {message}",
    "status.archiveError": "Archive error: {message}",
    "status.responding": "{online} of {total} batteries responding",
    "status.lastCollectorData": "Last collector data {relative}",
    "status.waitingFresh": "Waiting for a fresh collector sample",
    "status.waitingReconnect": "Waiting for the collector to reconnect",
    "status.recoveryDelayed": "Archive recovery delayed: {message}",
    "status.archiveCurrent": "Archive current · {rows} rows",
    "status.monitorOffline": "Monitor offline",
    "status.dataStale": "Data stale",
    "status.lastDashboardUpdate": "Last dashboard update {relative}",
    "status.noDashboardResponse": "No dashboard response",
    "status.refreshError": "Refresh error: {message}",
    "status.pending": "Pending",
    "status.online": "Online",
    "status.needsAttention": "Needs attention",
    "status.disabled": "Disabled",
    "status.lastKnown": "Last known",
    "status.waiting": "Waiting",
    "status.collectorOnline": "Collector online",
    "status.collectorDegraded": "Collector degraded",
    "status.collectorStale": "Data stale",
    "status.collectorOffline": "Collector offline",
    "status.collectorOnlineDescription": "Collector and all configured batteries are responding",
    "status.collectorDegradedDescription": "Collector is reachable, but one or more batteries need attention",
    "status.collectorStaleDescription": "Last known data is being shown while the collector reconnects",
    "status.collectorOfflineDescription": "The collector has not responded within the offline threshold",
    "common.waitingData": "Waiting for data",
    "common.waitingReadings": "Waiting for readings",
    "common.notConfigured": "Not configured",
    "common.recently": "recently",
    "rack.overview": "Rack overview",
    "rack.waitingStatus": "Waiting for rack status",
    "rack.batteries": "Batteries",
    "rack.collector": "Collector",
    "rack.defaultCollector": "Raspberry Pi collector",
    "rack.defaultConnection": "Modbus RTU over RS485",
    "rack.bus": "Bus",
    "rack.allOnline": "All batteries online",
    "rack.onlineCount": "{online} of {expected} online",
    "rack.pack": "pack",
    "rack.packs": "packs",
    "rack.reporting": "{count} reporting",
    "energy.eyebrow": "Live home energy",
    "energy.title": "Home power flow",
    "energy.waiting": "Waiting for live energy telemetry",
    "energy.waitingShort": "Waiting",
    "energy.sceneAria": "Three-dimensional power flow between the grid, inverter, battery rack, and home load",
    "energy.grid": "Grid",
    "energy.inverter": "Inverter",
    "energy.solar": "Solar",
    "energy.storage": "Battery rack",
    "energy.load": "Home load",
    "energy.direction": "Observed path",
    "energy.rate": "Battery power",
    "energy.charging": "Charging the battery",
    "energy.discharging": "Powering the home",
    "energy.idle": "Home system standing by",
    "energy.stale": "Live home flow paused",
    "energy.toBattery": "Grid → battery",
    "energy.fromBattery": "Battery → home",
    "energy.noTransfer": "No transfer",
    "energy.unavailable": "Unavailable",
    "energy.unmetered": "Not metered",
    "energy.routing": "Routing power",
    "energy.standby": "Standby",
    "energy.gridSupplying": "Grid is supplying the home",
    "energy.solarSupplying": "Solar is supplying the home",
    "energy.batterySupplying": "Battery is supplying the home",
    "energy.mixedSupply": "Multiple sources are supplying the home",
    "energy.noActiveSource": "No active power source",
    "energy.sourceGrid": "{value} from grid",
    "energy.sourceSolar": "{value} from solar",
    "energy.sourceBattery": "{value} from battery",
    "energy.gridExport": "{value} to grid",
    "energy.loadPhrase": "{value} home load",
    "energy.batteryChargingPhrase": "{value} charging battery",
    "energy.batteryDischargingPhrase": "{value} from battery",
    "energy.batteryIdlePhrase": "Battery idle",
    "energy.batteryUnavailablePhrase": "Battery telemetry unavailable",
    "energy.runtimeRemaining": "~{time} remaining at this discharge rate",
    "energy.runtimeCallout": "~{time} remaining",
    "energy.liveDescription": "{sources} · {load} · {battery}",
    "energy.importing": "{value} import",
    "energy.exporting": "{value} export",
    "energy.chargingValue": "{value} charging",
    "energy.dischargingValue": "{value} discharging",
    "energy.pack": "battery pack",
    "energy.packs": "battery packs",
    "energy.chargingDescription": "Direct battery telemetry measures {rate} entering {packs}. Solar, grid, and home paths remain paused until inverter telemetry is connected.",
    "energy.dischargingDescription": "Direct battery telemetry measures {rate} leaving {packs}. Its destination remains unknown until inverter telemetry is connected.",
    "energy.idleDescription": "Battery telemetry shows no significant transfer. Solar, grid, and home meters are not connected yet.",
    "energy.staleDescription": "Live home flow is paused until fresh collector data arrives.",
    "inverter.summary": "Inverter summary",
    "inverter.eyebrow": "Live inverter",
    "inverter.title": "Renogy X 8K",
    "inverter.waiting": "Waiting for inverter telemetry",
    "inverter.identity": "{serial} · Protocol {protocol}",
    "inverter.solar": "Solar array",
    "inverter.solarToday": "{count} MPPT · {energy} today",
    "inverter.grid": "Grid",
    "inverter.gridElectrical": "L1 {l1} · L2 {l2} · {frequency}",
    "inverter.load": "Backup load",
    "inverter.loadDetail": "{energy} today · External CT {external}",
    "inverter.battery": "Battery rack",
    "inverter.batteryElectrical": "Direct RS485 · {voltage} · {current} · {soc} · {temperature}",
    "inverter.batteryWaiting": "Waiting for direct battery telemetry",
    "inverter.runtimeRemaining": "Estimated support · {time} at current discharge",
    "inverter.thermal": "Inverter thermal",
    "inverter.internalTemperature": "{value} internal",
    "inverter.thermalDetail": "Inverter {inverter} · DC/DC {dcdc}",
    "inverter.healthNominal": "No active alarms or faults",
    "inverter.healthAlerts": "{alarms} alarms · {faults} faults",
    "inverter.lastError": "Last error: {message}",
    "energyHistory.eyebrow": "Energy history",
    "energyHistory.titleHour": "Energy by hour",
    "energyHistory.titleDate": "Energy for one day",
    "energyHistory.titleDateFor": "Energy on {date}",
    "energyHistory.titleMonth": "Energy by month",
    "energyHistory.titleYear": "Energy by year",
    "energyHistory.description": "Three-year history grouped by calendar period; totals show the latest recorded period",
    "energyHistory.descriptionHour": "Hourly meter detail for the last 7 days; totals show the latest recorded hour",
    "energyHistory.descriptionDate": "Hourly totals from 0:00 to 24:00 for the selected calendar day",
    "energyHistory.view": "Energy history view",
    "energyHistory.selectDate": "Select day",
    "energyHistory.selectDateAria": "Select calendar day",
    "energyHistory.hour": "Hour",
    "energyHistory.date": "Date",
    "energyHistory.month": "Month",
    "energyHistory.year": "Year",
    "energyHistory.totalsAria": "Energy totals for the latest selected period",
    "energyHistory.totalsPeriodAria": "Energy totals for {period}",
    "energyHistory.consumption": "Power consumption",
    "energyHistory.solar": "Solar generation",
    "energyHistory.grid": "Grid draw",
    "energyHistory.kwhAwaiting": "kWh · awaiting data",
    "energyHistory.kwhPeriod": "kWh · {period}",
    "energyHistory.chartAria": "Energy history in kilowatt-hours",
    "energyHistory.awaiting": "Awaiting inverter energy readings",
    "energyHistory.unavailable": "Energy history temporarily unavailable",
    "runtime.minutes": "{minutes}m",
    "runtime.hoursMinutes": "{hours}h {minutes}m",
    "runtime.daysHours": "{days}d {hours}h",
    "inverter.state.bypass": "Bypass",
    "inverter.state.standby": "Standby",
    "inverter.state.initializing": "Initializing",
    "inverter.state.hybridPower": "Hybrid power",
    "inverter.state.pvGrid": "Solar + grid",
    "inverter.state.batteryGrid": "Battery + grid",
    "inverter.state.acBatteryCharging": "Grid charging",
    "inverter.state.pvBatteryCharging": "Solar charging",
    "inverter.state.fault": "Fault",
    "inverter.state.selfCheck": "Self-check",
    "inverter.state.firmwareUpdate": "Firmware update",
    "inverter.state.service": "Service mode",
    "inverter.state.inverterTest": "Inverter test",
    "inverter.state.pvTest": "Solar test",
    "inverter.state.dcdcTest": "DC/DC test",
    "inverter.state.testMode": "Test mode",
    "inverter.state.undefined": "Undefined",
    "inverter.state.unknown": "Unknown state",
    "fleet.summary": "Fleet summary",
    "fleet.rackSoc": "Rack SOC",
    "fleet.socAria": "Overall rack state of charge",
    "fleet.livePower": "Live power",
    "fleet.netPower": "Net rack power",
    "fleet.rackCurrent": "Rack current",
    "fleet.netCurrentDetail": "Net across all packs",
    "fleet.averageVoltage": "Average voltage",
    "fleet.averageVoltageDetail": "Across reporting packs",
    "fleet.capacityLeft": "Capacity left",
    "fleet.combinedCapacity": "Combined capacity",
    "fleet.capacityOf": "of {value}",
    "fleet.mosfetTemperature": "MOSFET temperature",
    "fleet.ambientTemperature": "Ambient temperature",
    "fleet.rackHealth": "Rack health",
    "fleet.peakUnavailable": "Peak unavailable",
    "fleet.peak": "Peak {value}",
    "fleet.nominal": "Nominal",
    "fleet.alert": "alert",
    "fleet.alerts": "alerts",
    "fleet.cellSpreadUnavailable": "Cell spread unavailable",
    "fleet.maxCellDelta": "Max cell Δ {value}",
    "fleet.chargingInput": "Charging input",
    "fleet.dischargeOutput": "Discharge output",
    "fleet.lastKnownPower": "Last known power",
    "flow.lastKnownReading": "Last known reading",
    "flow.charging": "Charging",
    "flow.chargingCurrent": "Charging · {current}",
    "flow.discharging": "Discharging",
    "flow.dischargingCurrent": "Discharging · {current}",
    "flow.standingBy": "Standing by",
    "flow.lastKnownRack": "Last known rack level",
    "flow.waitingRack": "Waiting for rack readings",
    "flow.rackCharging": "Rack charging",
    "flow.rackChargingCurrent": "Rack charging · {current}",
    "flow.rackDischarging": "Rack discharging",
    "flow.rackDischargingCurrent": "Rack discharging · {current}",
    "flow.balanced": "Balanced power flow",
    "flow.rackStandingBy": "Rack standing by",
    "battery.readings": "Battery readings",
    "battery.awaitingReadings": "Awaiting readings",
    "battery.defaultRackName": "Rack Battery {number}",
    "battery.defaultName": "Battery {number}",
    "battery.socAria": "{name} state of charge",
    "battery.voltage": "Voltage",
    "battery.current": "Current",
    "battery.power": "Power",
    "battery.cellDelta": "Cell Δ",
    "inventory.eyebrow": "Rack inventory",
    "inventory.title": "Battery details",
    "inventory.initialStatus": "3 configured",
    "inventory.battery": "Battery",
    "inventory.network": "Network",
    "inventory.hardware": "Hardware",
    "inventory.state": "State",
    "inventory.batteries": "batteries",
    "inventory.batterySingular": "battery",
    "inventory.noneConfigured": "No batteries configured",
    "inventory.wifiAddress": "Battery Wi-Fi address",
    "inventory.noDirectIp": "No direct IP recorded",
    "inventory.address": "Address {address}",
    "inventory.defaultHardware": "Eco-worthy battery",
    "inventory.defaultModel": "Eco-worthy server rack battery",
    "inventory.firmware": "Firmware {version}",
    "inventory.firmwarePending": "Firmware pending",
    "inventory.seen": "Seen {relative}",
    "inventory.notSeen": "Not seen yet",
    "workbench.aria": "Monitoring workbench",
    "history.eyebrow": "History",
    "history.powerTitle": "Power sources & demand",
    "history.powerDescription": "Direct rack power with inverter-measured grid, solar, and load on one timeline",
    "history.range": "Range",
    "history.seriesAria": "Visible power data",
    "history.grid": "Grid",
    "history.battery": "Battery rack",
    "history.solar": "Solar",
    "history.load": "Load",
    "history.directionNote": "Above zero: grid import and battery charging. Below zero: grid export and battery discharge.",
    "history.chartAria": "Overlaid power history chart",
    "history.unavailable": "Power history temporarily unavailable",
    "history.awaiting": "Awaiting inverter power history",
    "history.pointAria": "Power at {timestamp}: {values}",
    "history.importing": "importing",
    "history.exporting": "exporting",
    "history.charging": "charging",
    "history.discharging": "discharging",
    "history.generating": "generating",
    "history.consuming": "consuming",
    "metric.soc": "State of charge",
    "metric.packVoltage": "Pack voltage",
    "metric.packCurrent": "Pack current",
    "metric.livePower": "Live power",
    "metric.cellDelta": "Cell delta",
    "metric.mosfetTemperature": "MOSFET temperature",
    "metric.ambientTemperature": "Ambient temperature",
    "metric.voltageShort": "Voltage",
    "metric.currentShort": "Current",
    "metric.powerShort": "Power",
    "metric.mosfetShort": "MOSFET temp",
    "metric.ambientShort": "Ambient temp",
    "details.selectedPack": "Selected pack",
    "details.rack": "Rack",
    "details.noCellData": "No cell data",
    "details.cellTitle": "Cell {number}: {voltage}",
    "details.noTemperatureData": "No temperature data",
    "details.batteryId": "Battery ID",
    "details.ipAddress": "IP address",
    "details.model": "Model",
    "details.address": "Address",
    "details.state": "State",
    "details.soh": "SOH",
    "details.cycles": "Cycles",
    "details.remaining": "Remaining",
    "details.full": "Full",
    "details.chargeLimit": "Charge limit",
    "details.dischargeLimit": "Discharge limit",
    "details.firmware": "Firmware",
    "details.serial": "Serial",
    "events.eyebrow": "Alert log",
    "events.title": "Recent events",
    "events.none": "No recent events",
    "events.refreshFailed": "Events could not refresh",
    "logs.aria": "Logs and status",
    "storage.eyebrow": "Archive",
    "storage.title": "Three-year log",
    "storage.downloadCsv": "Download CSV",
    "storage.rows": "Rows",
    "storage.size": "Size",
    "storage.oldest": "Oldest",
    "storage.newest": "Newest",
    "storage.rawPayload": "Raw battery payload",
    "error.unknownRefresh": "Unknown refresh error",
    "error.requestTimeout": "Request timed out after {seconds} seconds",
    "error.browserOffline": "Browser network is offline",
    "operation.charging": "Charging",
    "operation.discharging": "Discharging",
    "operation.idle": "Idle",
    "operation.standby": "Standby",
    "operation.fault": "Fault",
    "operation.unknown": "Unknown",
  },
  vi: {
    "page.title": "Giám sát hệ thống pin",
    "app.title": "Giám sát hệ thống pin",
    "logo.alt": "Logo Tran T",
    "brand.builderDefault": "Hệ thống do Trần Thanh Tuân và con trai xây dựng",
    "brand.builder": "Hệ thống do {builder} và con trai xây dựng",
    "language.switchTitle": "Chuyển ngôn ngữ",
    "language.switchLabel": "Chuyển đổi giữa tiếng Anh và tiếng Việt",
    "theme.switchTitle": "Chuyển giao diện",
    "theme.switchLabel": "Chuyển đổi giữa giao diện sáng và tối",
    "status.starting": "Đang khởi động",
    "status.noReadings": "Chưa có dữ liệu",
    "status.connecting": "Đang kết nối bộ thu thập",
    "status.noLiveReadings": "Chưa có số liệu trực tiếp",
    "status.dataRelative": "Dữ liệu {relative}",
    "status.lastError": "Lỗi gần nhất: {message}",
    "status.archiveError": "Lỗi lưu trữ: {message}",
    "status.responding": "{online}/{total} pin đang phản hồi",
    "status.lastCollectorData": "Dữ liệu cuối từ bộ thu thập {relative}",
    "status.waitingFresh": "Đang chờ mẫu dữ liệu mới",
    "status.waitingReconnect": "Đang chờ bộ thu thập kết nối lại",
    "status.recoveryDelayed": "Khôi phục lưu trữ bị chậm: {message}",
    "status.archiveCurrent": "Kho lưu trữ đã cập nhật · {rows} dòng",
    "status.monitorOffline": "Ứng dụng giám sát ngoại tuyến",
    "status.dataStale": "Dữ liệu đã cũ",
    "status.lastDashboardUpdate": "Bảng điều khiển cập nhật lần cuối {relative}",
    "status.noDashboardResponse": "Bảng điều khiển không phản hồi",
    "status.refreshError": "Lỗi cập nhật: {message}",
    "status.pending": "Đang chờ",
    "status.online": "Trực tuyến",
    "status.needsAttention": "Cần kiểm tra",
    "status.disabled": "Đã tắt",
    "status.lastKnown": "Dữ liệu gần nhất",
    "status.waiting": "Đang chờ",
    "status.collectorOnline": "Bộ thu thập trực tuyến",
    "status.collectorDegraded": "Bộ thu thập suy giảm",
    "status.collectorStale": "Dữ liệu đã cũ",
    "status.collectorOffline": "Bộ thu thập ngoại tuyến",
    "status.collectorOnlineDescription": "Bộ thu thập và tất cả pin đã cấu hình đang phản hồi",
    "status.collectorDegradedDescription": "Bộ thu thập vẫn kết nối nhưng có pin cần kiểm tra",
    "status.collectorStaleDescription": "Đang hiển thị dữ liệu gần nhất trong lúc bộ thu thập kết nối lại",
    "status.collectorOfflineDescription": "Bộ thu thập không phản hồi trong thời gian cho phép",
    "common.waitingData": "Đang chờ dữ liệu",
    "common.waitingReadings": "Đang chờ số liệu",
    "common.notConfigured": "Chưa cấu hình",
    "common.recently": "gần đây",
    "rack.overview": "Tổng quan tủ pin",
    "rack.waitingStatus": "Đang chờ trạng thái tủ pin",
    "rack.batteries": "Pin",
    "rack.collector": "Bộ thu thập",
    "rack.defaultCollector": "Bộ thu thập Raspberry Pi",
    "rack.defaultConnection": "Modbus RTU qua RS485",
    "rack.bus": "Kết nối",
    "rack.allOnline": "Tất cả pin đang trực tuyến",
    "rack.onlineCount": "{online}/{expected} đang trực tuyến",
    "rack.pack": "bộ pin",
    "rack.packs": "bộ pin",
    "rack.reporting": "{count} đang báo dữ liệu",
    "energy.eyebrow": "Năng lượng trong nhà",
    "energy.title": "Dòng điện trong nhà",
    "energy.waiting": "Đang chờ dữ liệu năng lượng trực tiếp",
    "energy.waitingShort": "Đang chờ",
    "energy.sceneAria": "Mô phỏng ba chiều dòng điện giữa điện lưới, biến tần, tủ pin và phụ tải trong nhà",
    "energy.grid": "Điện lưới",
    "energy.inverter": "Biến tần",
    "energy.solar": "Điện mặt trời",
    "energy.storage": "Tủ pin",
    "energy.load": "Phụ tải nhà",
    "energy.direction": "Đường truyền quan sát",
    "energy.rate": "Công suất pin",
    "energy.charging": "Đang nạp tủ pin",
    "energy.discharging": "Đang cấp điện cho nhà",
    "energy.idle": "Hệ thống nhà đang chờ",
    "energy.stale": "Dòng điện trong nhà đã tạm dừng",
    "energy.toBattery": "Điện lưới → pin",
    "energy.fromBattery": "Pin → phụ tải",
    "energy.noTransfer": "Không truyền tải",
    "energy.unavailable": "Chưa có dữ liệu",
    "energy.unmetered": "Chưa đo",
    "energy.routing": "Đang truyền điện",
    "energy.standby": "Đang chờ",
    "energy.gridSupplying": "Điện lưới đang cấp điện cho nhà",
    "energy.solarSupplying": "Điện mặt trời đang cấp điện cho nhà",
    "energy.batterySupplying": "Pin đang cấp điện cho nhà",
    "energy.mixedSupply": "Nhiều nguồn đang cấp điện cho nhà",
    "energy.noActiveSource": "Không có nguồn điện đang hoạt động",
    "energy.sourceGrid": "{value} từ điện lưới",
    "energy.sourceSolar": "{value} từ điện mặt trời",
    "energy.sourceBattery": "{value} từ pin",
    "energy.gridExport": "{value} lên điện lưới",
    "energy.loadPhrase": "phụ tải nhà {value}",
    "energy.batteryChargingPhrase": "{value} đang nạp pin",
    "energy.batteryDischargingPhrase": "{value} từ pin",
    "energy.batteryIdlePhrase": "Pin đang nghỉ",
    "energy.batteryUnavailablePhrase": "Chưa có dữ liệu trực tiếp từ pin",
    "energy.runtimeRemaining": "còn khoảng {time} ở mức xả hiện tại",
    "energy.runtimeCallout": "còn khoảng {time}",
    "energy.liveDescription": "{sources} · {load} · {battery}",
    "energy.importing": "nhập {value}",
    "energy.exporting": "xuất {value}",
    "energy.chargingValue": "đang nạp {value}",
    "energy.dischargingValue": "đang xả {value}",
    "energy.pack": "bộ pin",
    "energy.packs": "bộ pin",
    "energy.chargingDescription": "Dữ liệu trực tiếp từ pin ghi nhận {rate} đang đi vào {packs}. Các đường điện mặt trời, điện lưới và phụ tải sẽ tạm dừng cho đến khi có dữ liệu từ biến tần.",
    "energy.dischargingDescription": "Dữ liệu trực tiếp từ pin ghi nhận {rate} đang rời {packs}. Chưa thể xác định nơi nhận điện cho đến khi có dữ liệu từ biến tần.",
    "energy.idleDescription": "Dữ liệu pin không ghi nhận truyền tải đáng kể. Chưa kết nối đồng hồ điện mặt trời, điện lưới và phụ tải.",
    "energy.staleDescription": "Dòng điện trong nhà tạm dừng cho đến khi có dữ liệu mới từ bộ thu thập.",
    "inverter.summary": "Tóm tắt biến tần",
    "inverter.eyebrow": "Biến tần trực tiếp",
    "inverter.title": "Renogy X 8K",
    "inverter.waiting": "Đang chờ dữ liệu biến tần",
    "inverter.identity": "{serial} · Giao thức {protocol}",
    "inverter.solar": "Hệ thống điện mặt trời",
    "inverter.solarToday": "{count} MPPT · hôm nay {energy}",
    "inverter.grid": "Điện lưới",
    "inverter.gridElectrical": "L1 {l1} · L2 {l2} · {frequency}",
    "inverter.load": "Phụ tải dự phòng",
    "inverter.loadDetail": "hôm nay {energy} · CT ngoài {external}",
    "inverter.battery": "Tủ pin",
    "inverter.batteryElectrical": "RS485 trực tiếp · {voltage} · {current} · {soc} · {temperature}",
    "inverter.batteryWaiting": "Đang chờ dữ liệu trực tiếp từ pin",
    "inverter.runtimeRemaining": "Thời gian cấp điện ước tính · {time} ở mức xả hiện tại",
    "inverter.thermal": "Nhiệt độ biến tần",
    "inverter.internalTemperature": "bên trong {value}",
    "inverter.thermalDetail": "Biến tần {inverter} · DC/DC {dcdc}",
    "inverter.healthNominal": "Không có cảnh báo hoặc lỗi",
    "inverter.healthAlerts": "{alarms} cảnh báo · {faults} lỗi",
    "inverter.lastError": "Lỗi gần nhất: {message}",
    "energyHistory.eyebrow": "Lịch sử năng lượng",
    "energyHistory.titleHour": "Năng lượng theo giờ",
    "energyHistory.titleDate": "Năng lượng trong một ngày",
    "energyHistory.titleDateFor": "Năng lượng ngày {date}",
    "energyHistory.titleMonth": "Năng lượng theo tháng",
    "energyHistory.titleYear": "Năng lượng theo năm",
    "energyHistory.description": "Lịch sử ba năm được nhóm theo kỳ; tổng số hiển thị kỳ mới nhất đã ghi nhận",
    "energyHistory.descriptionHour": "Chi tiết công tơ theo giờ trong 7 ngày qua; tổng số hiển thị giờ mới nhất đã ghi nhận",
    "energyHistory.descriptionDate": "Tổng năng lượng theo giờ từ 0:00 đến 24:00 trong ngày đã chọn",
    "energyHistory.view": "Chế độ xem lịch sử năng lượng",
    "energyHistory.selectDate": "Chọn ngày",
    "energyHistory.selectDateAria": "Chọn ngày trên lịch",
    "energyHistory.hour": "Giờ",
    "energyHistory.date": "Ngày",
    "energyHistory.month": "Tháng",
    "energyHistory.year": "Năm",
    "energyHistory.totalsAria": "Tổng năng lượng cho kỳ được chọn mới nhất",
    "energyHistory.totalsPeriodAria": "Tổng năng lượng cho {period}",
    "energyHistory.consumption": "Điện năng tiêu thụ",
    "energyHistory.solar": "Sản lượng mặt trời",
    "energyHistory.grid": "Điện lấy từ lưới",
    "energyHistory.kwhAwaiting": "kWh · đang chờ dữ liệu",
    "energyHistory.kwhPeriod": "kWh · {period}",
    "energyHistory.chartAria": "Biểu đồ lịch sử năng lượng theo kilowatt-giờ",
    "energyHistory.awaiting": "Đang chờ số liệu năng lượng từ biến tần",
    "energyHistory.unavailable": "Lịch sử năng lượng tạm thời không khả dụng",
    "runtime.minutes": "{minutes} phút",
    "runtime.hoursMinutes": "{hours} giờ {minutes} phút",
    "runtime.daysHours": "{days} ngày {hours} giờ",
    "inverter.state.bypass": "Điện lưới chuyển thẳng",
    "inverter.state.standby": "Đang chờ",
    "inverter.state.initializing": "Đang khởi tạo",
    "inverter.state.hybridPower": "Nguồn điện hỗn hợp",
    "inverter.state.pvGrid": "Mặt trời + điện lưới",
    "inverter.state.batteryGrid": "Pin + điện lưới",
    "inverter.state.acBatteryCharging": "Điện lưới nạp pin",
    "inverter.state.pvBatteryCharging": "Điện mặt trời nạp pin",
    "inverter.state.fault": "Có lỗi",
    "inverter.state.selfCheck": "Đang tự kiểm tra",
    "inverter.state.firmwareUpdate": "Đang cập nhật phần mềm",
    "inverter.state.service": "Chế độ bảo trì",
    "inverter.state.inverterTest": "Kiểm tra biến tần",
    "inverter.state.pvTest": "Kiểm tra điện mặt trời",
    "inverter.state.dcdcTest": "Kiểm tra DC/DC",
    "inverter.state.testMode": "Chế độ kiểm tra",
    "inverter.state.undefined": "Chưa xác định",
    "inverter.state.unknown": "Trạng thái không xác định",
    "fleet.summary": "Tóm tắt tủ pin",
    "fleet.rackSoc": "SOC tủ pin",
    "fleet.socAria": "Mức sạc tổng thể của tủ pin",
    "fleet.livePower": "Công suất tức thời",
    "fleet.netPower": "Công suất ròng toàn tủ",
    "fleet.rackCurrent": "Dòng điện toàn tủ",
    "fleet.netCurrentDetail": "Tổng ròng của mọi bộ pin",
    "fleet.averageVoltage": "Điện áp trung bình",
    "fleet.averageVoltageDetail": "Trên các bộ pin đang báo dữ liệu",
    "fleet.capacityLeft": "Dung lượng còn lại",
    "fleet.combinedCapacity": "Tổng dung lượng",
    "fleet.capacityOf": "trên {value}",
    "fleet.mosfetTemperature": "Nhiệt độ MOSFET",
    "fleet.ambientTemperature": "Nhiệt độ môi trường",
    "fleet.rackHealth": "Tình trạng tủ pin",
    "fleet.peakUnavailable": "Chưa có nhiệt độ đỉnh",
    "fleet.peak": "Đỉnh {value}",
    "fleet.nominal": "Bình thường",
    "fleet.alert": "cảnh báo",
    "fleet.alerts": "cảnh báo",
    "fleet.cellSpreadUnavailable": "Chưa có độ lệch cell",
    "fleet.maxCellDelta": "Độ lệch cell tối đa {value}",
    "fleet.chargingInput": "Công suất sạc vào",
    "fleet.dischargeOutput": "Công suất xả ra",
    "fleet.lastKnownPower": "Công suất gần nhất",
    "flow.lastKnownReading": "Số liệu gần nhất",
    "flow.charging": "Đang sạc",
    "flow.chargingCurrent": "Đang sạc · {current}",
    "flow.discharging": "Đang xả",
    "flow.dischargingCurrent": "Đang xả · {current}",
    "flow.standingBy": "Đang chờ",
    "flow.lastKnownRack": "Mức tủ pin gần nhất",
    "flow.waitingRack": "Đang chờ số liệu tủ pin",
    "flow.rackCharging": "Tủ pin đang sạc",
    "flow.rackChargingCurrent": "Tủ pin đang sạc · {current}",
    "flow.rackDischarging": "Tủ pin đang xả",
    "flow.rackDischargingCurrent": "Tủ pin đang xả · {current}",
    "flow.balanced": "Dòng năng lượng cân bằng",
    "flow.rackStandingBy": "Tủ pin đang chờ",
    "battery.readings": "Số liệu pin",
    "battery.awaitingReadings": "Đang chờ số liệu",
    "battery.defaultRackName": "Pin {number}",
    "battery.defaultName": "Pin {number}",
    "battery.socAria": "Mức sạc của {name}",
    "battery.voltage": "Điện áp",
    "battery.current": "Dòng điện",
    "battery.power": "Công suất",
    "battery.cellDelta": "Độ lệch cell",
    "inventory.eyebrow": "Danh sách tủ pin",
    "inventory.title": "Chi tiết pin",
    "inventory.initialStatus": "Đã cấu hình 3 pin",
    "inventory.battery": "Pin",
    "inventory.network": "Mạng",
    "inventory.hardware": "Phần cứng",
    "inventory.state": "Trạng thái",
    "inventory.batteries": "pin",
    "inventory.batterySingular": "pin",
    "inventory.noneConfigured": "Chưa cấu hình pin",
    "inventory.wifiAddress": "Địa chỉ Wi-Fi của pin",
    "inventory.noDirectIp": "Chưa ghi nhận IP trực tiếp",
    "inventory.address": "Địa chỉ {address}",
    "inventory.defaultHardware": "Pin Eco-worthy",
    "inventory.defaultModel": "Pin tủ máy chủ Eco-worthy",
    "inventory.firmware": "Firmware {version}",
    "inventory.firmwarePending": "Đang chờ firmware",
    "inventory.seen": "Ghi nhận {relative}",
    "inventory.notSeen": "Chưa ghi nhận",
    "workbench.aria": "Bảng điều khiển giám sát",
    "history.eyebrow": "Lịch sử",
    "history.powerTitle": "Nguồn điện & nhu cầu",
    "history.powerDescription": "Công suất tủ pin trực tiếp cùng dữ liệu lưới, mặt trời và tải từ biến tần",
    "history.range": "Khoảng thời gian",
    "history.seriesAria": "Dữ liệu công suất đang hiển thị",
    "history.grid": "Lưới điện",
    "history.battery": "Tủ pin",
    "history.solar": "Mặt trời",
    "history.load": "Tải",
    "history.directionNote": "Trên 0: lấy điện lưới và sạc pin. Dưới 0: phát điện lên lưới và xả pin.",
    "history.chartAria": "Biểu đồ chồng lịch sử công suất",
    "history.unavailable": "Lịch sử công suất tạm thời không khả dụng",
    "history.awaiting": "Đang chờ lịch sử công suất biến tần",
    "history.pointAria": "Công suất lúc {timestamp}: {values}",
    "history.importing": "đang lấy điện",
    "history.exporting": "đang phát điện",
    "history.charging": "đang sạc",
    "history.discharging": "đang xả",
    "history.generating": "đang phát",
    "history.consuming": "đang tiêu thụ",
    "metric.soc": "Mức sạc",
    "metric.packVoltage": "Điện áp bộ pin",
    "metric.packCurrent": "Dòng điện bộ pin",
    "metric.livePower": "Công suất tức thời",
    "metric.cellDelta": "Độ lệch cell",
    "metric.mosfetTemperature": "Nhiệt độ MOSFET",
    "metric.ambientTemperature": "Nhiệt độ môi trường",
    "metric.voltageShort": "Điện áp",
    "metric.currentShort": "Dòng điện",
    "metric.powerShort": "Công suất",
    "metric.mosfetShort": "Nhiệt độ MOSFET",
    "metric.ambientShort": "Nhiệt độ môi trường",
    "details.selectedPack": "Bộ pin đang chọn",
    "details.rack": "Toàn tủ",
    "details.noCellData": "Chưa có dữ liệu cell",
    "details.cellTitle": "Cell {number}: {voltage}",
    "details.noTemperatureData": "Chưa có dữ liệu nhiệt độ",
    "details.batteryId": "Mã pin",
    "details.ipAddress": "Địa chỉ IP",
    "details.model": "Model",
    "details.address": "Địa chỉ",
    "details.state": "Trạng thái",
    "details.soh": "SOH",
    "details.cycles": "Chu kỳ",
    "details.remaining": "Còn lại",
    "details.full": "Đầy",
    "details.chargeLimit": "Giới hạn sạc",
    "details.dischargeLimit": "Giới hạn xả",
    "details.firmware": "Firmware",
    "details.serial": "Số sê-ri",
    "events.eyebrow": "Nhật ký cảnh báo",
    "events.title": "Sự kiện gần đây",
    "events.none": "Không có sự kiện gần đây",
    "events.refreshFailed": "Không thể cập nhật sự kiện",
    "logs.aria": "Nhật ký và trạng thái",
    "storage.eyebrow": "Lưu trữ",
    "storage.title": "Nhật ký ba năm",
    "storage.downloadCsv": "Tải CSV",
    "storage.rows": "Số dòng",
    "storage.size": "Dung lượng",
    "storage.oldest": "Cũ nhất",
    "storage.newest": "Mới nhất",
    "storage.rawPayload": "Dữ liệu pin thô",
    "error.unknownRefresh": "Lỗi cập nhật không xác định",
    "error.requestTimeout": "Yêu cầu hết thời gian sau {seconds} giây",
    "error.browserOffline": "Trình duyệt đang mất kết nối mạng",
    "operation.charging": "Đang sạc",
    "operation.discharging": "Đang xả",
    "operation.idle": "Không tải",
    "operation.standby": "Đang chờ",
    "operation.fault": "Lỗi",
    "operation.unknown": "Không xác định",
  },
};

const powerHistorySeries = [
  { field: "grid_power_w", labelKey: "history.grid", color: "#0a84ff" },
  { field: "battery_power_w", labelKey: "history.battery", color: "#bf5af2" },
  { field: "solar_power_w", labelKey: "history.solar", color: "#30b95f" },
  { field: "load_power_w", labelKey: "history.load", color: "#ff7a00" },
];
const energySeries = [
  { field: "consumption_kwh", color: "#ff7a00" },
  { field: "solar_generation_kwh", color: "#30b95f" },
  { field: "grid_import_kwh", color: "#0a84ff" },
];

const $ = (id) => document.getElementById(id);
const THEME_STORAGE_KEY = "battery-monitor-theme";
const LANGUAGE_STORAGE_KEY = "battery-monitor-language";
const LIVE_REFRESH_MS = 5000;
const SECONDARY_REFRESH_MS = 30000;
const REQUEST_TIMEOUT_MS = 8000;
const UI_OFFLINE_AFTER_MS = 120000;
const requestControllers = new Map();
let schedulerTimer = null;
let chartResizeFrame = null;
let energyChartResizeFrame = null;
let chartPointerFrame = null;
let chartAnimationFrame = null;

function t(key, values = {}) {
  const table = translations[state.language] || translations.en;
  const template = table[key] ?? translations.en[key] ?? key;
  return String(template).replace(/\{(\w+)\}/g, (match, name) =>
    Object.hasOwn(values, name) ? String(values[name]) : match,
  );
}

function currentLocale() {
  return state.language === "vi" ? "vi-VN" : "en-US";
}

function localCalendarDateValue(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function applyStaticTranslations() {
  document.title = t("page.title");
  document.querySelectorAll("[data-i18n]").forEach((element) => {
    element.textContent = t(element.dataset.i18n);
  });
  document.querySelectorAll("[data-i18n-title]").forEach((element) => {
    element.title = t(element.dataset.i18nTitle);
  });
  document.querySelectorAll("[data-i18n-aria-label]").forEach((element) => {
    element.setAttribute("aria-label", t(element.dataset.i18nAriaLabel));
  });
  document.querySelectorAll("[data-i18n-alt]").forEach((element) => {
    element.setAttribute("alt", t(element.dataset.i18nAlt));
  });
}

async function refreshCycle(forceSecondary = false) {
  if (document.hidden || state.refreshInProgress) return;
  state.refreshInProgress = true;
  try {
    const now = Date.now();
    const jobs = [["live", refreshLive()]];
    if (forceSecondary || now - state.lastHistoryRefreshAt >= SECONDARY_REFRESH_MS) {
      jobs.push(["history", refreshHistory()]);
    }
    if (forceSecondary || now - state.lastEnergyRefreshAt >= SECONDARY_REFRESH_MS) {
      jobs.push(["energy", refreshEnergyHistory()]);
    }
    if (forceSecondary || now - state.lastEventsRefreshAt >= SECONDARY_REFRESH_MS) {
      jobs.push(["events", refreshEvents()]);
    }

    const results = await Promise.allSettled(jobs.map(([, promise]) => promise));
    results.forEach((result, index) => {
      if (result.status === "rejected") {
        handleResourceFailure(jobs[index][0], result.reason);
      }
    });
  } finally {
    state.refreshInProgress = false;
    scheduleNextRefresh();
  }
}

async function refreshLive() {
  const payload = await getJson("/api/live", "live");
  state.livePayload = payload;
  state.batteries = payload.snapshot?.batteries || [];
  state.inverter = payload.snapshot?.inverter || null;
  state.storage = payload.storage || {};
  state.rack = payload.rack || {};
  state.summary = payload.summary || {};
  state.collectorState = payload.collector_status || "offline";
  state.collectorOnline = ["online", "degraded"].includes(state.collectorState);
  state.lastLiveReceivedAt = Date.now();
  state.resourceErrors.live = null;
  if (!state.selectedBatteryId && state.batteries.length) {
    state.selectedBatteryId = state.batteries[0].id;
  }
  renderStatus(payload);
  renderRackOverview();
  renderSummary(state.summary);
  renderInverterTelemetry();
  renderBatteryCards();
  renderBatteryInventory();
  renderSelectedBattery();
  renderStorage();
}

async function refreshHistory() {
  const requestedRange = state.range;
  const params = new URLSearchParams({ range: requestedRange });
  const payload = await getJson(`/api/power-history?${params}`, "history");
  if (requestedRange !== state.range) {
    return refreshHistory();
  }
  state.history = payload.points || [];
  state.lastHistoryRefreshAt = Date.now();
  state.resourceErrors.history = null;
  $("historyChart").removeAttribute("data-refresh-error");
  $("chartTitle").textContent = t("history.powerTitle");
  state.chartHover = null;
  hideChartTooltip(false);
  animateChartIn();
}

async function refreshEnergyHistory() {
  const requestedView = state.energyView;
  const requestedDate = state.energyDate;
  const params = new URLSearchParams({ view: requestedView });
  if (requestedView === "date") {
    params.set("date", requestedDate);
    params.set("timezone", state.energyTimezone);
  }
  const payload = await getJson(`/api/energy?${params}`, "energy");
  if (
    requestedView !== state.energyView ||
    (requestedView === "date" && requestedDate !== state.energyDate)
  ) {
    return refreshEnergyHistory();
  }
  state.energyHistory = Array.isArray(payload.points) ? payload.points : [];
  state.energyWindowStart = finiteNumber(payload.window_start_unix);
  state.energyWindowEnd = finiteNumber(payload.window_end_unix);
  if (requestedView === "date") {
    state.energyDate = payload.selected_date || requestedDate;
    state.energySummaryPeriod = {
      period: state.energyDate,
      timestamp: payload.window_start,
      unix: state.energyWindowStart,
    };
    state.energySummary = payload.totals || sumEnergyHistoryPoints(state.energyHistory);
  } else {
    state.energySummaryPeriod = latestEnergyHistoryPoint(state.energyHistory);
    state.energySummary = state.energySummaryPeriod || {};
  }
  state.lastEnergyRefreshAt = Date.now();
  state.resourceErrors.energy = null;
  $("energyHistoryChart").removeAttribute("data-refresh-error");
  renderEnergyHistory();
}

async function refreshEvents() {
  const payload = await getJson("/api/events?range=7d&limit=80", "events");
  state.events = payload.events || [];
  state.lastEventsRefreshAt = Date.now();
  state.resourceErrors.events = null;
  $("eventList").removeAttribute("data-refresh-error");
  renderEvents(state.events);
}

async function getJson(url, resource) {
  requestControllers.get(resource)?.abort();
  const controller = new AbortController();
  requestControllers.set(resource, controller);
  const timeout = window.setTimeout(() => {
    controller.abort(new DOMException("Request timed out", "TimeoutError"));
  }, REQUEST_TIMEOUT_MS);

  try {
    const response = await fetch(url, {
      headers: { Accept: "application/json", "Cache-Control": "no-cache" },
      cache: "no-store",
      signal: controller.signal,
    });
    if (!response.ok) {
      throw new Error(`${response.status} ${response.statusText}`);
    }
    return await response.json();
  } catch (error) {
    if (controller.signal.reason?.name === "TimeoutError") {
      throw new Error(t("error.requestTimeout", { seconds: REQUEST_TIMEOUT_MS / 1000 }));
    }
    throw error;
  } finally {
    window.clearTimeout(timeout);
    if (requestControllers.get(resource) === controller) {
      requestControllers.delete(resource);
    }
  }
}

function renderStatus(payload) {
  const pill = $("collectorStatus");
  const presentation = connectionPresentation(payload.collector_status);
  pill.textContent = presentation.label;
  pill.className = `status-pill ${presentation.className}`;
  pill.title = payload.collector_error || presentation.description;

  const lastData = payload.monitor?.last_data_at || payload.monitor?.last_success_at;
  $("lastUpdated").textContent = lastData
    ? t("status.dataRelative", { relative: formatRelativeTime(lastData) })
    : t("status.noLiveReadings");

  const detail = $("connectionDetail");
  if (payload.collector_error) {
    detail.textContent = t("status.lastError", { message: payload.collector_error });
  } else if (payload.monitor?.storage_error) {
    detail.textContent = t("status.archiveError", { message: payload.monitor.storage_error });
  } else if (payload.collector_status === "degraded") {
    const summary = payload.summary || {};
    detail.textContent = t("status.responding", {
      online: summary.online_count || 0,
      total: summary.battery_count || 0,
    });
  } else if (payload.collector_status === "stale") {
    detail.textContent = lastData
      ? t("status.lastCollectorData", { relative: formatRelativeTime(lastData) })
      : t("status.waitingFresh");
  } else if (payload.collector_status === "offline") {
    detail.textContent = t("status.waitingReconnect");
  } else if (payload.monitor?.backfill_error) {
    detail.textContent = t("status.recoveryDelayed", { message: payload.monitor.backfill_error });
  } else {
    detail.textContent = t("status.archiveCurrent", {
      rows: formatNumber(payload.storage?.row_count || 0),
    });
  }
}

function handleResourceFailure(resource, error) {
  if (error?.name === "AbortError") return;
  const message = error?.message || String(error || t("error.unknownRefresh"));
  state.resourceErrors[resource] = message;

  if (resource === "live") {
    renderLiveFailure(message);
    return;
  }
  if (resource === "history") {
    $("historyChart").dataset.refreshError = message;
    drawChart();
    return;
  }
  if (resource === "energy") {
    $("energyHistoryChart").dataset.refreshError = message;
    renderEnergyHistory();
    return;
  }
  $("eventList").dataset.refreshError = message;
  if (!$("eventList").children.length) {
    $("eventList").innerHTML = `<div class="empty-mini">${escapeHtml(t("events.refreshFailed"))}</div>`;
  }
}

function renderLiveFailure(message) {
  const age = state.lastLiveReceivedAt ? Date.now() - state.lastLiveReceivedAt : Infinity;
  const status = age >= UI_OFFLINE_AFTER_MS ? "offline" : "stale";
  const presentation = connectionPresentation(status);
  state.collectorOnline = false;
  $("collectorStatus").textContent = status === "offline"
    ? t("status.monitorOffline")
    : t("status.dataStale");
  $("collectorStatus").className = `status-pill ${presentation.className}`;
  $("collectorStatus").title = message;
  $("lastUpdated").textContent = state.lastLiveReceivedAt
    ? t("status.lastDashboardUpdate", {
        relative: formatRelativeTime(new Date(state.lastLiveReceivedAt).toISOString()),
      })
    : t("status.noDashboardResponse");
  $("connectionDetail").textContent = t("status.refreshError", { message });
  renderBatteryCards();
  renderBatteryInventory();
  renderSelectedBattery();
  renderEnergyFlow({ mode: "stale", label: t("flow.lastKnownRack") });
  renderInverterTelemetry();
}

function scheduleNextRefresh(delay = LIVE_REFRESH_MS) {
  window.clearTimeout(schedulerTimer);
  if (document.hidden) return;
  schedulerTimer = window.setTimeout(() => refreshCycle(false), delay);
}

function abortActiveRequests() {
  requestControllers.forEach((controller) => controller.abort());
  requestControllers.clear();
}

function renderSummary(summary) {
  const rackSoc = finiteNumber(summary.average_soc_percent);
  const flow = rackEnergyFlow(state.batteries);
  $("fleetSoc").textContent = formatValue(rackSoc, "%");
  $("fleetFlow").textContent = flow.label;
  updateSocProgress($("fleetSocBar"), rackSoc, flow.mode);
  $("fleetPower").textContent = formatValue(summary.total_power_w, "W");
  $("fleetPowerDetail").textContent = rackPowerDetail(flow.mode);
  $("fleetCurrent").textContent = formatValue(summary.total_current_a, "A");
  $("fleetVoltage").textContent = formatValue(summary.average_voltage_v, "V", 2);
  $("fleetCapacity").textContent = formatValue(summary.remaining_capacity_ah, "Ah");
  $("fleetCapacityDetail").textContent = finiteNumber(summary.full_capacity_ah) === null
    ? t("fleet.combinedCapacity")
    : t("fleet.capacityOf", { value: formatValue(summary.full_capacity_ah, "Ah") });
  $("fleetMosfetTemp").textContent = formatValue(summary.average_mosfet_temperature_c, "°C");
  $("fleetMosfetPeak").textContent = temperaturePeakLabel(summary.maximum_mosfet_temperature_c);
  $("fleetAmbientTemp").textContent = formatValue(summary.average_ambient_temperature_c, "°C");
  $("fleetAmbientPeak").textContent = temperaturePeakLabel(summary.maximum_ambient_temperature_c);
  const alerts = (summary.alarm_count || 0) + (summary.fault_count || 0);
  $("fleetHealth").textContent = alerts
    ? `${formatNumber(alerts)} ${t(alerts === 1 ? "fleet.alert" : "fleet.alerts")}`
    : t("fleet.nominal");
  $("fleetHealthMetric").classList.toggle("has-alerts", alerts > 0);
  $("fleetCellDelta").textContent = finiteNumber(summary.maximum_cell_voltage_delta_v) === null
    ? t("fleet.cellSpreadUnavailable")
    : t("fleet.maxCellDelta", {
        value: formatValue(summary.maximum_cell_voltage_delta_v, "V", 3),
      });
  renderEnergyFlow(flow);
}

function renderEnergyFlow(flow) {
  const section = $("energyFlowSection");
  if (!section) return;

  const rackMode = ["charging", "discharging", "idle", "stale"].includes(flow?.mode)
    ? flow.mode
    : "stale";
  const inverter = inverterTelemetry();
  const battery = rackBatteryTelemetry();
  const mode = battery.available ? batteryPowerMode(battery.power, rackMode) : "stale";
  const current = battery.current;
  const power = battery.power;
  const soc = battery.soc;
  const runtime = formatBatteryRuntime(battery.runtimeHours);
  const batteryCount = battery.count;
  const packTelemetry = state.batteries.slice(0, 3).map((battery) => {
    const reading = battery.last_reading || {};
    const reporting = state.collectorOnline && battery.status === "ok" && Boolean(battery.last_reading);
    return {
      id: battery.id,
      mode: energyFlowPresentation(reading, reporting).mode,
      current: finiteNumber(reading.current_a),
      power: finiteNumber(reading.power_w),
      soc: finiteNumber(reading.soc_percent),
      reporting,
    };
  });
  const rate = power === null ? t("energy.unavailable") : formatPower(Math.abs(power));
  const packs = `${formatNumber(batteryCount)} ${t(batteryCount === 1 ? "energy.pack" : "energy.packs")}`;

  let titleKey = "energy.stale";
  let descriptionKey = "energy.staleDescription";
  let descriptionValues = { rate, packs };
  if (inverter.available) {
    const activeSources = [];
    if ((inverter.solarPower ?? 0) > 25) {
      activeSources.push({ key: "solar", text: t("energy.sourceSolar", { value: formatPower(inverter.solarPower) }) });
    }
    if ((inverter.gridPower ?? 0) > 25) {
      activeSources.push({ key: "grid", text: t("energy.sourceGrid", { value: formatPower(inverter.gridPower) }) });
    }
    if (battery.available && (power ?? 0) < -25) {
      activeSources.push({ key: "battery", text: t("energy.sourceBattery", { value: formatPower(Math.abs(power)) }) });
    }

    if (activeSources.length > 1) titleKey = "energy.mixedSupply";
    else if (activeSources[0]?.key === "solar") titleKey = "energy.solarSupplying";
    else if (activeSources[0]?.key === "grid") titleKey = "energy.gridSupplying";
    else if (activeSources[0]?.key === "battery") titleKey = "energy.batterySupplying";
    else titleKey = "energy.idle";

    const sourceParts = activeSources.map((source) => source.text);
    if ((inverter.gridPower ?? 0) < -25) {
      sourceParts.push(t("energy.gridExport", { value: formatPower(Math.abs(inverter.gridPower)) }));
    }
    const batteryPhrase = !battery.available
      ? t("energy.batteryUnavailablePhrase")
      : (power ?? 0) > 25
        ? t("energy.batteryChargingPhrase", { value: formatPower(power) })
        : (power ?? 0) < -25
          ? t("energy.batteryDischargingPhrase", { value: formatPower(Math.abs(power)) })
          : t("energy.batteryIdlePhrase");
    descriptionKey = "energy.liveDescription";
    descriptionValues = {
      sources: sourceParts.join(" + ") || t("energy.noActiveSource"),
      load: t("energy.loadPhrase", { value: formatPower(inverter.loadPower) }),
      battery: batteryPhrase,
    };
  } else if (mode === "charging") {
    titleKey = "energy.charging";
    descriptionKey = "energy.chargingDescription";
  } else if (mode === "discharging") {
    titleKey = "energy.discharging";
    descriptionKey = "energy.dischargingDescription";
  } else if (mode === "idle") {
    titleKey = "energy.idle";
    descriptionKey = "energy.idleDescription";
  }

  section.dataset.mode = mode;
  section.dataset.current = String(current ?? 0);
  section.dataset.power = String(power ?? 0);
  section.dataset.soc = String(soc ?? 0);
  section.dataset.batteryCount = String(batteryCount);
  section.dataset.packTelemetry = JSON.stringify(packTelemetry);
  section.dataset.batterySource = "direct-battery-telemetry";
  section.dataset.inverterAvailable = String(inverter.available);
  section.dataset.gridPower = String(inverter.gridPower ?? 0);
  section.dataset.solarPower = String(inverter.solarPower ?? 0);
  section.dataset.loadPower = String(inverter.loadPower ?? 0);
  section.dataset.batteryPower = String(power ?? 0);
  section.dataset.batteryRuntimeHours = String(battery.runtimeHours ?? 0);
  section.dataset.gridActive = String(inverter.available && Math.abs(inverter.gridPower ?? 0) > 25);
  section.dataset.gridDirection = (inverter.gridPower ?? 0) < 0 ? "export" : "import";
  section.dataset.solarActive = String(inverter.available && (inverter.solarPower ?? 0) > 25);
  section.dataset.loadActive = String(inverter.available && (inverter.loadPower ?? 0) > 25);
  section.dataset.batteryActive = String(
    battery.available && (Math.abs(power ?? 0) > 25 || mode === "charging" || mode === "discharging"),
  );
  $("energyFlowTitle").textContent = t("energy.title");
  $("energyFlowState").textContent = t(titleKey);
  const runtimeText = runtime
    ? t("energy.runtimeRemaining", { time: runtime })
    : null;
  $("energyFlowDescription").textContent = [
    t(descriptionKey, descriptionValues),
    runtimeText,
  ].filter(Boolean).join(" · ");
  $("energyGridValue").textContent = inverter.available
    ? formatGridPower(inverter.gridPower)
    : t("energy.unmetered");
  $("energySolarValue").textContent = inverter.available
    ? formatPower(inverter.solarPower)
    : t("energy.unmetered");
  $("energyLoadValue").textContent = inverter.available
    ? formatPower(inverter.loadPower)
    : t("energy.unmetered");
  $("energyInverterValue").textContent = inverter.available
    ? inverterStateLabel(inverter.reading.system_state || inverter.reading.inverter_state)
    : mode === "stale"
      ? t("energy.unavailable")
      : mode === "charging" || mode === "discharging"
        ? t("energy.routing")
        : t("energy.standby");
  const socLabel = soc === null ? null : formatValue(soc, "%");
  $("energyBatteryValue").textContent = mode === "stale"
    ? t("energy.unavailable")
    : [socLabel, formatBatteryPower(power)]
        .filter(Boolean)
        .join(" · ");
  const energyRuntime = $("energyBatteryRuntime");
  energyRuntime.hidden = !runtimeText;
  energyRuntime.textContent = runtime
    ? t("energy.runtimeCallout", { time: runtime })
    : "";

  window.dispatchEvent(new CustomEvent("battery-energy-flow", {
    detail: {
      mode,
      current,
      power,
      soc,
      batteryCount,
      packs: packTelemetry,
      batterySource: "direct-battery-telemetry",
      inverterAvailable: inverter.available,
      gridPower: inverter.gridPower,
      solarPower: inverter.solarPower,
      loadPower: inverter.loadPower,
      batteryPower: power,
      batteryRuntimeHours: battery.runtimeHours,
    },
  }));
}

function renderInverterTelemetry() {
  const band = $("inverterBand");
  if (!band) return;

  const telemetry = inverterTelemetry();
  const battery = rackBatteryTelemetry();
  const inverter = telemetry.inverter;
  const reading = telemetry.reading;
  const hasReading = telemetry.hasReading;
  const effectiveStatus = !state.collectorOnline && hasReading
    ? "stale"
    : telemetry.available
      ? inverter?.status || "ok"
      : inverter?.status || "pending";
  const statusForPresentation = effectiveStatus === "degraded" ? "error" : effectiveStatus;
  const presentation = statusPresentation(statusForPresentation);
  const status = $("inverterStatus");
  status.textContent = presentation.label;
  status.className = `status-pill ${presentation.className}`;
  band.dataset.status = effectiveStatus;

  $("inverterName").textContent = inverter?.model || reading.model || t("inverter.title");
  $("inverterState").textContent = hasReading
    ? inverterStateLabel(reading.system_state || reading.inverter_state)
    : t("inverter.waiting");
  $("inverterIdentity").textContent = hasReading
    ? t("inverter.identity", {
        serial: reading.serial_number || "--",
        protocol: reading.protocol_version || "--",
      })
    : t("inverter.waiting");
  $("inverterConnection").textContent = inverter?.connection || t("common.notConfigured");

  const alarmCount = Array.isArray(reading.active_alarms) ? reading.active_alarms.length : 0;
  const faultCount = Array.isArray(reading.active_faults) ? reading.active_faults.length : 0;
  $("inverterHealth").textContent = inverter?.last_error
    ? t("inverter.lastError", { message: inverter.last_error })
    : alarmCount || faultCount
      ? t("inverter.healthAlerts", {
          alarms: formatNumber(alarmCount),
          faults: formatNumber(faultCount),
        })
      : hasReading
        ? t("inverter.healthNominal")
        : t("inverter.waiting");
  $("inverterIdentityCell").classList.toggle("has-alerts", alarmCount + faultCount > 0 || Boolean(inverter?.last_error));

  $("inverterSolarPower").textContent = formatPower(telemetry.solarPower);
  $("inverterSolarDetail").textContent = hasReading
    ? t("inverter.solarToday", {
        count: formatNumber(Array.isArray(reading.pv_inputs) ? reading.pv_inputs.length : 0),
        energy: formatEnergy(reading.pv_energy_today_kwh),
      })
    : t("inverter.waiting");
  $("inverterGridPower").textContent = formatGridPower(telemetry.gridPower);
  $("inverterGridDetail").textContent = hasReading
    ? t("inverter.gridElectrical", {
        l1: formatValue(reading.grid_l1_voltage_v, "V"),
        l2: formatValue(reading.grid_l2_voltage_v, "V"),
        frequency: formatValue(reading.grid_frequency_hz, "Hz", 2),
      })
    : t("inverter.waiting");
  $("inverterLoadPower").textContent = formatPower(telemetry.loadPower);
  $("inverterLoadDetail").textContent = hasReading
    ? t("inverter.loadDetail", {
        energy: formatEnergy(reading.load_energy_today_kwh),
        external: formatPower(telemetry.externalLoadPower),
      })
    : t("inverter.waiting");
  $("inverterBatteryPower").textContent = battery.available
    ? formatBatteryPower(battery.power)
    : "--";
  $("inverterBatteryDetail").textContent = battery.available
    ? t("inverter.batteryElectrical", {
        voltage: formatValue(battery.voltage, "V"),
        current: formatValue(battery.current, "A"),
        soc: formatValue(battery.soc, "%"),
        temperature: formatValue(battery.temperature, "°C"),
      })
    : t("inverter.batteryWaiting");
  const runtime = formatBatteryRuntime(battery.runtimeHours);
  const inverterRuntime = $("inverterBatteryRuntime");
  inverterRuntime.hidden = !runtime;
  inverterRuntime.textContent = runtime
    ? t("inverter.runtimeRemaining", { time: runtime })
    : "";
  $("inverterThermalValue").textContent = hasReading
    ? t("inverter.internalTemperature", {
        value: formatValue(reading.internal_temperature_c, "°C"),
      })
    : "--";
  $("inverterThermalDetail").textContent = hasReading
    ? t("inverter.thermalDetail", {
        inverter: formatValue(reading.inverter_temperature_c, "°C"),
        dcdc: formatValue(reading.dcdc_temperature_c, "°C"),
      })
    : t("inverter.waiting");
}

function inverterTelemetry(inverter = state.inverter) {
  const reading = inverter?.last_reading && typeof inverter.last_reading === "object"
    ? inverter.last_reading
    : {};
  const hasReading = Boolean(reading.timestamp);
  const available = Boolean(
    state.collectorOnline
      && inverter
      && ["ok", "degraded"].includes(inverter.status)
      && hasReading,
  );
  const gridImport = finiteNumber(reading.grid_import_power_w);
  const gridExport = finiteNumber(reading.grid_export_power_w);
  const gridTotal = finiteNumber(reading.grid_total_power_w);
  const gridPower = gridImport !== null || gridExport !== null
    ? (gridImport ?? 0) - (gridExport ?? 0)
    : gridTotal === null
      ? null
      : -gridTotal;

  return {
    available,
    hasReading,
    inverter,
    reading,
    gridPower,
    solarPower: finiteNumber(reading.pv_total_power_w),
    loadPower: finiteNumber(reading.load_total_power_w),
    externalLoadPower: finiteNumber(reading.home_load_total_power_w),
  };
}

function rackBatteryTelemetry(batteries = state.batteries) {
  const readings = batteries
    .filter(
      (battery) => state.collectorOnline
        && battery?.status === "ok"
        && battery.last_reading
        && typeof battery.last_reading === "object",
    )
    .map((battery) => battery.last_reading);
  const values = (field) => readings
    .map((reading) => finiteNumber(reading[field]))
    .filter((value) => value !== null);
  const total = (field) => {
    const numbers = values(field);
    return numbers.length ? numbers.reduce((sum, value) => sum + value, 0) : null;
  };
  const average = (field) => {
    const numbers = values(field);
    return numbers.length
      ? numbers.reduce((sum, value) => sum + value, 0) / numbers.length
      : null;
  };
  const remainingEnergyValues = readings
    .map((reading) => {
      const remainingCapacity = finiteNumber(reading.remaining_capacity_ah);
      const voltage = finiteNumber(reading.voltage_v);
      return remainingCapacity === null || voltage === null
        ? null
        : remainingCapacity * voltage;
    })
    .filter((value) => value !== null);
  const remainingEnergyWh = remainingEnergyValues.length === readings.length
    ? remainingEnergyValues.reduce((sum, value) => sum + value, 0)
    : null;
  const power = total("power_w");
  const runtimeHours = power !== null && power < -25 && remainingEnergyWh !== null
    ? remainingEnergyWh / Math.abs(power)
    : null;

  return {
    available: readings.length > 0,
    count: readings.length,
    power,
    current: total("current_a"),
    voltage: average("voltage_v"),
    soc: average("soc_percent"),
    temperature: average("mosfet_temperature_c"),
    remainingEnergyWh,
    runtimeHours,
  };
}

function batteryPowerMode(power, fallback = "idle") {
  if (power === null) return fallback;
  if (power > 25) return "charging";
  if (power < -25) return "discharging";
  return "idle";
}

function inverterStateLabel(value) {
  const stateKeys = {
    bypass: "inverter.state.bypass",
    standby: "inverter.state.standby",
    initializing: "inverter.state.initializing",
    hybrid_power: "inverter.state.hybridPower",
    pv_grid: "inverter.state.pvGrid",
    battery_grid: "inverter.state.batteryGrid",
    ac_battery_charging: "inverter.state.acBatteryCharging",
    pv_battery_charging: "inverter.state.pvBatteryCharging",
    fault: "inverter.state.fault",
    self_check: "inverter.state.selfCheck",
    dsp_firmware_update: "inverter.state.firmwareUpdate",
    arm_firmware_update: "inverter.state.firmwareUpdate",
    service: "inverter.state.service",
    inverter_test: "inverter.state.inverterTest",
    pv_test: "inverter.state.pvTest",
    dcdc_test: "inverter.state.dcdcTest",
    test_mode: "inverter.state.testMode",
    undefined: "inverter.state.undefined",
  };
  return t(stateKeys[String(value || "").trim().toLowerCase()] || "inverter.state.unknown");
}

function formatPower(value) {
  const power = finiteNumber(value);
  if (power === null) return "--";
  if (Math.abs(power) >= 1000) return formatValue(power / 1000, " kW", 2);
  return formatValue(power, " W", 0);
}

function formatBatteryRuntime(value) {
  const hours = finiteNumber(value);
  if (hours === null || hours <= 0) return null;
  const totalMinutes = Math.max(1, Math.round(hours * 60));
  if (totalMinutes < 60) {
    return t("runtime.minutes", { minutes: formatNumber(totalMinutes) });
  }
  const wholeHours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (wholeHours < 48) {
    return t("runtime.hoursMinutes", {
      hours: formatNumber(wholeHours),
      minutes: formatNumber(minutes),
    });
  }
  return t("runtime.daysHours", {
    days: formatNumber(Math.floor(wholeHours / 24)),
    hours: formatNumber(wholeHours % 24),
  });
}

function formatEnergy(value) {
  const energy = finiteNumber(value);
  return energy === null ? "--" : formatValue(energy, " kWh", 2);
}

function formatGridPower(value) {
  const power = finiteNumber(value);
  if (power === null) return "--";
  if (power > 25) return t("energy.importing", { value: formatPower(power) });
  if (power < -25) return t("energy.exporting", { value: formatPower(Math.abs(power)) });
  return formatPower(0);
}

function formatBatteryPower(value) {
  const power = finiteNumber(value);
  if (power === null) return "--";
  if (power > 25) return t("energy.chargingValue", { value: formatPower(power) });
  if (power < -25) return t("energy.dischargingValue", { value: formatPower(Math.abs(power)) });
  return t("energy.standby");
}

function rackPowerDetail(mode) {
  if (mode === "charging") return t("fleet.chargingInput");
  if (mode === "discharging") return t("fleet.dischargeOutput");
  if (mode === "stale") return t("fleet.lastKnownPower");
  return t("fleet.netPower");
}

function temperaturePeakLabel(value) {
  return finiteNumber(value) === null
    ? t("fleet.peakUnavailable")
    : t("fleet.peak", { value: formatValue(value, "°C") });
}

function energyFlowPresentation(reading, available = true) {
  if (!available) return { mode: "stale", label: t("flow.lastKnownReading") };

  const operation = String(reading.operation_status || "").toLowerCase();
  const current = finiteNumber(reading.current_a);
  let mode = "idle";
  if (operation.includes("discharg")) mode = "discharging";
  else if (operation.includes("charg")) mode = "charging";
  else if (current !== null && current > 0.05) mode = "charging";
  else if (current !== null && current < -0.05) mode = "discharging";

  if (mode === "charging") {
    return {
      mode,
      label: current === null
        ? t("flow.charging")
        : t("flow.chargingCurrent", { current: formatValue(Math.abs(current), "A") }),
    };
  }
  if (mode === "discharging") {
    return {
      mode,
      label: current === null
        ? t("flow.discharging")
        : t("flow.dischargingCurrent", { current: formatValue(Math.abs(current), "A") }),
    };
  }
  return { mode, label: t("flow.standingBy") };
}

function rackEnergyFlow(batteries) {
  if (!state.collectorOnline) return { mode: "stale", label: t("flow.lastKnownRack") };

  const liveReadings = batteries
    .filter((battery) => battery.status === "ok" && battery.last_reading)
    .map((battery) => battery.last_reading);
  if (!liveReadings.length) return { mode: "stale", label: t("flow.waitingRack") };

  const currents = liveReadings.map((reading) => finiteNumber(reading.current_a)).filter((value) => value !== null);
  const netCurrent = currents.length ? currents.reduce((total, value) => total + value, 0) : null;
  const modes = liveReadings.map((reading) => energyFlowPresentation(reading).mode);
  const chargingCount = modes.filter((mode) => mode === "charging").length;
  const dischargingCount = modes.filter((mode) => mode === "discharging").length;

  let mode = "idle";
  if (netCurrent !== null && netCurrent > 0.05) mode = "charging";
  else if (netCurrent !== null && netCurrent < -0.05) mode = "discharging";
  else if (chargingCount && !dischargingCount) mode = "charging";
  else if (dischargingCount && !chargingCount) mode = "discharging";

  if (mode === "charging") {
    return {
      mode,
      label: netCurrent === null
        ? t("flow.rackCharging")
        : t("flow.rackChargingCurrent", { current: formatValue(Math.abs(netCurrent), "A") }),
    };
  }
  if (mode === "discharging") {
    return {
      mode,
      label: netCurrent === null
        ? t("flow.rackDischarging")
        : t("flow.rackDischargingCurrent", { current: formatValue(Math.abs(netCurrent), "A") }),
    };
  }
  if (chargingCount && dischargingCount) return { mode, label: t("flow.balanced") };
  return { mode, label: t("flow.rackStandingBy") };
}

function updateSocProgress(progress, value, mode) {
  progress.className = `soc-progress soc-progress--${mode}`;
  if (value === null) {
    progress.removeAttribute("aria-valuenow");
    progress.style.setProperty("--soc", "0");
    return;
  }
  const soc = clamp(value, 0, 100);
  progress.setAttribute("aria-valuenow", String(soc));
  progress.style.setProperty("--soc", String(soc));
}

function renderRackOverview() {
  const rack = state.rack;
  const expected = rack.expected_battery_count ?? rack.batteries?.length ?? 0;
  const observed = rack.observed_battery_count ?? 0;
  const online = rack.online_battery_count ?? 0;

  $("builderLine").textContent = t("brand.builder", {
    builder: rack.builder || "Tran Thanh Tuan",
  });
  $("rackDescription").textContent = expected
    ? online === expected
      ? t("rack.allOnline")
      : t("rack.onlineCount", { online, expected })
    : t("rack.waitingStatus");
  $("rackBatteryCount").textContent = `${formatNumber(expected)} ${t(expected === 1 ? "rack.pack" : "rack.packs")}`;
  $("rackObservedCount").textContent = t("rack.reporting", { count: formatNumber(observed) });
  $("rackCollectorName").textContent = localizedCollectorName(rack.collector?.name);
  $("rackCollectorAddress").textContent = hostFromUrl(rack.collector?.url) || t("common.notConfigured");
  $("rackConnection").textContent = localizedConnectionName(rack.connection);
}

function renderBatteryCards() {
  const grid = $("batteryGrid");
  if (!state.batteries.length) {
    grid.innerHTML = `<div class="empty-state">${escapeHtml(t("battery.awaitingReadings"))}</div>`;
    return;
  }

  grid.querySelector(".empty-state")?.remove();
  const existingCards = new Map(
    Array.from(grid.querySelectorAll(".battery-card")).map((card) => [card.dataset.batteryId, card]),
  );
  const activeIds = new Set();

  for (const battery of state.batteries) {
    const reading = battery.last_reading || {};
    const profile = batteryProfile(battery);
    const displayName = localizedBatteryName(profile?.name || battery.id);
    const socValue = finiteNumber(reading.soc_percent);
    const soc = clamp(socValue ?? 0, 0, 100);
    const previousSoc = state.renderedSoc.get(battery.id) ?? 0;
    const flow = energyFlowPresentation(
      reading,
      state.collectorOnline && battery.status === "ok",
    );
    let card = existingCards.get(battery.id);
    const isNew = !card;
    if (!card) {
      card = document.createElement("button");
      card.type = "button";
      card.addEventListener("click", () => {
        const batteryId = card.dataset.batteryId;
        if (!batteryId) return;
        state.selectedBatteryId = batteryId;
        renderBatteryCards();
        renderBatteryInventory();
        renderSelectedBattery();
      });
    }

    activeIds.add(battery.id);
    card.dataset.batteryId = battery.id;
    card.dataset.flow = flow.mode;
    card.className = `battery-card ${battery.id === state.selectedBatteryId ? "is-selected" : ""}`;
    card.setAttribute("aria-pressed", String(battery.id === state.selectedBatteryId));

    card.innerHTML = `
      <div class="battery-card__top">
        <span>
          <strong>${escapeHtml(displayName)}</strong>
          <small>${escapeHtml(battery.id)} · RS485 ${escapeHtml(battery.address ?? "--")}</small>
        </span>
        <span class="${batteryDotClass(battery.status)}"></span>
      </div>
      <div class="battery-card__soc">
        <div class="battery-card__soc-heading">
          <span>${escapeHtml(t("metric.soc"))}</span>
          <strong>${socValue === null ? "--" : `${Math.round(soc)}%`}</strong>
        </div>
        <div
          class="soc-progress soc-progress--${flow.mode}"
          style="--soc: ${previousSoc}"
          role="progressbar"
          aria-label="${escapeHtml(t("battery.socAria", { name: displayName }))}"
          aria-valuemin="0"
          aria-valuemax="100"
          ${socValue === null ? "" : `aria-valuenow="${soc}"`}
        >
          <span class="soc-progress__fill"></span>
        </div>
        <small class="soc-flow-label"><span class="soc-flow-dot" aria-hidden="true"></span>${escapeHtml(flow.label)}</small>
      </div>
      <div class="battery-card__metrics">
        <div><span>${escapeHtml(t("battery.voltage"))}</span><strong>${formatValue(reading.voltage_v, "V")}</strong></div>
        <div><span>${escapeHtml(t("battery.current"))}</span><strong>${formatValue(reading.current_a, "A")}</strong></div>
        <div><span>${escapeHtml(t("battery.power"))}</span><strong>${formatValue(reading.power_w, "W")}</strong></div>
        <div><span>${escapeHtml(t("battery.cellDelta"))}</span><strong>${formatValue(reading.cell_voltage_delta_v, "V", 3)}</strong></div>
      </div>
    `;
    grid.appendChild(card);
    if (isNew) {
      card.classList.add("is-entering");
      window.requestAnimationFrame(() => card.classList.remove("is-entering"));
    }
    const progress = card.querySelector(".soc-progress");
    window.requestAnimationFrame(() => {
      if (progress?.isConnected) progress.style.setProperty("--soc", String(soc));
    });
    state.renderedSoc.set(battery.id, soc);
  }

  existingCards.forEach((card, batteryId) => {
    if (!activeIds.has(batteryId)) {
      card.remove();
      state.renderedSoc.delete(batteryId);
    }
  });
}

function renderBatteryInventory() {
  const inventory = state.rack.batteries || [];
  const body = $("batteryInventory");
  const expected = state.rack.expected_battery_count ?? inventory.length;
  $("inventoryStatus").textContent = `${formatNumber(expected)} ${t(
    expected === 1 ? "inventory.batterySingular" : "inventory.batteries",
  )}`;

  if (!inventory.length) {
    body.innerHTML = `<div class="empty-mini inventory-empty">${escapeHtml(t("inventory.noneConfigured"))}</div>`;
    return;
  }

  body.innerHTML = inventory
    .map((battery) => {
      const status = statusPresentation(state.collectorOnline ? battery.status : "stale");
      const displayName = localizedBatteryName(battery.name || battery.id);
      const hardware = [
        localizedBatteryModel(battery.model),
        battery.serial_number ? `S/N ${battery.serial_number}` : null,
      ]
        .filter(Boolean)
        .join(" · ");
      const busDetail = battery.rs485_protocol || "Modbus RTU";
      return `
        <button class="inventory-row ${battery.id === state.selectedBatteryId ? "is-selected" : ""}" data-battery-id="${escapeHtml(battery.id)}" type="button">
          <span class="inventory-cell" data-label="${escapeHtml(t("inventory.battery"))}">
            <strong>${escapeHtml(displayName)}</strong>
            <small>${escapeHtml(battery.id)}</small>
          </span>
          <span class="inventory-cell" data-label="${escapeHtml(t("inventory.network"))}">
            <strong>${escapeHtml(battery.ip_address || t("common.notConfigured"))}</strong>
            <small>${escapeHtml(battery.ip_address ? t("inventory.wifiAddress") : t("inventory.noDirectIp"))}</small>
          </span>
          <span class="inventory-cell" data-label="RS485">
            <strong>${escapeHtml(t("inventory.address", { address: battery.address ?? "--" }))}</strong>
            <small>${escapeHtml(busDetail)}</small>
          </span>
          <span class="inventory-cell" data-label="${escapeHtml(t("inventory.hardware"))}">
            <strong>${escapeHtml(hardware || t("inventory.defaultHardware"))}</strong>
            <small>${escapeHtml(
              battery.firmware_version
                ? t("inventory.firmware", { version: battery.firmware_version })
                : t("inventory.firmwarePending"),
            )}</small>
          </span>
          <span class="inventory-cell inventory-cell--state" data-label="${escapeHtml(t("inventory.state"))}">
            <span class="status-pill ${status.className}">${status.label}</span>
            <small>${escapeHtml(
              battery.last_polled_at
                ? t("inventory.seen", { relative: formatRelativeTime(battery.last_polled_at) })
                : t("inventory.notSeen"),
            )}</small>
          </span>
        </button>
      `;
    })
    .join("");

  body.querySelectorAll(".inventory-row").forEach((row) => {
    row.addEventListener("click", () => {
      const batteryId = row.dataset.batteryId;
      if (!state.batteries.some((battery) => battery.id === batteryId)) return;
      state.selectedBatteryId = batteryId;
      renderBatteryCards();
      renderBatteryInventory();
      renderSelectedBattery();
    });
  });
}

function renderSelectedBattery() {
  const battery = selectedBattery();
  if (!battery) {
    $("selectedName").textContent = t("details.rack");
    $("selectedState").textContent = t("status.pending");
    $("cellStrip").innerHTML = "";
    $("temperatureRow").innerHTML = "";
    $("detailList").innerHTML = "";
    $("payloadView").textContent = "";
    return;
  }

  const reading = battery.last_reading || {};
  const profile = batteryProfile(battery);
  $("selectedName").textContent = localizedBatteryName(profile?.name || battery.id);
  const status = statusPresentation(state.collectorOnline ? battery.status : "stale");
  $("selectedState").textContent = status.label;
  $("selectedState").className = `status-pill ${status.className}`;

  renderCells(reading.cell_voltages_v || []);
  renderTemperatures(reading.temperatures_c || []);
  renderDetails(reading, battery);
  $("payloadView").textContent = JSON.stringify(battery, null, 2);
}

function renderCells(cells) {
  const strip = $("cellStrip");
  strip.innerHTML = "";
  if (!cells.length) {
    strip.innerHTML = `<div class="empty-mini">${escapeHtml(t("details.noCellData"))}</div>`;
    return;
  }
  const min = Math.min(...cells);
  const max = Math.max(...cells);
  for (const [index, voltage] of cells.entries()) {
    const height = 28 + ((voltage - min) / Math.max(max - min, 0.001)) * 58;
    const cell = document.createElement("div");
    cell.className = "cell-bar";
    cell.style.height = `${height}px`;
    cell.title = t("details.cellTitle", {
      number: index + 1,
      voltage: formatValue(voltage, "V", 3),
    });
    cell.innerHTML = `<span>${index + 1}</span>`;
    strip.appendChild(cell);
  }
}

function renderTemperatures(temperatures) {
  const row = $("temperatureRow");
  row.innerHTML = "";
  if (!temperatures.length) {
    row.innerHTML = `<div class="empty-mini">${escapeHtml(t("details.noTemperatureData"))}</div>`;
    return;
  }
  for (const [index, temperature] of temperatures.entries()) {
    const chip = document.createElement("div");
    chip.className = "temp-chip";
    chip.innerHTML = `<span>T${index + 1}</span><strong>${formatValue(temperature, "°C", 1)}</strong>`;
    row.appendChild(chip);
  }
}

function renderDetails(reading, battery) {
  const profile = batteryProfile(battery);
  const details = [
    [t("details.batteryId"), battery.id],
    [t("details.ipAddress"), profile?.ip_address || t("common.notConfigured")],
    [t("details.model"), localizedBatteryModel(profile?.model)],
    [t("details.address"), battery.address],
    [t("details.state"), operationLabel(reading.operation_status)],
    [t("details.soh"), formatValue(reading.soh_percent, "%")],
    [t("details.cycles"), reading.cycle_count],
    [t("details.remaining"), formatValue(reading.remaining_capacity_ah, "Ah")],
    [t("details.full"), formatValue(reading.full_capacity_ah, "Ah")],
    [t("details.chargeLimit"), formatValue(reading.charge_current_limit_a, "A")],
    [t("details.dischargeLimit"), formatValue(reading.discharge_current_limit_a, "A")],
    [t("details.firmware"), reading.firmware_version],
    [t("details.serial"), reading.serial_number],
  ];
  $("detailList").innerHTML = details
    .map(
      ([label, value]) =>
        `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value ?? "--")}</dd></div>`,
    )
    .join("");
}

function renderEvents(events) {
  const list = $("eventList");
  if (!events.length) {
    list.innerHTML = `<div class="empty-mini">${escapeHtml(t("events.none"))}</div>`;
    return;
  }
  list.innerHTML = events
    .map((event) => {
      const labels = [...(event.faults || []), ...(event.alarms || [])];
      const title = labels.length
        ? labels.join(", ")
        : event.last_error || statusPresentation(event.status).label;
      return `
        <div class="event-row">
          <span class="${event.fault_count ? "event-dot event-dot--fault" : "event-dot"}"></span>
          <div>
            <strong>${escapeHtml(event.battery_id)}</strong>
            <p>${escapeHtml(title)}</p>
          </div>
          <time>${formatTime(event.captured_at)}</time>
        </div>
      `;
    })
    .join("");
}

function renderStorage() {
  $("rowCount").textContent = compactNumber(state.storage.row_count);
  $("dbSize").textContent = formatBytes(state.storage.database_size_bytes || 0);
  $("oldestReading").textContent = state.storage.oldest_reading_at
    ? shortDate(state.storage.oldest_reading_at)
    : "--";
  $("newestReading").textContent = state.storage.newest_reading_at
    ? shortDate(state.storage.newest_reading_at)
    : "--";
}

function renderEnergyHistory() {
  const totalIds = {
    consumption_kwh: "energyConsumptionTotal",
    solar_generation_kwh: "energySolarTotal",
    grid_import_kwh: "energyGridTotal",
  };
  Object.entries(totalIds).forEach(([field, id]) => {
    $(id).textContent = formatEnergyTotal(state.energySummary[field]);
  });

  const summaryPeriod = formatEnergySummaryPeriod(state.energySummaryPeriod);
  const periodText = summaryPeriod
    ? t("energyHistory.kwhPeriod", { period: summaryPeriod })
    : t("energyHistory.kwhAwaiting");
  ["energyConsumptionPeriod", "energySolarPeriod", "energyGridPeriod"].forEach((id) => {
    $(id).textContent = periodText;
  });
  $("energyHistoryTotals").setAttribute(
    "aria-label",
    summaryPeriod
      ? t("energyHistory.totalsPeriodAria", { period: summaryPeriod })
      : t("energyHistory.totalsAria"),
  );

  const titleKey = {
    hour: "energyHistory.titleHour",
    date: "energyHistory.titleDate",
    month: "energyHistory.titleMonth",
    year: "energyHistory.titleYear",
  }[state.energyView];
  $("energyHistoryTitle").textContent = state.energyView === "date"
    ? t("energyHistory.titleDateFor", { date: formatCalendarDate(state.energyDate) })
    : t(titleKey || "energyHistory.titleMonth");
  const descriptionKey = state.energyView === "hour"
    ? "energyHistory.descriptionHour"
    : state.energyView === "date"
      ? "energyHistory.descriptionDate"
      : "energyHistory.description";
  $("energyHistoryDescription").textContent = t(descriptionKey);
  $("energyDateControl").hidden = state.energyView !== "date";
  $("energyDateInput").value = state.energyDate;

  const hasPoints = state.energyHistory.some((point) =>
    energySeries.some((series) => finiteNumber(point[series.field]) !== null),
  );
  const empty = $("energyHistoryEmpty");
  empty.hidden = hasPoints;
  empty.textContent = state.resourceErrors.energy
    ? t("energyHistory.unavailable")
    : t("energyHistory.awaiting");
  window.requestAnimationFrame(drawEnergyHistoryChart);
}

function drawEnergyHistoryChart() {
  const canvas = $("energyHistoryChart");
  const ctx = canvas.getContext("2d");
  const theme = getThemeColors();
  const rect = canvas.getBoundingClientRect();
  if (rect.width <= 0 || rect.height <= 0) return;

  const dpr = window.devicePixelRatio || 1;
  const pixelWidth = Math.max(1, Math.floor(rect.width * dpr));
  const pixelHeight = Math.max(1, Math.floor(rect.height * dpr));
  if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) {
    canvas.width = pixelWidth;
    canvas.height = pixelHeight;
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, rect.width, rect.height);

  const pad = rect.width < 520
    ? { top: 18, right: 12, bottom: 38, left: 50 }
    : { top: 18, right: 18, bottom: 40, left: 62 };
  const width = Math.max(1, rect.width - pad.left - pad.right);
  const height = Math.max(1, rect.height - pad.top - pad.bottom);
  const points = state.energyHistory
    .filter((point) => Number.isFinite(point.unix))
    .sort((left, right) => left.unix - right.unix);
  const values = points.flatMap((point) =>
    energySeries
      .map((series) => finiteNumber(point[series.field]))
      .filter((value) => value !== null),
  );
  const hasFixedDateWindow = state.energyView === "date"
    && finiteNumber(state.energyWindowStart) !== null
    && finiteNumber(state.energyWindowEnd) !== null;

  drawEnergyGrid(ctx, theme, pad, width, height, Math.max(1, ...values));
  if (!points.length || !values.length) {
    if (hasFixedDateWindow) {
      drawEnergyTimeAxis(
        ctx,
        theme,
        pad,
        width,
        height,
        points,
        state.energyWindowStart,
        state.energyWindowEnd,
      );
    }
    return;
  }

  let minTime = hasFixedDateWindow
    ? state.energyWindowStart
    : Math.min(...points.map((point) => point.unix));
  let maxTime = hasFixedDateWindow
    ? state.energyWindowEnd
    : Math.max(...points.map((point) => point.unix));
  if (minTime === maxTime) {
    const spread = state.energyView === "hour"
      ? 3600
      : state.energyView === "date"
        ? 86400
        : state.energyView === "month"
          ? 2678400
          : 31536000;
    minTime -= spread / 2;
    maxTime += spread / 2;
  }
  const maxValue = Math.max(1, ...values) * 1.08;

  ctx.save();
  ctx.beginPath();
  ctx.rect(pad.left, pad.top, width, height);
  ctx.clip();
  energySeries.forEach((series) => {
    const seriesPoints = points
      .map((point) => ({ point, value: finiteNumber(point[series.field]) }))
      .filter((item) => item.value !== null)
      .map((item) => ({
        ...item,
        x: pad.left + scale(item.point.unix, minTime, maxTime, 0, width),
        y: pad.top + height - scale(item.value, 0, maxValue, 0, height),
      }));
    if (!seriesPoints.length) return;
    ctx.beginPath();
    seriesPoints.forEach((item, index) => {
      if (index === 0) ctx.moveTo(item.x, item.y);
      else ctx.lineTo(item.x, item.y);
    });
    ctx.strokeStyle = series.color;
    ctx.lineWidth = 2.4;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.stroke();

    if (seriesPoints.length <= 40) {
      seriesPoints.forEach((item) => {
        ctx.beginPath();
        ctx.arc(item.x, item.y, 3.2, 0, Math.PI * 2);
        ctx.fillStyle = series.color;
        ctx.fill();
      });
    }
  });
  ctx.restore();

  drawEnergyTimeAxis(ctx, theme, pad, width, height, points, minTime, maxTime);
}

function drawEnergyGrid(ctx, theme, pad, width, height, rawMaxValue) {
  const maxValue = Math.max(1, rawMaxValue * 1.08);
  ctx.save();
  ctx.font = "11px -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif";
  ctx.fillStyle = theme.chartMuted;
  for (let index = 0; index <= 4; index += 1) {
    const y = pad.top + (height * index) / 4;
    ctx.strokeStyle = theme.chartGrid;
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(pad.left + width, y);
    ctx.stroke();
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    ctx.fillText(formatEnergyAxis(maxValue - (maxValue * index) / 4), pad.left - 9, y);
  }
  ctx.restore();
}

function drawEnergyTimeAxis(ctx, theme, pad, width, height, points, minTime, maxTime) {
  if (state.energyView === "date") {
    ctx.save();
    ctx.font = "11px -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif";
    ctx.fillStyle = theme.chartMuted;
    for (let index = 0; index <= 4; index += 1) {
      const x = pad.left + (width * index) / 4;
      ctx.textAlign = index === 0 ? "left" : index === 4 ? "right" : "center";
      ctx.textBaseline = "top";
      ctx.fillText(`${index * 6}h`, x, pad.top + height + 11);
    }
    ctx.restore();
    return;
  }
  const tickCount = Math.min(points.length, width < 520 ? 3 : 5);
  if (!tickCount) return;
  ctx.save();
  ctx.font = "11px -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif";
  ctx.fillStyle = theme.chartMuted;
  for (let index = 0; index < tickCount; index += 1) {
    const pointIndex = tickCount === 1
      ? 0
      : Math.round((index * (points.length - 1)) / (tickCount - 1));
    const point = points[pointIndex];
    const x = tickCount === 1
      ? pad.left + width / 2
      : pad.left + scale(point.unix, minTime, maxTime, 0, width);
    ctx.textAlign = index === 0 ? "left" : index === tickCount - 1 ? "right" : "center";
    ctx.textBaseline = "top";
    ctx.fillText(formatEnergyPeriod(point), x, pad.top + height + 11);
  }
  ctx.restore();
}

function formatEnergyTotal(value) {
  const number = finiteNumber(value);
  if (number === null) return "--";
  return new Intl.NumberFormat(currentLocale(), {
    minimumFractionDigits: 0,
    maximumFractionDigits: 1,
  }).format(number);
}

function latestEnergyHistoryPoint(points) {
  return points.reduce((latest, point) => {
    const pointUnix = finiteNumber(point?.unix);
    if (pointUnix === null) return latest;
    const latestUnix = finiteNumber(latest?.unix);
    return latestUnix === null || pointUnix > latestUnix ? point : latest;
  }, null);
}

function sumEnergyHistoryPoints(points) {
  return energySeries.reduce((totals, series) => {
    const values = points
      .map((point) => finiteNumber(point?.[series.field]))
      .filter((value) => value !== null);
    totals[series.field] = values.length
      ? values.reduce((sum, value) => sum + value, 0)
      : null;
    return totals;
  }, {});
}

function formatEnergySummaryPeriod(point) {
  if (!point) return null;
  if (state.energyView === "year" && point.period) return String(point.period);
  if (state.energyView === "date" && point.period) {
    return formatCalendarDate(String(point.period).slice(0, 10));
  }

  const unix = finiteNumber(point.unix);
  const date = new Date(point.timestamp || (unix === null ? NaN : unix * 1000));
  if (!Number.isFinite(date.getTime())) return point.period ? String(point.period) : null;

  if (state.energyView === "hour") {
    return new Intl.DateTimeFormat(currentLocale(), {
      month: "short",
      day: "numeric",
      hour: "numeric",
    }).format(date);
  }
  if (state.energyView === "month") {
    return new Intl.DateTimeFormat(currentLocale(), {
      month: "long",
      year: "numeric",
    }).format(date);
  }
  return new Intl.DateTimeFormat(currentLocale(), {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(date);
}

function formatCalendarDate(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(String(value || ""))) return String(value || "");
  return new Intl.DateTimeFormat(currentLocale(), {
    month: "long",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${value}T12:00:00Z`));
}

function formatEnergyAxis(value) {
  if (Math.abs(value) >= 1000) {
    return new Intl.NumberFormat(currentLocale(), {
      notation: "compact",
      maximumFractionDigits: 1,
    }).format(value);
  }
  return new Intl.NumberFormat(currentLocale(), { maximumFractionDigits: 1 }).format(value);
}

function formatEnergyPeriod(point) {
  if (state.energyView === "year") return String(point.period || "");
  const date = new Date(point.timestamp || point.unix * 1000);
  if (state.energyView === "hour") {
    return new Intl.DateTimeFormat(currentLocale(), {
      weekday: "short",
      hour: "numeric",
    }).format(date);
  }
  if (state.energyView === "month") {
    return new Intl.DateTimeFormat(currentLocale(), { month: "short", year: "2-digit" }).format(date);
  }
  return new Intl.DateTimeFormat(currentLocale(), {
    month: "short",
    day: "numeric",
    year: "2-digit",
  }).format(date);
}

function animateChartIn() {
  window.cancelAnimationFrame(chartAnimationFrame);
  if (prefersReducedMotion() || !state.history.length) {
    state.chartReveal = 1;
    drawChart();
    return;
  }

  state.chartReveal = 0;
  let startedAt = null;
  const step = (timestamp) => {
    if (startedAt === null) startedAt = timestamp;
    const elapsed = clamp((timestamp - startedAt) / 680, 0, 1);
    state.chartReveal = 1 - (1 - elapsed) ** 3;
    drawChart();
    if (elapsed < 1) chartAnimationFrame = window.requestAnimationFrame(step);
  };
  chartAnimationFrame = window.requestAnimationFrame(step);
}

function drawChart() {
  const canvas = $("historyChart");
  const ctx = canvas.getContext("2d");
  const theme = getThemeColors();
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  if (rect.width <= 0 || rect.height <= 0) return;

  const pixelWidth = Math.max(1, Math.floor(rect.width * dpr));
  const pixelHeight = Math.max(1, Math.floor(rect.height * dpr));
  if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) {
    canvas.width = pixelWidth;
    canvas.height = pixelHeight;
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, rect.width, rect.height);

  const pad = rect.width < 520
    ? { top: 18, right: 12, bottom: 34, left: 48 }
    : { top: 18, right: 18, bottom: 36, left: 58 };
  const width = Math.max(1, rect.width - pad.left - pad.right);
  const height = Math.max(1, rect.height - pad.top - pad.bottom);
  const visibleSeries = selectedPowerHistorySeries();
  const history = state.history
    .filter((point) =>
      Number.isFinite(point.unix) &&
      visibleSeries.some((series) => finiteNumber(point[series.field]) !== null),
    )
    .sort((left, right) => left.unix - right.unix);

  if (!history.length || !visibleSeries.length) {
    drawEmptyChart(ctx, theme, pad, width, height);
    state.chartGeometry = null;
    $("chartLegend").innerHTML = "";
    hideChartTooltip(false);
    return;
  }

  const times = history.map((point) => point.unix);
  const values = history.flatMap((point) =>
    visibleSeries
      .map((series) => finiteNumber(point[series.field]))
      .filter((value) => value !== null),
  );
  const minTime = Math.min(...times);
  const maxTime = Math.max(...times);
  let minValue = Math.min(0, ...values);
  let maxValue = Math.max(0, ...values);
  if (minValue === maxValue) {
    const spread = Math.max(Math.abs(minValue) * 0.08, 100);
    minValue -= spread;
    maxValue += spread;
  }
  const valuePadding = (maxValue - minValue) * 0.08;
  minValue -= valuePadding;
  maxValue += valuePadding;

  drawChartGrid(ctx, theme, pad, width, height, minTime, maxTime, minValue, maxValue);

  const plottedPoints = [];
  ctx.save();
  ctx.beginPath();
  ctx.rect(pad.left, pad.top, width * state.chartReveal, height);
  ctx.clip();
  visibleSeries.forEach((series) => {
    const points = history
      .map((point) => ({ point, value: finiteNumber(point[series.field]) }))
      .filter((item) => item.value !== null)
      .map((item) => ({
        ...item,
        series,
        color: series.color,
        x: pad.left + scale(item.point.unix, minTime, maxTime, 0, width),
        y: pad.top + height - scale(item.value, minValue, maxValue, 0, height),
      }));
    plottedPoints.push(...points);
    drawHistorySeries(ctx, points, series.color);
  });
  ctx.restore();

  state.chartGeometry = {
    points: plottedPoints,
    plot: { left: pad.left, right: pad.left + width, top: pad.top, bottom: pad.top + height },
  };
  renderChartLegend(history, visibleSeries);

  const activePoints = state.chartHover
    ? plottedPoints.filter((item) => item.point.unix === state.chartHover.unix)
    : [];
  if (activePoints.length) {
    drawChartFocus(ctx, activePoints, theme, pad.top, pad.top + height);
    renderChartTooltip(activePoints, rect);
  } else {
    hideChartTooltip(false);
  }
}

function drawEmptyChart(ctx, theme, pad, width, height) {
  ctx.strokeStyle = theme.chartGrid;
  ctx.lineWidth = 1;
  for (let index = 0; index <= 4; index += 1) {
    const y = pad.top + (height * index) / 4;
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(pad.left + width, y);
    ctx.stroke();
  }
  ctx.fillStyle = theme.chartMuted;
  ctx.font = "14px -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif";
  ctx.fillText(
    state.resourceErrors.history ? t("history.unavailable") : t("history.awaiting"),
    pad.left,
    pad.top + 28,
  );
}

function drawChartGrid(ctx, theme, pad, width, height, minTime, maxTime, minValue, maxValue) {
  ctx.save();
  ctx.lineWidth = 1;
  ctx.font = "11px -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif";
  ctx.fillStyle = theme.chartMuted;
  const zeroY = pad.top + height - scale(0, minValue, maxValue, 0, height);

  for (let index = 0; index <= 4; index += 1) {
    const y = pad.top + (height * index) / 4;
    const value = maxValue - ((maxValue - minValue) * index) / 4;
    if (Math.abs(y - zeroY) < 14) continue;
    ctx.strokeStyle = theme.chartGrid;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(pad.left + width, y);
    ctx.stroke();
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    ctx.fillText(formatPowerAxis(value), pad.left - 9, y);
  }

  ctx.strokeStyle = theme.chartMuted;
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(pad.left, zeroY);
  ctx.lineTo(pad.left + width, zeroY);
  ctx.stroke();
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  ctx.fillText("0 W", pad.left - 9, zeroY);

  const tickCount = width < 460 ? 3 : 5;
  for (let index = 0; index < tickCount; index += 1) {
    const ratio = tickCount === 1 ? 0 : index / (tickCount - 1);
    const x = pad.left + width * ratio;
    const unix = minTime + (maxTime - minTime) * ratio;
    ctx.strokeStyle = theme.chartGrid;
    ctx.beginPath();
    ctx.moveTo(x, pad.top);
    ctx.lineTo(x, pad.top + height);
    ctx.stroke();
    ctx.textAlign = index === 0 ? "left" : index === tickCount - 1 ? "right" : "center";
    ctx.textBaseline = "top";
    ctx.fillText(formatChartTick(unix), x, pad.top + height + 10);
  }
  ctx.restore();
}

function drawHistorySeries(ctx, points, color) {
  if (!points.length) return;
  ctx.beginPath();
  points.forEach((item, index) => {
    if (index === 0) ctx.moveTo(item.x, item.y);
    else ctx.lineTo(item.x, item.y);
  });
  ctx.strokeStyle = color;
  ctx.lineWidth = 2.5;
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  ctx.stroke();
}

function drawChartFocus(ctx, activePoints, theme, top, bottom) {
  const x = activePoints[0].x;
  ctx.save();
  ctx.strokeStyle = theme.chartMuted;
  ctx.lineWidth = 1;
  ctx.setLineDash([4, 5]);
  ctx.beginPath();
  ctx.moveTo(x, top);
  ctx.lineTo(x, bottom);
  ctx.stroke();
  ctx.setLineDash([]);

  activePoints.forEach((activePoint) => {
    ctx.beginPath();
    ctx.arc(activePoint.x, activePoint.y, 6, 0, Math.PI * 2);
    ctx.fillStyle = theme.chartInk;
    ctx.fill();
    ctx.beginPath();
    ctx.arc(activePoint.x, activePoint.y, 3.5, 0, Math.PI * 2);
    ctx.fillStyle = activePoint.color;
    ctx.fill();
  });
  ctx.restore();
}

function renderChartLegend(history, visibleSeries) {
  const legend = $("chartLegend");
  const items = visibleSeries.map((series) => {
    const point = [...history]
      .reverse()
      .find((candidate) => finiteNumber(candidate[series.field]) !== null);
    return { series, point, value: point ? point[series.field] : null };
  });
  const signature = `${state.language}:${items
    .map((item) => `${item.series.field}:${item.point?.unix}:${item.value}`)
    .join("|")}`;
  if (legend.dataset.signature === signature) return;
  legend.dataset.signature = signature;
  legend.innerHTML = items
    .map(
      (item) => `
        <span class="chart-legend__item">
          <span class="chart-legend__swatch" style="--series-color: ${item.series.color}"></span>
          <strong>${escapeHtml(t(item.series.labelKey))}</strong>
          <span>${formatPowerHistoryValue(item.value, item.series.field)}</span>
        </span>
      `,
    )
    .join("");
}

function renderChartTooltip(activePoints, canvasRect) {
  const tooltip = $("chartTooltip");
  const timestamp = formatChartTimestamp(
    activePoints[0].point.timestamp || activePoints[0].point.unix * 1000,
  );
  const rows = activePoints
    .sort((left, right) => powerHistorySeries.indexOf(left.series) - powerHistorySeries.indexOf(right.series))
    .map((item) => `
      <span class="power-tooltip__row">
        <i style="--series-color: ${item.color}"></i>
        <span>${escapeHtml(t(item.series.labelKey))}</span>
        <strong>${escapeHtml(formatPowerHistoryValue(item.value, item.series.field))}</strong>
      </span>
    `)
    .join("");
  tooltip.classList.add("chart-tooltip--power");
  tooltip.innerHTML = `
    <time class="power-tooltip__time">${escapeHtml(timestamp)}</time>
    ${rows}
  `;
  tooltip.hidden = false;

  if (canvasRect.width < 540) {
    tooltip.dataset.mobile = "true";
    tooltip.style.left = "12px";
    tooltip.style.top = "12px";
  } else {
    delete tooltip.dataset.mobile;
    const anchorX = activePoints[0].x;
    const anchorY = Math.min(...activePoints.map((item) => item.y));
    tooltip.style.left = `${clamp(anchorX, 138, canvasRect.width - 138)}px`;
    tooltip.style.top = `${anchorY}px`;
    tooltip.classList.toggle("is-below", anchorY < 145);
  }
  const values = activePoints
    .map((item) => `${t(item.series.labelKey)} ${formatPowerHistoryValue(item.value, item.series.field)}`)
    .join(", ");
  $("historyChart").setAttribute(
    "aria-label",
    t("history.pointAria", {
      timestamp,
      values,
    }),
  );
}

function hideChartTooltip(redraw = true) {
  state.chartHover = null;
  const tooltip = $("chartTooltip");
  tooltip.hidden = true;
  tooltip.classList.remove("is-below");
  tooltip.classList.remove("chart-tooltip--power");
  delete tooltip.dataset.mobile;
  $("historyChart").setAttribute("aria-label", t("history.chartAria"));
  if (redraw) window.requestAnimationFrame(drawChart);
}

function updateChartHoverFromClient(clientX, clientY) {
  const canvas = $("historyChart");
  const rect = canvas.getBoundingClientRect();
  const geometry = state.chartGeometry;
  if (!geometry?.points.length) return;
  const x = clientX - rect.left;
  const y = clientY - rect.top;
  if (x < geometry.plot.left - 18 || x > geometry.plot.right + 18) {
    hideChartTooltip();
    return;
  }

  const nearest = geometry.points.reduce((best, point) => {
    const score = Math.abs(point.x - x) + Math.abs(point.y - y) * 0.16;
    return !best || score < best.score ? { point, score } : best;
  }, null)?.point;
  if (!nearest) return;
  state.chartHover = { unix: nearest.point.unix };
  drawChart();
}

function queueChartHover(clientX, clientY) {
  window.cancelAnimationFrame(chartPointerFrame);
  chartPointerFrame = window.requestAnimationFrame(() => updateChartHoverFromClient(clientX, clientY));
}

function moveChartKeyboardSelection(key) {
  const timestamps = Array.from(
    new Set((state.chartGeometry?.points || []).map((item) => item.point.unix)),
  ).sort((left, right) => left - right);
  if (!timestamps.length) return;
  const currentIndex = timestamps.indexOf(state.chartHover?.unix);
  let nextIndex = currentIndex;
  if (key === "Home") nextIndex = 0;
  else if (key === "End") nextIndex = timestamps.length - 1;
  else if (key === "ArrowLeft") nextIndex = currentIndex < 0 ? timestamps.length - 1 : currentIndex - 1;
  else if (key === "ArrowRight") nextIndex = currentIndex < 0 ? 0 : currentIndex + 1;
  nextIndex = clamp(nextIndex, 0, timestamps.length - 1);
  state.chartHover = { unix: timestamps[nextIndex] };
  drawChart();
}

function selectedPowerHistorySeries() {
  return powerHistorySeries.filter((series) => state.powerSeries.has(series.field));
}

function formatPowerAxis(value) {
  const magnitude = Math.abs(value);
  const scaled = magnitude >= 1000 ? magnitude / 1000 : magnitude;
  const unit = magnitude >= 1000 ? "kW" : "W";
  const prefix = value < 0 ? "−" : value > 0 ? "+" : "";
  return `${prefix}${new Intl.NumberFormat(currentLocale(), {
    maximumFractionDigits: magnitude >= 1000 ? 1 : 0,
  }).format(scaled)} ${unit}`;
}

function formatPowerHistoryValue(value, field) {
  const number = finiteNumber(value);
  if (number === null) return "--";
  const magnitude = Math.abs(number);
  const power = magnitude >= 1000
    ? `${new Intl.NumberFormat(currentLocale(), { maximumFractionDigits: 1 }).format(magnitude / 1000)} kW`
    : `${new Intl.NumberFormat(currentLocale(), { maximumFractionDigits: 0 }).format(magnitude)} W`;
  const directionKey = field === "grid_power_w"
    ? number >= 0 ? "history.importing" : "history.exporting"
    : field === "battery_power_w"
      ? number >= 0 ? "history.charging" : "history.discharging"
      : field === "solar_power_w"
        ? "history.generating"
        : "history.consuming";
  return `${power} ${t(directionKey)}`;
}

function formatChartTick(unix) {
  const date = new Date(unix * 1000);
  if (state.range === "1h" || state.range === "24h") {
    return new Intl.DateTimeFormat(currentLocale(), { hour: "numeric", minute: "2-digit" }).format(date);
  }
  if (state.range === "3y") {
    return new Intl.DateTimeFormat(currentLocale(), { month: "short", year: "2-digit" }).format(date);
  }
  return new Intl.DateTimeFormat(currentLocale(), { month: "short", day: "numeric" }).format(date);
}

function formatChartTimestamp(value) {
  return new Intl.DateTimeFormat(currentLocale(), {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(value));
}

function selectedBattery() {
  return state.batteries.find((battery) => battery.id === state.selectedBatteryId) || state.batteries[0];
}

function batteryProfile(battery) {
  return (state.rack.batteries || []).find(
    (profile) => profile.id === battery.id || profile.address === battery.address,
  );
}

function localizedBatteryName(value) {
  if (!value || state.language !== "vi") return value;
  const name = String(value).trim();
  const rackBattery = /^rack battery\s+(\d+)$/i.exec(name);
  if (rackBattery) return t("battery.defaultRackName", { number: rackBattery[1] });
  const battery = /^battery\s+(\d+)$/i.exec(name);
  if (battery) return t("battery.defaultName", { number: battery[1] });
  return value;
}

function localizedBatteryModel(value) {
  if (!value || state.language !== "vi") return value;
  const model = String(value).trim();
  if (/^eco-worthy server rack battery$/i.test(model)) return t("inventory.defaultModel");
  if (/^eco-worthy battery$/i.test(model)) return t("inventory.defaultHardware");
  return value;
}

function localizedCollectorName(value) {
  if (!value) return t("rack.defaultCollector");
  if (state.language === "vi" && /^raspberry pi collector$/i.test(String(value).trim())) {
    return t("rack.defaultCollector");
  }
  return value;
}

function localizedConnectionName(value) {
  if (!value) return t("rack.defaultConnection");
  if (state.language === "vi" && /^modbus rtu over rs485$/i.test(String(value).trim())) {
    return t("rack.defaultConnection");
  }
  return value;
}

function statusPresentation(status) {
  if (status === "ok") return { label: t("status.online"), className: "status-pill--ok" };
  if (status === "error") return { label: t("status.needsAttention"), className: "status-pill--error" };
  if (status === "disabled") return { label: t("status.disabled"), className: "" };
  if (status === "stale") return { label: t("status.lastKnown"), className: "status-pill--pending" };
  return { label: t("status.waiting"), className: "status-pill--pending" };
}

function connectionPresentation(status) {
  if (status === "online") {
    return {
      label: t("status.collectorOnline"),
      className: "status-pill--ok",
      description: t("status.collectorOnlineDescription"),
    };
  }
  if (status === "degraded") {
    return {
      label: t("status.collectorDegraded"),
      className: "status-pill--warning",
      description: t("status.collectorDegradedDescription"),
    };
  }
  if (status === "stale") {
    return {
      label: t("status.collectorStale"),
      className: "status-pill--stale",
      description: t("status.collectorStaleDescription"),
    };
  }
  return {
    label: t("status.collectorOffline"),
    className: "status-pill--error",
    description: t("status.collectorOfflineDescription"),
  };
}

function operationLabel(value) {
  if (!value) return null;
  const operation = String(value).toLowerCase();
  if (operation.includes("discharg")) return t("operation.discharging");
  if (operation.includes("charg")) return t("operation.charging");
  if (operation.includes("idle")) return t("operation.idle");
  if (operation.includes("standby") || operation.includes("stand by")) return t("operation.standby");
  if (operation.includes("fault") || operation.includes("error")) return t("operation.fault");
  if (operation === "unknown") return t("operation.unknown");
  return value;
}

function batteryDotClass(status) {
  if (!state.collectorOnline) return "dot";
  if (status === "ok") return "dot dot--ok";
  if (status === "error") return "dot dot--error";
  return "dot";
}

function formatValue(value, unit = "", digits = 1) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "--";
  const minimumFractionDigits = digits === 1 ? 0 : digits;
  const formatted = new Intl.NumberFormat(currentLocale(), {
    minimumFractionDigits,
    maximumFractionDigits: digits,
  }).format(value);
  return `${formatted}${unit}`;
}

function compactNumber(value) {
  if (typeof value !== "number") return "--";
  return new Intl.NumberFormat(currentLocale(), { notation: "compact" }).format(value);
}

function formatNumber(value) {
  return new Intl.NumberFormat(currentLocale()).format(value);
}

function pluralize(value, singular, plural) {
  return value === 1 ? singular : plural;
}

function hostFromUrl(value) {
  if (!value) return "";
  try {
    return new URL(value).host;
  } catch {
    return value;
  }
}

function formatRelativeTime(value) {
  const date = new Date(value);
  const deltaSeconds = Math.round((date.getTime() - Date.now()) / 1000);
  if (!Number.isFinite(deltaSeconds)) return t("common.recently");
  const formatter = new Intl.RelativeTimeFormat(currentLocale(), { numeric: "auto" });
  const ranges = [
    [60, "second"],
    [60, "minute"],
    [24, "hour"],
    [7, "day"],
  ];
  let valueForRange = deltaSeconds;
  for (const [limit, unit] of ranges) {
    if (Math.abs(valueForRange) < limit) return formatter.format(valueForRange, unit);
    valueForRange = Math.round(valueForRange / limit);
  }
  return shortDate(value);
}

function formatBytes(bytes) {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = bytes;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${new Intl.NumberFormat(currentLocale(), {
    minimumFractionDigits: 0,
    maximumFractionDigits: index === 0 ? 0 : 1,
  }).format(size)} ${units[index]}`;
}

function formatTime(value) {
  return new Intl.DateTimeFormat(currentLocale(), {
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(value));
}

function shortDate(value) {
  return new Intl.DateTimeFormat(currentLocale(), {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(new Date(value));
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function finiteNumber(value) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function scale(value, min, max, outMin, outMax) {
  if (max === min) return (outMin + outMax) / 2;
  return outMin + ((value - min) / (max - min)) * (outMax - outMin);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function getThemeColors() {
  const style = getComputedStyle(document.documentElement);
  return {
    chartGrid: style.getPropertyValue("--chart-grid").trim(),
    chartInk: style.getPropertyValue("--chart-ink").trim(),
    chartMuted: style.getPropertyValue("--chart-muted").trim(),
  };
}

function initLanguage() {
  const storedLanguage = getStoredLanguage();
  const browserLanguage = navigator.language?.toLowerCase().startsWith("vi") ? "vi" : "en";
  const language = storedLanguage || (document.documentElement.lang === "vi" ? "vi" : browserLanguage);
  applyLanguage(language, false);

  const toggle = $("languageToggle");
  toggle.checked = language === "vi";
  toggle.addEventListener("change", () => {
    applyLanguage(toggle.checked ? "vi" : "en", true);
  });
}

function applyLanguage(language, persist) {
  const nextLanguage = language === "vi" ? "vi" : "en";
  const setLanguage = () => {
    state.language = nextLanguage;
    document.documentElement.lang = nextLanguage;
    document.documentElement.dataset.language = nextLanguage;
    if (persist) setStoredLanguage(nextLanguage);
    applyStaticTranslations();
    rerenderLocalizedUi();
    $("languageToggle").checked = nextLanguage === "vi";
  };

  if (persist && document.startViewTransition && !prefersReducedMotion()) {
    document.startViewTransition(setLanguage);
    return;
  }
  setLanguage();
}

function rerenderLocalizedUi() {
  $("chartTitle").textContent = t("history.powerTitle");
  $("chartLegend").dataset.signature = "";
  hideChartTooltip(false);
  renderEnergyHistory();

  if (state.livePayload) {
    renderStatus(state.livePayload);
    renderRackOverview();
    renderSummary(state.summary);
    renderInverterTelemetry();
    renderBatteryCards();
    renderBatteryInventory();
    renderSelectedBattery();
    renderStorage();
  }
  if (state.lastEventsRefreshAt || state.resourceErrors.events) {
    renderEvents(state.events);
    if (state.resourceErrors.events && !state.events.length) {
      $("eventList").innerHTML = `<div class="empty-mini">${escapeHtml(t("events.refreshFailed"))}</div>`;
    }
  }
  if (state.resourceErrors.live) renderLiveFailure(state.resourceErrors.live);
  window.requestAnimationFrame(drawChart);
}

function getStoredLanguage() {
  try {
    const language = localStorage.getItem(LANGUAGE_STORAGE_KEY);
    return language === "vi" || language === "en" ? language : null;
  } catch {
    return null;
  }
}

function setStoredLanguage(language) {
  try {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, language);
  } catch {
    return;
  }
}

function initTheme() {
  const storedTheme = getStoredTheme();
  const systemTheme = window.matchMedia?.("(prefers-color-scheme: dark)");
  const prefersDark = systemTheme?.matches;
  const theme = storedTheme || (prefersDark ? "dark" : "light");
  applyTheme(theme, false);

  const toggle = $("themeToggle");
  toggle.checked = theme === "dark";
  toggle.addEventListener("change", () => {
    applyTheme(toggle.checked ? "dark" : "light", true);
  });

  systemTheme?.addEventListener?.("change", (event) => {
    if (getStoredTheme()) return;
    applyTheme(event.matches ? "dark" : "light", true);
    toggle.checked = event.matches;
  });
}

function applyTheme(theme, persist) {
  const setTheme = () => {
    state.theme = theme;
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
    if (persist) {
      setStoredTheme(theme);
    }
    requestAnimationFrame(drawChart);
    requestAnimationFrame(drawEnergyHistoryChart);
  };

  if (persist && document.startViewTransition && !prefersReducedMotion()) {
    document.startViewTransition(setTheme);
    return;
  }

  setTheme();
}

function getStoredTheme() {
  try {
    return localStorage.getItem(THEME_STORAGE_KEY);
  } catch {
    return null;
  }
}

function setStoredTheme(theme) {
  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    return;
  }
}

function prefersReducedMotion() {
  return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true;
}

function bindControls() {
  initLanguage();
  initTheme();

  const energyDateInput = $("energyDateInput");
  const oldestDate = new Date();
  oldestDate.setFullYear(oldestDate.getFullYear() - 3);
  energyDateInput.value = state.energyDate;
  energyDateInput.max = localCalendarDateValue(new Date());
  energyDateInput.min = localCalendarDateValue(oldestDate);
  energyDateInput.addEventListener("change", () => {
    if (!energyDateInput.value || energyDateInput.value === state.energyDate) return;
    state.energyDate = energyDateInput.value;
    state.energyHistory = [];
    state.energySummary = {};
    state.energySummaryPeriod = null;
    state.energyWindowStart = null;
    state.energyWindowEnd = null;
    renderEnergyHistory();
    refreshEnergyHistory().catch((error) => handleResourceFailure("energy", error));
  });

  document.querySelectorAll("[data-power-series]").forEach((button) => {
    button.addEventListener("click", () => {
      const field = button.dataset.powerSeries;
      if (state.powerSeries.has(field) && state.powerSeries.size === 1) return;
      if (state.powerSeries.has(field)) state.powerSeries.delete(field);
      else state.powerSeries.add(field);
      button.classList.toggle("is-active", state.powerSeries.has(field));
      button.setAttribute("aria-pressed", String(state.powerSeries.has(field)));
      $("chartLegend").dataset.signature = "";
      hideChartTooltip(false);
      window.requestAnimationFrame(drawChart);
    });
  });

  document.querySelectorAll(".segmented button[data-range]").forEach((button) => {
    button.addEventListener("click", () => {
      state.range = button.dataset.range;
      document.querySelectorAll(".segmented button[data-range]").forEach((item) => item.classList.remove("is-active"));
      button.classList.add("is-active");
      hideChartTooltip(false);
      refreshHistory().catch((error) => handleResourceFailure("history", error));
    });
  });

  document.querySelectorAll("#energyViewControls button[data-energy-view]").forEach((button) => {
    button.addEventListener("click", () => {
      state.energyView = button.dataset.energyView;
      state.energyHistory = [];
      state.energySummary = {};
      state.energySummaryPeriod = null;
      state.energyWindowStart = null;
      state.energyWindowEnd = null;
      document.querySelectorAll("#energyViewControls button").forEach((item) => {
        item.classList.remove("is-active");
        item.setAttribute("aria-pressed", "false");
      });
      button.classList.add("is-active");
      button.setAttribute("aria-pressed", "true");
      renderEnergyHistory();
      refreshEnergyHistory().catch((error) => handleResourceFailure("energy", error));
    });
  });

  $("exportButton").addEventListener("click", () => {
    const batteryId = state.selectedBatteryId || "all";
    window.location.href = `/api/export.csv?battery_id=${encodeURIComponent(batteryId)}&days=30`;
  });

  const chart = $("historyChart");
  chart.addEventListener("pointermove", (event) => {
    if (event.pointerType === "touch") return;
    queueChartHover(event.clientX, event.clientY);
  });
  chart.addEventListener("pointerdown", (event) => {
    if (event.pointerType === "touch") queueChartHover(event.clientX, event.clientY);
  });
  chart.addEventListener("pointerleave", (event) => {
    if (event.pointerType !== "touch") hideChartTooltip();
  });
  chart.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    moveChartKeyboardSelection(event.key);
  });
  chart.addEventListener("blur", () => hideChartTooltip());

  const chartContainer = chart.parentElement;
  const energyChartContainer = $("energyHistoryChart").parentElement;
  if ("ResizeObserver" in window) {
    const observer = new ResizeObserver(() => {
      window.cancelAnimationFrame(chartResizeFrame);
      chartResizeFrame = window.requestAnimationFrame(drawChart);
    });
    observer.observe(chartContainer);
    const energyObserver = new ResizeObserver(() => {
      window.cancelAnimationFrame(energyChartResizeFrame);
      energyChartResizeFrame = window.requestAnimationFrame(drawEnergyHistoryChart);
    });
    energyObserver.observe(energyChartContainer);
  } else {
    window.addEventListener("resize", () => {
      window.cancelAnimationFrame(chartResizeFrame);
      chartResizeFrame = window.requestAnimationFrame(drawChart);
      window.cancelAnimationFrame(energyChartResizeFrame);
      energyChartResizeFrame = window.requestAnimationFrame(drawEnergyHistoryChart);
    });
  }

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      window.clearTimeout(schedulerTimer);
      abortActiveRequests();
      return;
    }
    refreshCycle(true);
  });

  window.addEventListener("online", () => refreshCycle(true));
  window.addEventListener("offline", () => renderLiveFailure(t("error.browserOffline")));
}

bindControls();
refreshCycle(true);
