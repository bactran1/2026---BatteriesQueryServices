const state = {
  batteries: [],
  selectedBatteryId: null,
  metric: "soc_percent",
  range: "24h",
  history: [],
  storage: {},
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

const palette = ["#0a84ff", "#30d158", "#ff9f0a", "#bf5af2", "#ff453a"];

const $ = (id) => document.getElementById(id);
const THEME_STORAGE_KEY = "battery-monitor-theme";

async function refreshAll() {
  await refreshLive();
  await Promise.all([refreshHistory(), refreshEvents()]);
}

async function refreshLive() {
  try {
    const payload = await getJson("/api/live");
    state.batteries = payload.snapshot?.batteries || [];
    state.storage = payload.storage || {};
    if (!state.selectedBatteryId && state.batteries.length) {
      state.selectedBatteryId = state.batteries[0].id;
    }
    renderStatus(payload);
    renderSummary(payload.summary || {});
    renderBatteryCards();
    renderSelectedBattery();
    renderStorage();
  } catch (error) {
    $("collectorStatus").textContent = "Offline";
    $("collectorStatus").className = "status-pill status-pill--error";
  }
}

async function refreshHistory() {
  const params = new URLSearchParams({
    battery_id: state.selectedBatteryId || "all",
    metric: state.metric,
    range: state.range,
  });
  const payload = await getJson(`/api/history?${params}`);
  state.history = payload.points || [];
  $("chartTitle").textContent = metricLabels[state.metric] || state.metric;
  drawChart();
}

async function refreshEvents() {
  const payload = await getJson("/api/events?range=7d&limit=80");
  renderEvents(payload.events || []);
}

async function getJson(url) {
  const response = await fetch(url, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json();
}

function renderStatus(payload) {
  const pill = $("collectorStatus");
  const online = payload.collector_status === "ok";
  pill.textContent = online ? "Collector online" : "Collector offline";
  pill.className = `status-pill ${online ? "status-pill--ok" : "status-pill--error"}`;

  const newest = payload.storage?.newest_reading_at;
  $("lastUpdated").textContent = newest ? `Logged ${formatTime(newest)}` : "No readings yet";
}

function renderSummary(summary) {
  $("fleetSoc").textContent = formatValue(summary.average_soc_percent, "%");
  $("fleetPower").textContent = formatValue(summary.total_power_w, "W");
  $("fleetCapacity").textContent = formatValue(summary.remaining_capacity_ah, "Ah");
  const alerts = (summary.alarm_count || 0) + (summary.fault_count || 0);
  $("fleetAlerts").textContent = `${alerts}`;
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
    const soc = clamp(reading.soc_percent ?? 0, 0, 100);
    const card = document.createElement("button");
    card.type = "button";
    card.className = `battery-card ${battery.id === state.selectedBatteryId ? "is-selected" : ""}`;
    card.addEventListener("click", () => {
      state.selectedBatteryId = battery.id;
      renderBatteryCards();
      renderSelectedBattery();
      refreshHistory();
    });

    card.innerHTML = `
      <div class="battery-card__top">
        <span>${escapeHtml(battery.id)}</span>
        <span class="${battery.status === "ok" ? "dot dot--ok" : "dot dot--error"}"></span>
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
  $("selectedName").textContent = battery.id;
  $("selectedState").textContent = battery.status || "pending";
  $("selectedState").className = `status-pill ${battery.status === "ok" ? "status-pill--ok" : "status-pill--error"}`;

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
  const details = [
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
    .map(([label, value]) => `<div><dt>${label}</dt><dd>${value ?? "--"}</dd></div>`)
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
    ctx.fillText("Awaiting history", pad.left, pad.top + 28);
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
    refreshHistory();
  });

  document.querySelectorAll(".segmented button").forEach((button) => {
    button.addEventListener("click", () => {
      state.range = button.dataset.range;
      document.querySelectorAll(".segmented button").forEach((item) => item.classList.remove("is-active"));
      button.classList.add("is-active");
      refreshHistory();
    });
  });

  $("exportButton").addEventListener("click", () => {
    const batteryId = state.selectedBatteryId || "all";
    window.location.href = `/api/export.csv?battery_id=${encodeURIComponent(batteryId)}&days=30`;
  });

  window.addEventListener("resize", drawChart);
}

bindControls();
refreshAll();
setInterval(refreshLive, 5000);
setInterval(refreshHistory, 30000);
setInterval(refreshEvents, 30000);
