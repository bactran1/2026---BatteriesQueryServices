const state = {
  batteries: [],
  selectedBatteryId: null,
  metric: "soc_percent",
  range: "24h",
  history: [],
  storage: {},
  rack: {},
  collectorState: "offline",
  collectorOnline: false,
  lastLiveReceivedAt: 0,
  lastHistoryRefreshAt: 0,
  lastEventsRefreshAt: 0,
  refreshInProgress: false,
  resourceErrors: { live: null, history: null, events: null },
  theme: "light",
  chartGeometry: null,
  chartHover: null,
  chartReveal: 1,
  renderedSoc: new Map(),
};

const metricLabels = {
  soc_percent: "State of charge",
  voltage_v: "Pack voltage",
  current_a: "Pack current",
  power_w: "Live power",
  cell_voltage_delta_v: "Cell delta",
  mosfet_temperature_c: "MOSFET temperature",
  ambient_temperature_c: "Ambient temperature",
};

const metricUnits = {
  soc_percent: "%",
  voltage_v: "V",
  current_a: "A",
  power_w: "W",
  cell_voltage_delta_v: "V",
  mosfet_temperature_c: "°C",
  ambient_temperature_c: "°C",
};

const metricDigits = {
  soc_percent: 1,
  voltage_v: 2,
  current_a: 2,
  power_w: 1,
  cell_voltage_delta_v: 4,
  mosfet_temperature_c: 1,
  ambient_temperature_c: 1,
};

const palette = ["#ff7a00", "#30d158", "#bf5af2", "#34c7d9", "#ff453a"];

const $ = (id) => document.getElementById(id);
const THEME_STORAGE_KEY = "battery-monitor-theme";
const LIVE_REFRESH_MS = 5000;
const SECONDARY_REFRESH_MS = 30000;
const REQUEST_TIMEOUT_MS = 8000;
const UI_OFFLINE_AFTER_MS = 120000;
const requestControllers = new Map();
let schedulerTimer = null;
let chartResizeFrame = null;
let chartPointerFrame = null;
let chartAnimationFrame = null;

async function refreshCycle(forceSecondary = false) {
  if (document.hidden || state.refreshInProgress) return;
  state.refreshInProgress = true;
  try {
    const now = Date.now();
    const jobs = [["live", refreshLive()]];
    if (forceSecondary || now - state.lastHistoryRefreshAt >= SECONDARY_REFRESH_MS) {
      jobs.push(["history", refreshHistory()]);
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
  state.batteries = payload.snapshot?.batteries || [];
  state.storage = payload.storage || {};
  state.rack = payload.rack || {};
  state.collectorState = payload.collector_status || "offline";
  state.collectorOnline = ["online", "degraded"].includes(state.collectorState);
  state.lastLiveReceivedAt = Date.now();
  state.resourceErrors.live = null;
  let initializedSelection = false;
  if (!state.selectedBatteryId && state.batteries.length) {
    state.selectedBatteryId = state.batteries[0].id;
    initializedSelection = true;
  }
  renderStatus(payload);
  renderRackOverview();
  renderSummary(payload.summary || {});
  renderBatteryCards();
  renderBatteryInventory();
  renderSelectedBattery();
  renderStorage();
  if (
    initializedSelection &&
    state.history.some((point) => point.battery_id !== state.selectedBatteryId)
  ) {
    refreshHistory().catch((error) => handleResourceFailure("history", error));
  }
}

async function refreshHistory() {
  const requestedBatteryId = state.selectedBatteryId || "all";
  const requestedMetric = state.metric;
  const requestedRange = state.range;
  const params = new URLSearchParams({
    battery_id: requestedBatteryId,
    metric: requestedMetric,
    range: requestedRange,
  });
  const payload = await getJson(`/api/history?${params}`, "history");
  if (
    requestedBatteryId !== (state.selectedBatteryId || "all") ||
    requestedMetric !== state.metric ||
    requestedRange !== state.range
  ) {
    return refreshHistory();
  }
  state.history = payload.points || [];
  state.lastHistoryRefreshAt = Date.now();
  state.resourceErrors.history = null;
  $("historyChart").removeAttribute("data-refresh-error");
  $("chartTitle").textContent = metricLabels[state.metric] || state.metric;
  state.chartHover = null;
  hideChartTooltip(false);
  animateChartIn();
}

async function refreshEvents() {
  const payload = await getJson("/api/events?range=7d&limit=80", "events");
  state.lastEventsRefreshAt = Date.now();
  state.resourceErrors.events = null;
  $("eventList").removeAttribute("data-refresh-error");
  renderEvents(payload.events || []);
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
      throw new Error(`Request timed out after ${REQUEST_TIMEOUT_MS / 1000} seconds`);
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
    ? `Data ${formatRelativeTime(lastData)}`
    : "No live readings yet";

  const detail = $("connectionDetail");
  if (payload.collector_error) {
    detail.textContent = `Last error: ${payload.collector_error}`;
  } else if (payload.monitor?.storage_error) {
    detail.textContent = `Archive error: ${payload.monitor.storage_error}`;
  } else if (payload.collector_status === "degraded") {
    const summary = payload.summary || {};
    detail.textContent = `${summary.online_count || 0} of ${summary.battery_count || 0} batteries responding`;
  } else if (payload.collector_status === "stale") {
    detail.textContent = lastData
      ? `Last collector data ${formatRelativeTime(lastData)}`
      : "Waiting for a fresh collector sample";
  } else if (payload.collector_status === "offline") {
    detail.textContent = "Waiting for the collector to reconnect";
  } else if (payload.monitor?.backfill_error) {
    detail.textContent = `Archive recovery delayed: ${payload.monitor.backfill_error}`;
  } else {
    detail.textContent = `Archive current · ${formatNumber(payload.storage?.row_count || 0)} rows`;
  }
}

function handleResourceFailure(resource, error) {
  if (error?.name === "AbortError") return;
  const message = error?.message || String(error || "Unknown refresh error");
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
  $("eventList").dataset.refreshError = message;
  if (!$("eventList").children.length) {
    $("eventList").innerHTML = `<div class="empty-mini">Events could not refresh</div>`;
  }
}

function renderLiveFailure(message) {
  const age = state.lastLiveReceivedAt ? Date.now() - state.lastLiveReceivedAt : Infinity;
  const status = age >= UI_OFFLINE_AFTER_MS ? "offline" : "stale";
  const presentation = connectionPresentation(status);
  state.collectorOnline = false;
  $("collectorStatus").textContent = status === "offline" ? "Monitor offline" : "Data stale";
  $("collectorStatus").className = `status-pill ${presentation.className}`;
  $("collectorStatus").title = message;
  $("lastUpdated").textContent = state.lastLiveReceivedAt
    ? `Last dashboard update ${formatRelativeTime(new Date(state.lastLiveReceivedAt).toISOString())}`
    : "No dashboard response";
  $("connectionDetail").textContent = `Refresh error: ${message}`;
  renderBatteryCards();
  renderBatteryInventory();
  renderSelectedBattery();
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
    ? "Combined capacity"
    : `of ${formatValue(summary.full_capacity_ah, "Ah")}`;
  $("fleetMosfetTemp").textContent = formatValue(summary.average_mosfet_temperature_c, "°C");
  $("fleetMosfetPeak").textContent = temperaturePeakLabel(summary.maximum_mosfet_temperature_c);
  $("fleetAmbientTemp").textContent = formatValue(summary.average_ambient_temperature_c, "°C");
  $("fleetAmbientPeak").textContent = temperaturePeakLabel(summary.maximum_ambient_temperature_c);
  const alerts = (summary.alarm_count || 0) + (summary.fault_count || 0);
  $("fleetHealth").textContent = alerts ? `${alerts} ${pluralize(alerts, "alert", "alerts")}` : "Nominal";
  $("fleetHealthMetric").classList.toggle("has-alerts", alerts > 0);
  $("fleetCellDelta").textContent = finiteNumber(summary.maximum_cell_voltage_delta_v) === null
    ? "Cell spread unavailable"
    : `Max cell Δ ${formatValue(summary.maximum_cell_voltage_delta_v, "V", 3)}`;
}

function rackPowerDetail(mode) {
  if (mode === "charging") return "Charging input";
  if (mode === "discharging") return "Discharge output";
  if (mode === "stale") return "Last known power";
  return "Net rack power";
}

function temperaturePeakLabel(value) {
  return finiteNumber(value) === null ? "Peak unavailable" : `Peak ${formatValue(value, "°C")}`;
}

function energyFlowPresentation(reading, available = true) {
  if (!available) return { mode: "stale", label: "Last known reading" };

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
      label: current === null ? "Charging" : `Charging · ${formatValue(Math.abs(current), "A")}`,
    };
  }
  if (mode === "discharging") {
    return {
      mode,
      label: current === null ? "Discharging" : `Discharging · ${formatValue(Math.abs(current), "A")}`,
    };
  }
  return { mode, label: "Standing by" };
}

function rackEnergyFlow(batteries) {
  if (!state.collectorOnline) return { mode: "stale", label: "Last known rack level" };

  const liveReadings = batteries
    .filter((battery) => battery.status === "ok" && battery.last_reading)
    .map((battery) => battery.last_reading);
  if (!liveReadings.length) return { mode: "stale", label: "Waiting for rack readings" };

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
      label: netCurrent === null ? "Rack charging" : `Rack charging · ${formatValue(Math.abs(netCurrent), "A")}`,
    };
  }
  if (mode === "discharging") {
    return {
      mode,
      label: netCurrent === null ? "Rack discharging" : `Rack discharging · ${formatValue(Math.abs(netCurrent), "A")}`,
    };
  }
  if (chargingCount && dischargingCount) return { mode, label: "Balanced power flow" };
  return { mode, label: "Rack standing by" };
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

  $("builderLine").textContent = `The system is built by ${rack.builder || "Tran Thanh Tuan"} and son`;
  $("rackDescription").textContent = expected
    ? online === expected
      ? "All batteries online"
      : `${online} of ${expected} online`
    : "Waiting for rack status";
  $("rackBatteryCount").textContent = `${expected} ${pluralize(expected, "pack", "packs")}`;
  $("rackObservedCount").textContent = `${observed} reporting`;
  $("rackCollectorName").textContent = rack.collector?.name || "Raspberry Pi collector";
  $("rackCollectorAddress").textContent = hostFromUrl(rack.collector?.url) || "Not configured";
  $("rackConnection").textContent = rack.connection || "Modbus RTU over RS485";
}

function renderBatteryCards() {
  const grid = $("batteryGrid");
  if (!state.batteries.length) {
    grid.innerHTML = `<div class="empty-state">Awaiting readings</div>`;
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
        refreshHistory().catch((error) => handleResourceFailure("history", error));
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
          <strong>${escapeHtml(profile?.name || battery.id)}</strong>
          <small>${escapeHtml(battery.id)} · RS485 ${escapeHtml(battery.address ?? "--")}</small>
        </span>
        <span class="${batteryDotClass(battery.status)}"></span>
      </div>
      <div class="battery-card__soc">
        <div class="battery-card__soc-heading">
          <span>State of charge</span>
          <strong>${socValue === null ? "--" : `${Math.round(soc)}%`}</strong>
        </div>
        <div
          class="soc-progress soc-progress--${flow.mode}"
          style="--soc: ${previousSoc}"
          role="progressbar"
          aria-label="${escapeHtml(profile?.name || battery.id)} state of charge"
          aria-valuemin="0"
          aria-valuemax="100"
          ${socValue === null ? "" : `aria-valuenow="${soc}"`}
        >
          <span class="soc-progress__fill"></span>
        </div>
        <small class="soc-flow-label"><span class="soc-flow-dot" aria-hidden="true"></span>${escapeHtml(flow.label)}</small>
      </div>
      <div class="battery-card__metrics">
        <div><span>Voltage</span><strong>${formatValue(reading.voltage_v, "V")}</strong></div>
        <div><span>Current</span><strong>${formatValue(reading.current_a, "A")}</strong></div>
        <div><span>Power</span><strong>${formatValue(reading.power_w, "W")}</strong></div>
        <div><span>Cell Δ</span><strong>${formatValue(reading.cell_voltage_delta_v, "V", 3)}</strong></div>
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
  $("inventoryStatus").textContent = `${expected} ${pluralize(expected, "battery", "batteries")}`;

  if (!inventory.length) {
    body.innerHTML = `<div class="empty-mini inventory-empty">No batteries configured</div>`;
    return;
  }

  body.innerHTML = inventory
    .map((battery) => {
      const status = statusPresentation(state.collectorOnline ? battery.status : "stale");
      const hardware = [battery.model, battery.serial_number ? `S/N ${battery.serial_number}` : null]
        .filter(Boolean)
        .join(" · ");
      const busDetail = battery.rs485_protocol || "Modbus RTU";
      return `
        <button class="inventory-row ${battery.id === state.selectedBatteryId ? "is-selected" : ""}" data-battery-id="${escapeHtml(battery.id)}" type="button">
          <span class="inventory-cell" data-label="Battery">
            <strong>${escapeHtml(battery.name || battery.id)}</strong>
            <small>${escapeHtml(battery.id)}</small>
          </span>
          <span class="inventory-cell" data-label="Network">
            <strong>${escapeHtml(battery.ip_address || "Not configured")}</strong>
            <small>${battery.ip_address ? "Battery Wi-Fi address" : "No direct IP recorded"}</small>
          </span>
          <span class="inventory-cell" data-label="RS485">
            <strong>Address ${escapeHtml(battery.address ?? "--")}</strong>
            <small>${escapeHtml(busDetail)}</small>
          </span>
          <span class="inventory-cell" data-label="Hardware">
            <strong>${escapeHtml(hardware || "Eco-worthy battery")}</strong>
            <small>${escapeHtml(battery.firmware_version ? `Firmware ${battery.firmware_version}` : "Firmware pending")}</small>
          </span>
          <span class="inventory-cell inventory-cell--state" data-label="State">
            <span class="status-pill ${status.className}">${status.label}</span>
            <small>${battery.last_polled_at ? `Seen ${formatRelativeTime(battery.last_polled_at)}` : "Not seen yet"}</small>
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
      refreshHistory().catch((error) => handleResourceFailure("history", error));
    });
  });
}

function renderSelectedBattery() {
  const battery = selectedBattery();
  if (!battery) {
    $("selectedName").textContent = "Rack";
    $("selectedState").textContent = "Pending";
    $("cellStrip").innerHTML = "";
    $("temperatureRow").innerHTML = "";
    $("detailList").innerHTML = "";
    $("payloadView").textContent = "";
    return;
  }

  const reading = battery.last_reading || {};
  const profile = batteryProfile(battery);
  $("selectedName").textContent = profile?.name || battery.id;
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
    strip.innerHTML = `<div class="empty-mini">No cell data</div>`;
    return;
  }
  const min = Math.min(...cells);
  const max = Math.max(...cells);
  for (const [index, voltage] of cells.entries()) {
    const height = 28 + ((voltage - min) / Math.max(max - min, 0.001)) * 58;
    const cell = document.createElement("div");
    cell.className = "cell-bar";
    cell.style.height = `${height}px`;
    cell.title = `Cell ${index + 1}: ${voltage.toFixed(3)} V`;
    cell.innerHTML = `<span>${index + 1}</span>`;
    strip.appendChild(cell);
  }
}

function renderTemperatures(temperatures) {
  const row = $("temperatureRow");
  row.innerHTML = "";
  if (!temperatures.length) {
    row.innerHTML = `<div class="empty-mini">No temperature data</div>`;
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
    ["Battery ID", battery.id],
    ["IP address", profile?.ip_address || "Not configured"],
    ["Model", profile?.model],
    ["Address", battery.address],
    ["State", reading.operation_status],
    ["SOH", formatValue(reading.soh_percent, "%")],
    ["Cycles", reading.cycle_count],
    ["Remaining", formatValue(reading.remaining_capacity_ah, "Ah")],
    ["Full", formatValue(reading.full_capacity_ah, "Ah")],
    ["Charge limit", formatValue(reading.charge_current_limit_a, "A")],
    ["Discharge limit", formatValue(reading.discharge_current_limit_a, "A")],
    ["Firmware", reading.firmware_version],
    ["Serial", reading.serial_number],
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
    list.innerHTML = `<div class="empty-mini">No recent events</div>`;
    return;
  }
  list.innerHTML = events
    .map((event) => {
      const labels = [...(event.faults || []), ...(event.alarms || [])];
      const title = labels.length ? labels.join(", ") : event.last_error || event.status;
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
  const history = state.history.filter(
    (point) => Number.isFinite(point.unix) && Number.isFinite(point.value),
  );

  if (!history.length) {
    drawEmptyChart(ctx, theme, pad, width, height);
    state.chartGeometry = null;
    $("chartLegend").innerHTML = "";
    hideChartTooltip(false);
    return;
  }

  const groups = groupBy(history, "battery_id");
  const times = history.map((point) => point.unix);
  const values = history.map((point) => point.value);
  const minTime = Math.min(...times);
  const maxTime = Math.max(...times);
  let minValue = Math.min(...values);
  let maxValue = Math.max(...values);
  if (minValue === maxValue) {
    const spread = Math.max(Math.abs(minValue) * 0.02, 0.1);
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
  Array.from(groups.entries()).forEach(([batteryId, rawPoints], index) => {
    const color = palette[index % palette.length];
    const points = [...rawPoints]
      .sort((a, b) => a.unix - b.unix)
      .map((point) => ({
        point,
        batteryId,
        color,
        x: pad.left + scale(point.unix, minTime, maxTime, 0, width),
        y: pad.top + height - scale(point.value, minValue, maxValue, 0, height),
      }));
    plottedPoints.push(...points);
    drawHistorySeries(ctx, points, color, pad.top + height);
  });
  ctx.restore();

  state.chartGeometry = {
    points: plottedPoints,
    plot: { left: pad.left, right: pad.left + width, top: pad.top, bottom: pad.top + height },
  };
  renderChartLegend(groups);

  const activePoint = state.chartHover
    ? plottedPoints.find(
        (item) =>
          item.batteryId === state.chartHover.batteryId && item.point.unix === state.chartHover.unix,
      )
    : null;
  if (activePoint) {
    drawChartFocus(ctx, activePoint, theme, pad.top, pad.top + height);
    renderChartTooltip(activePoint, rect);
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
    state.resourceErrors.history ? "History temporarily unavailable" : "Awaiting history",
    pad.left,
    pad.top + 28,
  );
}

function drawChartGrid(ctx, theme, pad, width, height, minTime, maxTime, minValue, maxValue) {
  ctx.save();
  ctx.lineWidth = 1;
  ctx.font = "11px -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif";
  ctx.fillStyle = theme.chartMuted;

  for (let index = 0; index <= 4; index += 1) {
    const y = pad.top + (height * index) / 4;
    const value = maxValue - ((maxValue - minValue) * index) / 4;
    ctx.strokeStyle = theme.chartGrid;
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(pad.left + width, y);
    ctx.stroke();
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    ctx.fillText(formatHistoryValue(value), pad.left - 9, y);
  }

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

function drawHistorySeries(ctx, points, color, baseline) {
  if (!points.length) return;
  const gradient = ctx.createLinearGradient(0, Math.min(...points.map((item) => item.y)), 0, baseline);
  gradient.addColorStop(0, hexToRgba(color, 0.18));
  gradient.addColorStop(1, hexToRgba(color, 0));

  ctx.beginPath();
  points.forEach((item, index) => {
    if (index === 0) ctx.moveTo(item.x, item.y);
    else ctx.lineTo(item.x, item.y);
  });
  ctx.lineTo(points[points.length - 1].x, baseline);
  ctx.lineTo(points[0].x, baseline);
  ctx.closePath();
  ctx.fillStyle = gradient;
  ctx.fill();

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

function drawChartFocus(ctx, activePoint, theme, top, bottom) {
  ctx.save();
  ctx.strokeStyle = theme.chartMuted;
  ctx.lineWidth = 1;
  ctx.setLineDash([4, 5]);
  ctx.beginPath();
  ctx.moveTo(activePoint.x, top);
  ctx.lineTo(activePoint.x, bottom);
  ctx.stroke();
  ctx.setLineDash([]);

  ctx.beginPath();
  ctx.arc(activePoint.x, activePoint.y, 7, 0, Math.PI * 2);
  ctx.fillStyle = theme.chartInk;
  ctx.fill();
  ctx.beginPath();
  ctx.arc(activePoint.x, activePoint.y, 4, 0, Math.PI * 2);
  ctx.fillStyle = activePoint.color;
  ctx.fill();
  ctx.restore();
}

function renderChartLegend(groups) {
  const legend = $("chartLegend");
  const items = Array.from(groups.entries()).map(([batteryId, points], index) => ({
    batteryId,
    color: palette[index % palette.length],
    point: points[points.length - 1],
  }));
  const signature = `${state.metric}:${items
    .map((item) => `${item.batteryId}:${item.point.unix}:${item.point.value}`)
    .join("|")}`;
  if (legend.dataset.signature === signature) return;
  legend.dataset.signature = signature;
  legend.innerHTML = items
    .map(
      (item) => `
        <span class="chart-legend__item">
          <span class="chart-legend__swatch" style="--series-color: ${item.color}"></span>
          <strong>${escapeHtml(item.batteryId)}</strong>
          <span>${formatHistoryValue(item.point.value)}</span>
        </span>
      `,
    )
    .join("");
}

function renderChartTooltip(activePoint, canvasRect) {
  const tooltip = $("chartTooltip");
  const value = formatHistoryValue(activePoint.point.value);
  const timestamp = formatChartTimestamp(activePoint.point.timestamp || activePoint.point.unix * 1000);
  tooltip.innerHTML = `
    <span class="chart-tooltip__swatch" style="--series-color: ${activePoint.color}"></span>
    <span class="chart-tooltip__identity">
      <strong>${escapeHtml(activePoint.batteryId)}</strong>
      <time>${escapeHtml(timestamp)}</time>
    </span>
    <strong class="chart-tooltip__value">${escapeHtml(value)}</strong>
  `;
  tooltip.hidden = false;

  if (canvasRect.width < 540) {
    tooltip.dataset.mobile = "true";
    tooltip.style.left = "12px";
    tooltip.style.top = "12px";
  } else {
    delete tooltip.dataset.mobile;
    tooltip.style.left = `${clamp(activePoint.x, 116, canvasRect.width - 116)}px`;
    tooltip.style.top = `${activePoint.y}px`;
    tooltip.classList.toggle("is-below", activePoint.y < 96);
  }
  $("historyChart").setAttribute(
    "aria-label",
    `${metricLabels[state.metric]} for ${activePoint.batteryId}: ${value}, ${timestamp}`,
  );
}

function hideChartTooltip(redraw = true) {
  state.chartHover = null;
  const tooltip = $("chartTooltip");
  tooltip.hidden = true;
  tooltip.classList.remove("is-below");
  delete tooltip.dataset.mobile;
  $("historyChart").setAttribute("aria-label", `${metricLabels[state.metric]} history chart`);
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
  state.chartHover = { batteryId: nearest.batteryId, unix: nearest.point.unix };
  drawChart();
}

function queueChartHover(clientX, clientY) {
  window.cancelAnimationFrame(chartPointerFrame);
  chartPointerFrame = window.requestAnimationFrame(() => updateChartHoverFromClient(clientX, clientY));
}

function moveChartKeyboardSelection(key) {
  const points = [...(state.chartGeometry?.points || [])].sort(
    (a, b) => a.point.unix - b.point.unix || a.batteryId.localeCompare(b.batteryId),
  );
  if (!points.length) return;
  const currentIndex = points.findIndex(
    (item) => item.batteryId === state.chartHover?.batteryId && item.point.unix === state.chartHover?.unix,
  );
  let nextIndex = currentIndex;
  if (key === "Home") nextIndex = 0;
  else if (key === "End") nextIndex = points.length - 1;
  else if (key === "ArrowLeft") nextIndex = currentIndex < 0 ? points.length - 1 : currentIndex - 1;
  else if (key === "ArrowRight") nextIndex = currentIndex < 0 ? 0 : currentIndex + 1;
  nextIndex = clamp(nextIndex, 0, points.length - 1);
  const next = points[nextIndex];
  state.chartHover = { batteryId: next.batteryId, unix: next.point.unix };
  drawChart();
}

function formatHistoryValue(value) {
  return formatValue(value, metricUnits[state.metric], metricDigits[state.metric] ?? 2);
}

function formatChartTick(unix) {
  const date = new Date(unix * 1000);
  if (state.range === "1h" || state.range === "24h") {
    return new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" }).format(date);
  }
  if (state.range === "3y") {
    return new Intl.DateTimeFormat(undefined, { month: "short", year: "2-digit" }).format(date);
  }
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(date);
}

function formatChartTimestamp(value) {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(value));
}

function hexToRgba(hex, alpha) {
  const value = hex.replace("#", "");
  const red = Number.parseInt(value.slice(0, 2), 16);
  const green = Number.parseInt(value.slice(2, 4), 16);
  const blue = Number.parseInt(value.slice(4, 6), 16);
  return `rgba(${red}, ${green}, ${blue}, ${alpha})`;
}

function selectedBattery() {
  return state.batteries.find((battery) => battery.id === state.selectedBatteryId) || state.batteries[0];
}

function batteryProfile(battery) {
  return (state.rack.batteries || []).find(
    (profile) => profile.id === battery.id || profile.address === battery.address,
  );
}

function statusPresentation(status) {
  if (status === "ok") return { label: "Online", className: "status-pill--ok" };
  if (status === "error") return { label: "Needs attention", className: "status-pill--error" };
  if (status === "disabled") return { label: "Disabled", className: "" };
  if (status === "stale") return { label: "Last known", className: "status-pill--pending" };
  return { label: "Waiting", className: "status-pill--pending" };
}

function connectionPresentation(status) {
  if (status === "online") {
    return {
      label: "Collector online",
      className: "status-pill--ok",
      description: "Collector and all configured batteries are responding",
    };
  }
  if (status === "degraded") {
    return {
      label: "Collector degraded",
      className: "status-pill--warning",
      description: "Collector is reachable, but one or more batteries need attention",
    };
  }
  if (status === "stale") {
    return {
      label: "Data stale",
      className: "status-pill--stale",
      description: "Last known data is being shown while the collector reconnects",
    };
  }
  return {
    label: "Collector offline",
    className: "status-pill--error",
    description: "The collector has not responded within the offline threshold",
  };
}

function batteryDotClass(status) {
  if (!state.collectorOnline) return "dot";
  if (status === "ok") return "dot dot--ok";
  if (status === "error") return "dot dot--error";
  return "dot";
}

function groupBy(items, key) {
  const map = new Map();
  for (const item of items) {
    const value = item[key];
    if (!map.has(value)) map.set(value, []);
    map.get(value).push(item);
  }
  return map;
}

function formatValue(value, unit = "", digits = 1) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "--";
  return `${value.toFixed(digits).replace(/\.0$/, "")}${unit}`;
}

function compactNumber(value) {
  if (typeof value !== "number") return "--";
  return new Intl.NumberFormat(undefined, { notation: "compact" }).format(value);
}

function formatNumber(value) {
  return new Intl.NumberFormat().format(value);
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
  if (!Number.isFinite(deltaSeconds)) return "recently";
  const formatter = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
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
  return `${size.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function formatTime(value) {
  return new Intl.DateTimeFormat(undefined, {
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(value));
}

function shortDate(value) {
  return new Intl.DateTimeFormat(undefined, {
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
  initTheme();

  $("metricSelect").addEventListener("change", (event) => {
    state.metric = event.target.value;
    hideChartTooltip(false);
    refreshHistory().catch((error) => handleResourceFailure("history", error));
  });

  document.querySelectorAll(".segmented button").forEach((button) => {
    button.addEventListener("click", () => {
      state.range = button.dataset.range;
      document.querySelectorAll(".segmented button").forEach((item) => item.classList.remove("is-active"));
      button.classList.add("is-active");
      hideChartTooltip(false);
      refreshHistory().catch((error) => handleResourceFailure("history", error));
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
  if ("ResizeObserver" in window) {
    const observer = new ResizeObserver(() => {
      window.cancelAnimationFrame(chartResizeFrame);
      chartResizeFrame = window.requestAnimationFrame(drawChart);
    });
    observer.observe(chartContainer);
  } else {
    window.addEventListener("resize", () => {
      window.cancelAnimationFrame(chartResizeFrame);
      chartResizeFrame = window.requestAnimationFrame(drawChart);
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
  window.addEventListener("offline", () => renderLiveFailure("Browser network is offline"));
}

bindControls();
refreshCycle(true);
