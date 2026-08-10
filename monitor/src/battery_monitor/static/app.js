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
  if (!state.selectedBatteryId && state.batteries.length) {
    state.selectedBatteryId = state.batteries[0].id;
  }
  renderStatus(payload);
  renderRackOverview();
  renderSummary(payload.summary || {});
  renderBatteryCards();
  renderBatteryInventory();
  renderSelectedBattery();
  renderStorage();
}

async function refreshHistory() {
  const params = new URLSearchParams({
    battery_id: state.selectedBatteryId || "all",
    metric: state.metric,
    range: state.range,
  });
  const payload = await getJson(`/api/history?${params}`, "history");
  state.history = payload.points || [];
  state.lastHistoryRefreshAt = Date.now();
  state.resourceErrors.history = null;
  $("historyChart").removeAttribute("data-refresh-error");
  $("chartTitle").textContent = metricLabels[state.metric] || state.metric;
  drawChart();
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
  $("fleetSoc").textContent = formatValue(summary.average_soc_percent, "%");
  $("fleetPower").textContent = formatValue(summary.total_power_w, "W");
  $("fleetCapacity").textContent = formatValue(summary.remaining_capacity_ah, "Ah");
  const alerts = (summary.alarm_count || 0) + (summary.fault_count || 0);
  $("fleetAlerts").textContent = `${alerts}`;
}

function renderRackOverview() {
  const rack = state.rack;
  const expected = rack.expected_battery_count ?? rack.batteries?.length ?? 0;
  const observed = rack.observed_battery_count ?? 0;
  const online = rack.online_battery_count ?? 0;

  $("builderLine").textContent = `The system is built by ${rack.builder || "Tran Thanh Tuan"} and son`;
  $("rackDescription").textContent = `${expected} ${pluralize(expected, "battery", "batteries")} configured for local monitoring with a ${formatNumber(rack.retention_days || 1095)}-day archive.`;
  $("rackBatteryCount").textContent = `${expected} configured`;
  $("rackObservedCount").textContent = `${observed} reporting · ${online} online`;
  $("rackCollectorName").textContent = rack.collector?.name || "Raspberry Pi collector";
  $("rackCollectorAddress").textContent = hostFromUrl(rack.collector?.url) || "Not configured";
  $("rackConnection").textContent = rack.connection || "Modbus RTU over RS485";
  $("rackLocation").textContent = rack.location || "Not specified";
  $("rackRetention").textContent = `${formatNumber(rack.retention_days || 1095)}-day archive`;
}

function renderBatteryCards() {
  const grid = $("batteryGrid");
  grid.innerHTML = "";
  if (!state.batteries.length) {
    grid.innerHTML = `<div class="empty-state">Awaiting readings</div>`;
    return;
  }

  for (const battery of state.batteries) {
    const reading = battery.last_reading || {};
    const profile = batteryProfile(battery);
    const soc = clamp(reading.soc_percent ?? 0, 0, 100);
    const card = document.createElement("button");
    card.type = "button";
    card.className = `battery-card ${battery.id === state.selectedBatteryId ? "is-selected" : ""}`;
    card.addEventListener("click", () => {
      state.selectedBatteryId = battery.id;
      renderBatteryCards();
      renderBatteryInventory();
      renderSelectedBattery();
      refreshHistory().catch((error) => handleResourceFailure("history", error));
    });

    card.innerHTML = `
      <div class="battery-card__top">
        <span>
          <strong>${escapeHtml(profile?.name || battery.id)}</strong>
          <small>${escapeHtml(battery.id)} · RS485 ${escapeHtml(battery.address ?? "--")}</small>
        </span>
        <span class="${batteryDotClass(battery.status)}"></span>
      </div>
      <div class="soc-ring" style="--soc:${soc}">
        <span>${Number.isFinite(soc) ? Math.round(soc) : "--"}%</span>
      </div>
      <div class="battery-card__metrics">
        <div><span>Voltage</span><strong>${formatValue(reading.voltage_v, "V")}</strong></div>
        <div><span>Current</span><strong>${formatValue(reading.current_a, "A")}</strong></div>
        <div><span>Power</span><strong>${formatValue(reading.power_w, "W")}</strong></div>
        <div><span>Cell Δ</span><strong>${formatValue(reading.cell_voltage_delta_v, "V", 3)}</strong></div>
      </div>
    `;
    grid.appendChild(card);
  }
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

function drawChart() {
  const canvas = $("historyChart");
  const ctx = canvas.getContext("2d");
  const theme = getThemeColors();
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = Math.max(1, Math.floor(rect.width * dpr));
  canvas.height = Math.max(1, Math.floor(rect.height * dpr));
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, rect.width, rect.height);

  const pad = { top: 18, right: 20, bottom: 34, left: 54 };
  const width = rect.width - pad.left - pad.right;
  const height = rect.height - pad.top - pad.bottom;

  ctx.strokeStyle = theme.chartGrid;
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i += 1) {
    const y = pad.top + (height * i) / 4;
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(pad.left + width, y);
    ctx.stroke();
  }

  if (!state.history.length) {
    ctx.fillStyle = theme.chartMuted;
    ctx.font = "14px -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif";
    ctx.fillText(
      state.resourceErrors.history ? "History temporarily unavailable" : "Awaiting history",
      pad.left,
      pad.top + 28,
    );
    return;
  }

  const groups = groupBy(state.history, "battery_id");
  const times = state.history.map((point) => point.unix);
  const values = state.history.map((point) => point.value);
  const minTime = Math.min(...times);
  const maxTime = Math.max(...times);
  let minValue = Math.min(...values);
  let maxValue = Math.max(...values);
  if (minValue === maxValue) {
    minValue -= 1;
    maxValue += 1;
  }
  const padding = (maxValue - minValue) * 0.08;
  minValue -= padding;
  maxValue += padding;

  Array.from(groups.entries()).forEach(([batteryId, points], index) => {
    ctx.strokeStyle = palette[index % palette.length];
    ctx.lineWidth = 2.5;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    ctx.beginPath();
    points.forEach((point, pointIndex) => {
      const x = pad.left + scale(point.unix, minTime, maxTime, 0, width);
      const y = pad.top + height - scale(point.value, minValue, maxValue, 0, height);
      if (pointIndex === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();

    const last = points[points.length - 1];
    const labelX = pad.left + width - 64;
    const labelY = pad.top + 18 + index * 20;
    ctx.fillStyle = palette[index % palette.length];
    ctx.fillRect(labelX, labelY - 9, 8, 8);
    ctx.fillStyle = theme.chartInk;
    ctx.font = "12px -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif";
    ctx.fillText(`${batteryId} ${formatValue(last.value, metricUnits[state.metric], 2)}`, labelX + 14, labelY);
  });

  ctx.fillStyle = theme.chartMuted;
  ctx.font = "12px -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif";
  ctx.fillText(formatValue(maxValue, metricUnits[state.metric], 2), 10, pad.top + 4);
  ctx.fillText(formatValue(minValue, metricUnits[state.metric], 2), 10, pad.top + height);
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
    refreshHistory().catch((error) => handleResourceFailure("history", error));
  });

  document.querySelectorAll(".segmented button").forEach((button) => {
    button.addEventListener("click", () => {
      state.range = button.dataset.range;
      document.querySelectorAll(".segmented button").forEach((item) => item.classList.remove("is-active"));
      button.classList.add("is-active");
      refreshHistory().catch((error) => handleResourceFailure("history", error));
    });
  });

  $("exportButton").addEventListener("click", () => {
    const batteryId = state.selectedBatteryId || "all";
    window.location.href = `/api/export.csv?battery_id=${encodeURIComponent(batteryId)}&days=30`;
  });

  const chartContainer = $("historyChart").parentElement;
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
