const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../monitor/src/battery_monitor/static/app.js"), "utf8");

function chart(viewportWidth = 390) {
  const bars = [];
  const labels = [];
  const ctx = {
    setTransform() {}, clearRect() {}, save() {}, restore() {}, drawImage() {},
    beginPath() {}, moveTo() {}, lineTo() {}, stroke() {},
    fillRect: (...args) => bars.push(args),
    fillText: (...args) => labels.push(args),
  };
  const elements = new Map();
  const element = (id) => {
    if (!elements.has(id)) elements.set(id, {
      style: {}, dataset: {}, classList: { remove() {} }, setAttribute() {},
      getContext: () => ctx,
      getBoundingClientRect() {
        return { width: parseFloat(this.style.width) || viewportWidth, height: 310 };
      },
      clientWidth: viewportWidth, scrollLeft: 0,
      get scrollWidth() { return parseFloat(element("energyHistoryChart").style.width) || viewportWidth; },
    });
    return elements.get(id);
  };
  const context = vm.createContext({
    document: { documentElement: { lang: "en" }, getElementById: element },
    window: { devicePixelRatio: 3 },
  });
  vm.runInContext(`${source}\nfunction bindControls() {}\nfunction refreshCycle() {}\nfunction getThemeColors() { return {chartMuted: "#999", chartGrid: "#ddd"}; }`, context);
  return { context, state: vm.runInContext("state", context), element, bars, labels,
    run: (code) => vm.runInContext(code, context) };
}

test("Energy uses separate bars and one shared zero-based scale", () => {
  const ui = chart();
  ui.state.energyView = "hour";
  ui.state.energyHistory = [{unix: 0, consumption_kwh: 0.2, solar_generation_kwh: 0.4, grid_import_kwh: 0.1}];
  ui.run("drawEnergyHistoryChart()");
  assert.equal(ui.bars.length, 3);
  assert.equal(ui.element("energyHistoryChart").dataset.chartType, "grouped-bars");
  assert.equal(ui.bars[1][3], ui.bars[0][3] * 2);
  assert.equal(ui.bars[1][1], 26);
  assert.ok(ui.labels.some(([text]) => text === "0.4"));
  assert.equal(ui.element("energyHistoryChart").width, 780);
});

test("Dense hourly timelines scroll instead of squeezing bars on mobile", () => {
  const ui = chart(320);
  ui.state.energyView = "hour";
  ui.state.energyHistory = Array.from({length:168}, (_, index) => ({
    unix:index*3600, consumption_kwh:1, solar_generation_kwh:2, grid_import_kwh:0,
  }));
  ui.run("drawEnergyHistoryChart()");
  assert.equal(ui.bars.length, 504);
  assert.ok(ui.bars.every(([, , width]) => width >= 6));
  assert.ok(parseFloat(ui.element("energyHistoryChart").style.width) > 320);
  assert.equal(ui.element("energyChartScroll").clientWidth, 320);
});

test("Zero energy stays zero and missing energy is not drawn as zero", () => {
  const ui = chart();
  ui.state.energyView = "hour";
  ui.state.energyHistory = [{unix:0, consumption_kwh:0, solar_generation_kwh:null, grid_import_kwh:0.002}];
  ui.run("drawEnergyHistoryChart()");
  assert.equal(ui.bars.length, 2);
  assert.equal(ui.bars[0][3], 0);
  assert.ok(ui.labels.some(([text]) => text === "0.002"));
  assert.equal(ui.run("formatEnergyTotal(0.002)"), "0.002");
});

test("Date bars preserve all hours of normal and daylight-saving days", () => {
  const ui = chart();
  ui.state.energyView = "date";
  for (const hours of [23, 24, 25]) {
    ui.state.energyWindowStart = 0;
    ui.state.energyWindowEnd = hours * 3600;
    assert.equal(ui.run("energyChartSlots([]).length"), hours);
  }
});

test("Missing calendar months retain an empty slot", () => {
  const ui = chart();
  ui.state.energyView = "month";
  ui.state.energyHistory = [
    {unix:Date.UTC(2026,0,1)/1000, consumption_kwh:20},
    {unix:Date.UTC(2026,2,1)/1000, consumption_kwh:30},
  ];
  assert.equal(ui.run("energyChartSlots(state.energyHistory).length"), 3);
});

test("Power date axis ends at 24h for both three and five ticks", () => {
  const ui = chart();
  ui.state.range = "date";
  ui.state.powerTimezone = "UTC";
  for (const count of [3,5]) {
    const labels = Array.from({length:count}, (_, index) =>
      ui.run(`powerTimeTick(${index * 86400 / (count - 1)}, ${index / (count - 1)})`));
    assert.equal(labels[0], "0h");
    assert.equal(labels.at(-1), "24h");
    assert.equal(labels[(count - 1) / 2], "12:00");
  }
  const fields = ui.run("selectedPowerHistorySeries().map(series => series.field).join(',')");
  assert.ok(fields.includes("home_load_power_w"));
  assert.ok(fields.includes("load_power_w"));
});
