const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../monitor/src/battery_monitor/static/app.js"), "utf8");

function chart(viewportWidth = 390) {
  const bars = [];
  const areas = [];
  const labels = [];
  const strokes = [];
  const listeners = new Map();
  const frames = new Map();
  let frameId = 0;
  const on = (target, type, callback) => {
    const key = `${target}:${type}`;
    listeners.set(key, [...(listeners.get(key) || []), callback]);
  };
  const ctx = {
    setTransform() {}, clearRect() {}, save() {}, restore() {}, drawImage() {},
    beginPath() {}, closePath() {}, moveTo: (...args) => strokes.push(["move", ...args]),
    lineTo: (...args) => strokes.push(["line", ...args]), stroke() {},
    rect() {}, clip() {}, arc() {}, fill() { areas.push({ color: this.fillStyle, alpha: this.globalAlpha }); }, setLineDash() {},
    fillRect: (...args) => bars.push(args),
    fillText: (...args) => labels.push(args),
  };
  const elements = new Map();
  const element = (id) => {
    if (!elements.has(id)) elements.set(id, {
      style: {}, dataset: {}, classList: { remove() {}, add() {}, toggle() {} }, setAttribute() {},
      addEventListener: (type, callback) => on(id, type, callback),
      contains: (target) => target === element(id) || target?.owner === id,
      focus() {},
      getContext: () => ctx,
      getBoundingClientRect() {
        return { left: 0, top: 0, width: parseFloat(this.style.width) || viewportWidth, height: 310 };
      },
      clientWidth: viewportWidth, offsetWidth: 280, offsetHeight: 210, scrollPosition: 0,
      get scrollLeft() { return this.scrollPosition; },
      set scrollLeft(value) { this.scrollPosition = Math.max(0, Math.min(value, this.scrollWidth - this.clientWidth)); },
      get scrollWidth() { return parseFloat(element("energyHistoryChart").style.width) || viewportWidth; },
    });
    return elements.get(id);
  };
  const context = vm.createContext({
    document: { documentElement: { lang: "en" }, getElementById: element,
      addEventListener: (type, callback) => on("document", type, callback) },
    window: { devicePixelRatio: 3, requestAnimationFrame(callback) { frames.set(++frameId, callback); return frameId; },
      cancelAnimationFrame: (id) => frames.delete(id) },
  });
  vm.runInContext(`${source}\nfunction bindControls() {}\nfunction refreshCycle() {}\nfunction getThemeColors() { return {chartMuted: "#999", chartGrid: "#ddd"}; }`, context);
  return { context, state: vm.runInContext("state", context), element, bars, areas, labels, strokes,
    emit: (target, type, event = {}) => (listeners.get(`${target}:${type}`) || []).forEach(fn => fn(event)),
    flush() { for (const [id, callback] of [...frames]) { if (frames.delete(id)) callback(); } },
    run: (code) => vm.runInContext(code, context) };
}

test("Energy uses translucent overlapping areas and one shared zero-based scale", () => {
  const ui = chart();
  ui.state.energyView = "hour";
  ui.state.energyHistory = [{unix: 0, consumption_kwh: 0.2, solar_generation_kwh: 0.4, grid_import_kwh: 0.1}];
  ui.run("drawEnergyHistoryChart()");
  assert.equal(ui.areas.length, 3);
  assert.ok(ui.areas.every((area) => area.alpha === 0.24));
  assert.equal(ui.element("energyHistoryChart").dataset.chartType, "overlapping-areas");
  const consumption = ui.state.energyChartGeometry.points.find((point) => point.series.field === "consumption_kwh");
  const solar = ui.state.energyChartGeometry.points.find((point) => point.series.field === "solar_generation_kwh");
  assert.equal(solar.y, 26);
  assert.equal(consumption.y, (26 + ui.state.energyChartGeometry.plot.bottom) / 2);
  assert.ok(ui.labels.some(([text]) => text === "0.4"));
  assert.equal(ui.element("energyHistoryChart").width, 780);
});

test("SOC uses a fixed percentage axis without changing the power scale", () => {
  const ui = chart(320);
  ui.state.history = [
    {unix:0, battery_power_w:-2500, battery_soc_percent:0},
    {unix:60, battery_power_w:4500, battery_soc_percent:50},
    {unix:120, battery_power_w:2000, battery_soc_percent:100},
  ];
  ui.run("drawChart()");
  const before = {...ui.state.chartGeometry.powerScale};
  const soc = ui.state.chartGeometry.points.filter(p => p.series.unit === "%");
  assert.equal(soc[0].y, ui.state.chartGeometry.plot.bottom);
  assert.equal(soc[2].y, ui.state.chartGeometry.plot.top);
  assert.equal(soc[1].y, (soc[0].y + soc[2].y) / 2);
  assert.ok(ui.labels.some(([text]) => text === "100%"));
  assert.ok(ui.labels.some(([text]) => text === "0%"));
  assert.equal(ui.element("historyChart").width, 640);
  ui.state.powerSeries.delete("battery_soc_percent");
  ui.run("drawChart()");
  assert.deepEqual({...ui.state.chartGeometry.powerScale}, before);
});

test("SOC-only history, zero, invalid and absent SOC retain their meaning", () => {
  const ui = chart();
  ui.state.powerSeries = new Set(["battery_soc_percent"]);
  ui.state.history = [{unix:0,battery_soc_percent:0}, {unix:60,battery_soc_percent:null},
    {unix:120,battery_soc_percent:130}, {unix:180,battery_soc_percent:72.35}];
  ui.run("drawChart()");
  assert.equal(ui.state.chartGeometry.points.length, 2);
  assert.equal(ui.run('formatPowerHistoryValue(72.35, "battery_soc_percent")'), "72.4%");
  assert.equal(ui.run('formatPowerHistoryValue(0, "battery_soc_percent")'), "0%");
  assert.equal(ui.run('formatPowerHistoryValue(null, "battery_soc_percent")'), "--");
  assert.equal(ui.run('formatPowerHistoryValue(130, "battery_soc_percent")'), "--");
  ui.state.language = "vi";
  assert.equal(ui.run('formatPowerHistoryValue(72.35, "battery_soc_percent")'), "72,4%");
  assert.ok(!ui.labels.some(([text]) => / W$/.test(text)));
});

test("Missing SOC breaks the line instead of drawing a made-up value", () => {
  const ui = chart();
  const series = ui.run('powerHistorySeries.find(s => s.unit === "%")');
  ui.run('drawHistorySeries(document.getElementById("historyChart").getContext("2d"), [{x:0,y:1}, null, {x:2,y:3}], "teal")');
  assert.equal(ui.strokes.filter(([kind]) => kind === "line").length, 0);
  assert.equal(ui.strokes.filter(([kind]) => kind === "move").length, 2);
  assert.equal(series.field, "battery_soc_percent");
});

test("Readouts stay within desktop chart bounds for every anchor", () => {
  const ui = chart(768);
  for (const x of [0, 384, 768]) {
    for (const y of [0, 155, 310]) {
      ui.run(`positionChartReadout($("chartTooltip"), 768, 310, ${x}, ${y})`);
      const tooltip = ui.element("chartTooltip");
      assert.ok(parseFloat(tooltip.style.left) >= 12);
      assert.ok(parseFloat(tooltip.style.left) + tooltip.offsetWidth <= 756);
      assert.ok(parseFloat(tooltip.style.top) >= 12);
      assert.ok(parseFloat(tooltip.style.top) + tooltip.offsetHeight <= 298);
    }
  }
});

function interactiveChart(kind = "power") {
  const ui = chart();
  const energy = kind === "energy";
  ui.id = energy ? "energyHistoryChart" : "historyChart";
  ui.tooltip = energy ? "energyHistoryTooltip" : "chartTooltip";
  if (energy) {
    ui.state.energyView = "hour";
    ui.state.energyHistory = [{unix:0, consumption_kwh:2}];
    ui.run('drawEnergyHistoryChart(); bindChartInspection($("energyHistoryChart"), $("energyHistoryTooltip"), queueEnergyChartHover, hideEnergyChartTooltip, moveEnergyChartKeyboardSelection)');
  } else {
    ui.state.history = [{unix:0, battery_power_w:500, battery_soc_percent:81.5}];
    ui.run('drawChart(); bindChartInspection($("historyChart"), $("chartTooltip"), queueChartHover, hideChartTooltip, moveChartKeyboardSelection)');
  }
  const geometry = energy ? ui.state.energyChartGeometry : ui.state.chartGeometry;
  const point = geometry.points[0];
  ui.touch = {pointerType:"touch", pointerId:1, clientX:point.groupX ?? point.x, clientY:150};
  ui.tap = () => {
    ui.emit(ui.id, "pointerdown", ui.touch);
    ui.emit(ui.id, "pointerup", ui.touch);
    ui.flush();
  };
  return ui;
}

for (const kind of ["power", "energy"]) {
  test(`${kind}: tap opens and a second tap dismisses the readout`, () => {
    const ui = interactiveChart(kind);
    ui.tap();
    assert.equal(ui.element(ui.tooltip).hidden, false);
    if (kind === "power") assert.match(ui.element("chartTooltipContent").innerHTML, /81.5%/);
    ui.tap();
    assert.equal(ui.element(ui.tooltip).hidden, true);
  });
  test(`${kind}: close, outside tap, scrolling and Escape dismiss`, () => {
    const ui = interactiveChart(kind);
    for (const dismiss of [
      () => ui.emit(ui.tooltip, "click", {target:{closest:()=>true}}),
      () => ui.emit("document", "pointerdown", {target:{}}),
      () => ui.emit("document", "scroll", {target:{}}),
      () => ui.emit("document", "keydown", {key:"Escape"}),
      () => ui.emit(ui.id, "pointercancel"),
    ]) {
      ui.tap();
      assert.equal(ui.element(ui.tooltip).hidden, false);
      dismiss();
      ui.flush();
      assert.equal(ui.element(ui.tooltip).hidden, true);
    }
  });
  test(`${kind}: a swipe never opens the readout and canceled animation frames cannot resurrect it`, () => {
    const ui = interactiveChart(kind);
    ui.emit(ui.id, "pointerdown", ui.touch);
    ui.emit(ui.id, "pointermove", {...ui.touch, clientY:190});
    ui.emit(ui.id, "pointerup", {...ui.touch, clientY:190});
    ui.flush();
    assert.equal(ui.element(ui.tooltip).hidden, true);
    ui.emit(ui.id, "pointerdown", ui.touch);
    ui.emit(ui.id, "pointerup", ui.touch);
    ui.emit("document", "pointerdown", {target:{}});
    ui.flush();
    assert.equal(ui.element(ui.tooltip).hidden, true);
  });
}

test("Rolling hour fits twelve five-minute areas in the mobile viewport", () => {
  const ui = chart(320);
  ui.state.energyView = "hour";
  ui.state.energyWindowStart = 0;
  ui.state.energyWindowEnd = 3600;
  ui.state.energyBucketSeconds = 300;
  ui.state.energyHistory = Array.from({length:12}, (_, index) => ({
    unix:index*300, consumption_kwh:1, solar_generation_kwh:2, grid_import_kwh:0,
  }));
  ui.run("drawEnergyHistoryChart()");
  assert.equal(ui.areas.length, 3);
  assert.equal(ui.state.energyChartGeometry.points.length, 36);
  assert.equal(parseFloat(ui.element("energyHistoryChart").style.width), 320);
  assert.equal(ui.element("energyChartScroll").clientWidth, 320);
});

test("Zero energy stays zero and missing energy is not drawn as zero", () => {
  const ui = chart();
  ui.state.energyView = "hour";
  ui.state.energyHistory = [{unix:0, consumption_kwh:0, solar_generation_kwh:null, grid_import_kwh:0.002}];
  ui.run("drawEnergyHistoryChart()");
  assert.equal(ui.areas.length, 2);
  assert.equal(ui.state.energyChartGeometry.points.find((point) => point.value === 0).y,
    ui.state.energyChartGeometry.plot.bottom);
  assert.ok(ui.labels.some(([text]) => text === "0.002"));
  assert.equal(ui.run("formatEnergyTotal(0.002)"), "0.002");
  assert.equal(ui.run("formatEnergyPointValue(1.5678)"), "1.5678 kWh");
});

test("Date areas preserve all hours of normal and daylight-saving days", () => {
  const ui = chart();
  ui.state.energyView = "date";
  for (const hours of [23, 24, 25]) {
    ui.state.energyWindowStart = 0;
    ui.state.energyWindowEnd = hours * 3600;
    assert.equal(ui.run("energyChartSlots([]).length"), hours);
  }
});

for (const viewportWidth of [320, 1440]) {
  test(`Date view fits all 24 hourly points at ${viewportWidth}px without scrolling`, () => {
    const ui = chart(viewportWidth);
    ui.state.energyView = "date";
    ui.state.energyWindowStart = 0;
    ui.state.energyWindowEnd = 24 * 3600;
    ui.state.energyHistory = Array.from({length:24}, (_, index) => ({
      unix:index*3600, consumption_kwh:1, solar_generation_kwh:2, grid_import_kwh:0.5,
    }));
    ui.run("drawEnergyHistoryChart()");
    assert.equal(ui.state.energyChartGeometry.points.length, 72);
    assert.equal(parseFloat(ui.element("energyHistoryChart").style.width), viewportWidth);
    assert.equal(ui.element("energyHistoryChart").scrollWidth, viewportWidth);
  });
}

test("Year view retains an empty slot for a missing month", () => {
  const ui = chart();
  ui.state.energyView = "year";
  ui.state.energyHistory = [
    {unix:Date.UTC(2026,0,15)/1000, consumption_kwh:20},
    {unix:Date.UTC(2026,2,15)/1000, consumption_kwh:30},
  ];
  // Jan, Feb (empty), Mar
  assert.equal(ui.run("energyChartSlots(state.energyHistory).length"), 3);
});

test("Month view retains an empty slot for a missing day", () => {
  const ui = chart();
  ui.state.energyView = "month";
  ui.state.energyHistory = [
    {unix:Date.UTC(2026,8,1)/1000, consumption_kwh:5},
    {unix:Date.UTC(2026,8,4)/1000, consumption_kwh:8},
  ];
  // Sep 1, 2 (empty), 3 (empty), 4
  assert.equal(ui.run("energyChartSlots(state.energyHistory).length"), 4);
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
