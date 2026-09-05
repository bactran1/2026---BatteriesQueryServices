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
  render();
  return { element, events, state, render };
}

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
