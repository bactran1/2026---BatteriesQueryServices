"use strict";

const $ = (id) => document.getElementById(id);
let csrf = null;
let paused = false;
let sessionMinutes = 30;
let idleTimer = 0;
let lastSlideAt = 0;
let activityBound = false;
const ACTIVITY_EVENTS = ["pointerdown", "pointermove", "keydown", "wheel", "touchstart"];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
}

function toast(message, kind = "ok") {
  const el = $("adminToast");
  el.textContent = message;
  el.className = `admin-toast admin-toast--${kind === "bad" ? "bad" : "ok"}`;
  el.hidden = false;
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => { el.hidden = true; }, 4500);
}

async function api(method, path, body) {
  const options = { method, credentials: "same-origin", headers: {} };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  if (method !== "GET") options.headers["X-CSRF-Token"] = csrf || "";
  const response = await fetch(path, options);
  let data = null;
  try { data = await response.json(); } catch (error) { /* not JSON */ }
  if (response.status === 401) {
    showLogin();
    throw new Error((data && data.detail) || "Session expired — sign in again");
  }
  if (!response.ok) {
    throw new Error((data && (data.detail || data.error)) || `Request failed (${response.status})`);
  }
  return data;
}

function formatBytes(bytes) {
  const value = Number(bytes);
  if (!Number.isFinite(value) || value <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const power = Math.min(units.length - 1, Math.floor(Math.log(value) / Math.log(1024)));
  return `${(value / 1024 ** power).toFixed(power ? 1 : 0)} ${units[power]}`;
}

function formatWhen(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

function renderKv(el, entries) {
  el.innerHTML = entries
    .map(([key, value, cls]) => `<div><dt>${esc(key)}</dt><dd class="${cls || ""}">${esc(value)}</dd></div>`)
    .join("");
}

// ---------------------------------------------------------------------------
// Idle auto-logout (timeout is configurable on the admin page)
// ---------------------------------------------------------------------------
function resetIdle() {
  if (!activityBound) return;
  clearTimeout(idleTimer);
  idleTimer = setTimeout(autoLogout, Math.max(1, sessionMinutes) * 60_000);
}

function onActivity() {
  resetIdle();
  // Slide the server-side session too, but no more than once a minute.
  const now = Date.now();
  if (now - lastSlideAt > 60_000) {
    lastSlideAt = now;
    slideSession();
  }
}

function onVisibility() {
  // A background tab's timers get throttled, so re-check the server session
  // whenever the tab is shown again in case it lapsed while hidden.
  if (!document.hidden) slideSession();
}

async function slideSession() {
  try {
    const session = await api("GET", "/api/admin/session");
    if (!session.authenticated) {
      autoLogout();
      return;
    }
    if (session.csrf) csrf = session.csrf;
    if (Number.isFinite(session.session_minutes)) {
      sessionMinutes = session.session_minutes;
      resetIdle();
    }
  } catch (error) {
    /* transient network error — leave the local timer running */
  }
}

function startIdleWatch() {
  if (!activityBound) {
    ACTIVITY_EVENTS.forEach((type) =>
      document.addEventListener(type, onActivity, { passive: true }));
    document.addEventListener("visibilitychange", onVisibility);
    activityBound = true;
  }
  lastSlideAt = Date.now();
  resetIdle();
}

function stopIdleWatch() {
  clearTimeout(idleTimer);
  idleTimer = 0;
  if (activityBound) {
    ACTIVITY_EVENTS.forEach((type) => document.removeEventListener(type, onActivity));
    document.removeEventListener("visibilitychange", onVisibility);
    activityBound = false;
  }
}

let autoLogoutInFlight = false;
async function autoLogout() {
  if (autoLogoutInFlight) return;
  autoLogoutInFlight = true;
  stopIdleWatch();
  try { await api("POST", "/api/admin/logout", {}); } catch (error) { /* ignore */ }
  showLogin();
  toast(`Signed out after ${sessionMinutes} minute(s) of inactivity.`, "bad");
  autoLogoutInFlight = false;
}

// ---------------------------------------------------------------------------
// View switching
// ---------------------------------------------------------------------------
function showLogin(notConfigured = false) {
  stopIdleWatch();
  csrf = null;
  $("adminPanel").hidden = true;
  $("adminLogin").hidden = false;
  $("adminLogout").hidden = true;
  const hint = $("adminLoginHint");
  const input = $("adminPassword");
  const submit = $("adminLoginForm").querySelector("button[type=submit]");
  if (notConfigured) {
    hint.textContent = "Admin is not configured. Set BQM_ADMIN_PASSWORD on the server and restart.";
    input.disabled = true;
    submit.disabled = true;
  } else {
    hint.textContent = "Enter the admin password to continue.";
    input.disabled = false;
    submit.disabled = false;
  }
}

function showPanel() {
  $("adminLogin").hidden = true;
  $("adminPanel").hidden = false;
  $("adminLogout").hidden = false;
  startIdleWatch();
  loadAll();
}

async function loadAll() {
  await Promise.allSettled([loadAppInfo(), loadStorage(), loadDiagnostics(), loadConfig()]);
}

// ---------------------------------------------------------------------------
// Loaders
// ---------------------------------------------------------------------------
async function loadAppInfo() {
  const info = await api("GET", "/api/admin/app-info");
  paused = Boolean(info.paused);
  updatePauseButton();
  renderKv($("adminAppInfo"), [
    ["Version", info.version],
    ["Build", info.build_commit],
    ["Started", formatWhen(info.started_at)],
    ["Polling", paused ? "Paused" : "Active", paused ? "is-bad" : "is-ok"],
    ["Retention", `${info.retention_days} days`],
    ["Auto-logout", `${info.session_minutes} min idle`],
    ["Poll interval", `${info.live_poll_interval_seconds}s`],
    ["Collector URL", info.collector_url],
    ["Database", info.database_path],
  ]);
}

async function loadStorage() {
  const { stats, health, integrity } = await api("GET", "/api/admin/storage");
  const healthy = health && health.status === "ok";
  const intact = integrity && integrity.ok;
  renderKv($("adminStorage"), [
    ["Rows", Number(stats.row_count).toLocaleString()],
    ["Database size", formatBytes(stats.database_size_bytes)],
    ["Battery packs", stats.battery_count],
    ["Oldest reading", formatWhen(stats.oldest_reading_at)],
    ["Newest reading", formatWhen(stats.newest_reading_at)],
    ["Inverter points", Number(stats.inverter_point_count || 0).toLocaleString()],
    ["Energy points", Number(stats.energy_point_count || 0).toLocaleString()],
    ["Writable", healthy ? "Yes" : "No", healthy ? "is-ok" : "is-bad"],
    ["Integrity", intact ? "OK" : (integrity && integrity.integrity_check) || "Unknown", intact ? "is-ok" : "is-bad"],
  ]);
}

async function loadDiagnostics() {
  const data = await api("GET", "/api/admin/diagnostics");
  const monitor = data.monitor || {};
  paused = Boolean(data.paused);
  updatePauseButton();
  const reachable = Boolean(data.collector_reachable);
  renderKv($("adminDiagnostics"), [
    ["Collector", data.collector_status, data.collector_status === "online" ? "is-ok" : "is-bad"],
    ["Reachable", reachable ? "Yes" : "No", reachable ? "is-ok" : "is-bad"],
    ["Polling", paused ? "Paused" : "Active", paused ? "is-bad" : "is-ok"],
    ["Last success", formatWhen(monitor.last_success_at)],
    ["Last data", formatWhen(monitor.last_data_at)],
    ["Last prune", formatWhen(monitor.last_prune_at)],
    ["Failures in a row", monitor.consecutive_failures ?? 0],
    ["Last error", monitor.collector_error || "None", monitor.collector_error ? "is-bad" : "is-ok"],
  ]);
}

async function loadConfig() {
  const config = await api("GET", "/api/admin/config");
  const form = $("adminConfigForm");
  form.rack_name.value = config.rack_name || "";
  form.rack_builder.value = config.rack_builder || "";
  form.rack_location.value = config.rack_location || "";
  form.collector_name.value = config.collector_name || "";
  form.retention_days.value = config.retention_days ?? "";
  form.session_minutes.value = config.session_minutes ?? 30;
  form.battery_reserve_percent.value = config.battery_reserve_percent ?? 20;
  if (Number.isFinite(config.session_minutes)) {
    sessionMinutes = config.session_minutes;
    resetIdle();
  }
  const glow = Number(config.energy_glow_strength ?? 0.05);
  $("adminGlow").value = String(glow);
  $("adminGlowValue").textContent = glow.toFixed(2);
  $("adminLineGlow").checked = config.energy_line_glow === true;
  renderBatteryRows(config.batteries || []);
}

function renderBatteryRows(batteries) {
  $("adminBatteries").innerHTML = batteries
    .map((battery) => `
      <tr>
        <td><input data-field="id" value="${esc(battery.id)}" readonly /></td>
        <td><input data-field="name" value="${esc(battery.name)}" /></td>
        <td><input data-field="address" type="number" value="${esc(battery.address)}" /></td>
        <td><input data-field="ip_address" value="${esc(battery.ip_address)}" placeholder="—" /></td>
        <td><input data-field="model" value="${esc(battery.model)}" /></td>
      </tr>`)
    .join("");
}

function readBatteryRows() {
  return Array.from($("adminBatteries").querySelectorAll("tr")).map((row) => {
    const cell = (field) => row.querySelector(`input[data-field="${field}"]`).value.trim();
    return {
      id: cell("id"),
      name: cell("name"),
      address: Number(cell("address")),
      ip_address: cell("ip_address"),
      model: cell("model"),
    };
  });
}

function updatePauseButton() {
  const button = $("adminPauseBtn");
  if (button) button.textContent = paused ? "Resume polling" : "Pause polling";
}

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------
async function downloadBackup() {
  const response = await fetch("/api/admin/backup.sqlite", { credentials: "same-origin" });
  if (response.status === 401) { showLogin(); throw new Error("Session expired"); }
  if (!response.ok) throw new Error(`Backup failed (${response.status})`);
  const blob = await response.blob();
  const match = /filename="?([^"]+)"?/.exec(response.headers.get("Content-Disposition") || "");
  const name = match ? match[1] : "battery-monitor-backup.sqlite3";
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

const actions = {
  "refresh-info": () => wrap(loadAppInfo, "Application info refreshed"),
  "refresh-storage": () => wrap(loadStorage, "Storage refreshed"),
  "refresh-diagnostics": () => wrap(loadDiagnostics, "Diagnostics refreshed"),
  "reload-config": () => wrap(loadConfig, "Configuration reloaded"),
  prune: async () => {
    const result = await api("POST", "/api/admin/prune", {});
    await loadStorage();
    toast(`Pruned ${result.deleted} row(s) beyond ${result.retention_days} days.`);
  },
  backup: async () => { await downloadBackup(); toast("Backup downloaded."); },
  reset: async () => {
    const typed = window.prompt('This permanently deletes ALL stored history. Type DELETE to confirm.');
    if (typed === null) return;
    if (typed !== "DELETE") { toast("Reset cancelled — confirmation did not match.", "bad"); return; }
    const result = await api("POST", "/api/admin/reset", { confirm: "DELETE" });
    await Promise.allSettled([loadStorage(), loadDiagnostics()]);
    const total = Object.values(result.deleted || {}).reduce((sum, n) => sum + Number(n || 0), 0);
    toast(`All history erased (${total} row(s) removed).`);
  },
  poll: async () => {
    const result = await api("POST", "/api/admin/poll", {});
    await loadDiagnostics();
    toast(result.polled ? `Poll complete — ${result.inserted} reading(s) stored.` : "Poll attempted but collector was unreachable.", result.polled ? "ok" : "bad");
  },
  "toggle-polling": async () => {
    const result = await api("POST", "/api/admin/polling", { paused: !paused });
    paused = Boolean(result.paused);
    updatePauseButton();
    toast(paused ? "Background polling paused." : "Background polling resumed.");
  },
  "collector-test": async () => {
    const result = await api("GET", "/api/admin/collector-test");
    const el = $("adminCollectorResult");
    el.hidden = false;
    if (result.reachable) {
      el.textContent = `✓ Reachable in ${result.latency_ms} ms · ${result.battery_count} battery(ies) · ${result.collector_url}`;
      el.style.color = "var(--green)";
    } else {
      el.textContent = `✗ Unreachable (${result.error || "unknown error"}) · ${result.collector_url}`;
      el.style.color = "var(--red)";
    }
  },
};

async function runAction(name, button) {
  const handler = actions[name];
  if (!handler) return;
  if (button) button.disabled = true;
  try {
    await handler();
  } catch (error) {
    toast(error.message || "Action failed", "bad");
  } finally {
    if (button) button.disabled = false;
  }
}

// ---------------------------------------------------------------------------
// Wiring
// ---------------------------------------------------------------------------
async function wrap(loader, message) {
  await loader();
  toast(message);
}

function bind() {
  $("adminLoginForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const error = $("adminLoginError");
    error.hidden = true;
    try {
      const result = await api("POST", "/api/admin/login", { password: $("adminPassword").value });
      csrf = result.csrf;
      if (Number.isFinite(result.session_minutes)) sessionMinutes = result.session_minutes;
      $("adminPassword").value = "";
      showPanel();
    } catch (err) {
      error.textContent = err.message || "Sign in failed";
      error.hidden = false;
    }
  });

  $("adminLogout").addEventListener("click", async () => {
    try { await api("POST", "/api/admin/logout", {}); } catch (error) { /* ignore */ }
    showLogin();
  });

  document.querySelectorAll("[data-action]").forEach((button) => {
    button.addEventListener("click", () => runAction(button.dataset.action, button));
  });

  $("adminGlow").addEventListener("input", (event) => {
    $("adminGlowValue").textContent = Number(event.target.value).toFixed(2);
  });

  $("adminConfigForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.target;
    const patch = {
      rack_name: form.rack_name.value.trim(),
      rack_builder: form.rack_builder.value.trim(),
      rack_location: form.rack_location.value.trim(),
      collector_name: form.collector_name.value.trim(),
      retention_days: Number(form.retention_days.value),
      session_minutes: Number(form.session_minutes.value),
      battery_reserve_percent: Number(form.battery_reserve_percent.value),
      energy_glow_strength: Number(form.energy_glow_strength.value),
      energy_line_glow: form.energy_line_glow.checked,
      batteries: readBatteryRows(),
    };
    const submit = form.querySelector("button[type=submit]");
    submit.disabled = true;
    try {
      await api("PUT", "/api/admin/config", patch);
      await loadConfig();
      toast("Configuration saved.");
    } catch (error) {
      toast(error.message || "Save failed", "bad");
    } finally {
      submit.disabled = false;
    }
  });

  $("adminPasswordForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.target;
    const submit = form.querySelector("button[type=submit]");
    submit.disabled = true;
    try {
      await api("POST", "/api/admin/password", {
        current_password: form.current_password.value,
        new_password: form.new_password.value,
      });
      form.reset();
      toast("Password updated.");
    } catch (error) {
      toast(error.message || "Password change failed", "bad");
    } finally {
      submit.disabled = false;
    }
  });
}

async function boot() {
  bind();
  try {
    const session = await api("GET", "/api/admin/session");
    if (Number.isFinite(session.session_minutes)) sessionMinutes = session.session_minutes;
    if (session.authenticated) {
      csrf = session.csrf;
      showPanel();
    } else {
      showLogin(!session.configured);
    }
  } catch (error) {
    showLogin();
  }
}

boot();
