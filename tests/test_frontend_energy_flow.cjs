const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const appPath = path.join(__dirname, "../monitor/src/battery_monitor/static/app.js");
const source = fs.readFileSync(appPath, "utf8");

function dashboard(homeLoad, backupLoad = 0) {
  const elements = new Map();
  const events = [];
  const element = (id) => {
    if (!elements.has(id)) {
      elements.set(id, { textContent: "", dataset: {}, classList: { toggle() {} } });
    }
    return elements.get(id);
  };
  const context = vm.createContext({
    document: { documentElement: { lang: "en" }, getElementById: element },
    window: { dispatchEvent: (event) => events.push(event) },
    CustomEvent: class {
      constructor(type, options) { this.type = type; this.detail = options.detail; }
    },
  });
  // Disable startup polling and control binding while exercising the real renderers.
  vm.runInContext(`${source}\nfunction bindControls() {}\nfunction refreshCycle() {}`, context);
  const state = vm.runInContext("state", context);
  state.collectorOnline = true;
  state.batteries = [{
    id: "rack-1", status: "ok",
    last_reading: { power_w: 324, current_a: 6, voltage_v: 54, soc_percent: 92 },
  }];
  state.inverter = {
    status: "ok",
    last_reading: {
      timestamp: new Date().toISOString(),
      home_load_total_power_w: homeLoad,
      load_total_power_w: backupLoad,
      pv_total_power_w: 3000,
      grid_import_power_w: 0,
      grid_export_power_w: 0,
      battery_power_w: -5000,
      battery_soc_percent: 10,
    },
  };
  const render = () => vm.runInContext(
    'renderEnergyFlow({mode: "charging"}); renderInverterTelemetry();', context,
  );
  const renderWeather = () => vm.runInContext("renderWeather();", context);
  render();
  return { element, events, state, render, renderWeather };
}

test("Current weather is localized without changing its source measurements", () => {
  const ui = dashboard(1500, 450);
  ui.state.weather = {
    status: "ok", temperature_c: 18, apparent_temperature_c: 17,
    relative_humidity_percent: 71, wind_speed_kmh: 8.6,
    weather_code: 61, is_day: true, source: "Open-Meteo", location: "Home",
    solar_irradiance_w_m2: 482.4, direct_normal_irradiance_w_m2: 621.7,
    solar_elevation_degrees: 42.4, solar_azimuth_degrees: 188.2,
  };
  ui.renderWeather();
  assert.equal(ui.element("energyWeatherTemperature").textContent, "64°F");
  assert.equal(ui.element("energyWeatherCondition").textContent, "Rain");
  assert.match(ui.element("energyWeatherDetails").textContent, /Feels 63°F/);
  assert.match(ui.element("energyWeatherDetails").textContent, /Wind 5 mph/);
  assert.equal(ui.element("energyWeatherSolar").textContent,
    "Irradiance 482 W/m² · Sun 42° · 188° S");
  assert.match(ui.element("energyWeatherSolar").title, /DNI 622 W\/m²/);
  assert.equal(ui.element("energyWeather").dataset.kind, "rain");

  ui.state.language = "vi";
  ui.renderWeather();
  assert.equal(ui.element("energyWeatherTemperature").textContent, "18°C");
  assert.equal(ui.element("energyWeatherCondition").textContent, "Có mưa");
  assert.match(ui.element("energyWeatherDetails").textContent, /Gió 9 km\/h/);
  assert.equal(ui.element("energyWeatherSolar").textContent,
    "Bức xạ 482 W/m² · Mặt trời 42° · 188° N");
});

test("Home load label, description, and animation use the CT-side load", () => {
  const ui = dashboard(1500, 0);
  assert.equal(ui.element("energyLoadValue").textContent, "1.50 kW");
  assert.match(ui.element("energyFlowDescription").textContent, /1\.50 kW home load/);
  assert.equal(ui.element("energyFlowSection").dataset.loadPower, "1500");
  assert.equal(ui.element("energyFlowSection").dataset.loadActive, "true");
  assert.equal(ui.events.at(-1).detail.loadPower, 1500);
  assert.equal(ui.element("inverterLoadPower").textContent, "0 W");
  assert.match(ui.element("inverterLoadDetail").textContent, /Home load 1\.50 kW/);
  assert.equal(ui.events.at(-1).detail.batteryPower, 324);
  assert.equal(ui.events.at(-1).detail.soc, 92);
});

test("Home load updates independently of backup load on subsequent readings", () => {
  const ui = dashboard(1500, 450);
  ui.state.inverter.last_reading.home_load_total_power_w = 725;
  ui.render();
  assert.equal(ui.element("energyLoadValue").textContent, "725 W");
  assert.equal(ui.events.at(-1).detail.loadPower, 725);
  assert.equal(ui.element("inverterLoadPower").textContent, "450 W");
});

test("A measured zero Home load stays zero even with backup output", () => {
  const ui = dashboard(0, 2200);
  assert.equal(ui.element("energyLoadValue").textContent, "0 W");
  assert.equal(ui.element("energyFlowSection").dataset.loadActive, "false");
  assert.equal(ui.events.at(-1).detail.loadPower, 0);
  assert.equal(ui.element("inverterLoadPower").textContent, "2.20 kW");
});

test("Missing or invalid Home load never falls back to backup output", () => {
  for (const value of [undefined, null, NaN, Infinity]) {
    const ui = dashboard(value, 2200);
    assert.equal(ui.element("energyLoadValue").textContent, "Not metered");
    assert.equal(ui.element("energyFlowSection").dataset.loadActive, "false");
    assert.equal(ui.events.at(-1).detail.loadPower, null);
    assert.equal(ui.element("inverterLoadPower").textContent, "2.20 kW");
  }
});

test("A disconnected inverter pauses Home load while battery data stays direct", () => {
  const ui = dashboard(1500, 450);
  ui.state.inverter.status = "error";
  ui.render();
  assert.equal(ui.element("energyLoadValue").textContent, "Not metered");
  assert.equal(ui.element("energyFlowSection").dataset.loadActive, "false");
  assert.equal(ui.events.at(-1).detail.inverterAvailable, false);
  assert.equal(ui.events.at(-1).detail.batteryPower, 324);
});

test("Vietnamese Home load uses the same independent measurement", () => {
  const ui = dashboard(1500, 450);
  ui.state.language = "vi";
  ui.render();
  assert.equal(ui.element("energyLoadValue").textContent, "1,50 kW");
  assert.equal(ui.element("inverterLoadPower").textContent, "450 W");
  assert.equal(ui.events.at(-1).detail.loadPower, 1500);
});

test("Backup load has its own live value and animation feed", () => {
  const ui = dashboard(1500, 450);
  assert.equal(ui.element("energyBackupValue").textContent, "450 W");
  assert.equal(ui.events.at(-1).detail.backupPower, 450);
  assert.equal(ui.element("energyFlowSection").dataset.backupActive, "true");
  ui.state.inverter.last_reading.load_total_power_w = null;
  ui.render();
  assert.equal(ui.element("energyBackupValue").textContent, "Not metered");
  assert.equal(ui.element("energyFlowSection").dataset.backupActive, "false");
});

test("CT-side link obeys home and grid balance without using backup or battery readings", () => {
  const ui = dashboard(1500, 4000);
  assert.equal(ui.events.at(-1).detail.acLinkPower, 1500);
  ui.state.inverter.last_reading.grid_import_power_w = 2000;
  ui.render();
  assert.equal(ui.events.at(-1).detail.acLinkPower, -500);
  ui.state.inverter.last_reading.grid_import_power_w = 0;
  ui.state.inverter.last_reading.grid_export_power_w = 1000;
  ui.render();
  assert.equal(ui.events.at(-1).detail.acLinkPower, 2500);
  assert.equal(ui.events.at(-1).detail.acLinkAvailable, true);
  ui.state.inverter.last_reading.grid_export_power_w = null;
  ui.state.inverter.last_reading.grid_import_power_w = null;
  ui.render();
  assert.equal(ui.events.at(-1).detail.acLinkAvailable, false);
  assert.equal(ui.events.at(-1).detail.acLinkPower, null);
});
