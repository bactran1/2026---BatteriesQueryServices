const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "../monitor/src/battery_monitor/static/app.js"), "utf8",
);

// Enough DOM for the savings panel: the donut builds SVG paths through
// createElementNS and writes its legend and table rows as markup.
function panel() {
  const elements = new Map();
  const element = (id) => {
    if (!elements.has(id)) {
      elements.set(id, {
        id, textContent: "", innerHTML: "", dataset: {}, hidden: false, style: {},
        children: [], classList: { toggle() {}, add() {}, remove() {} },
        setAttribute() {}, removeAttribute() {},
        querySelectorAll: () => [],
        replaceChildren(...nodes) { this.children = nodes; },
      });
    }
    return elements.get(id);
  };
  const context = vm.createContext({
    document: {
      documentElement: { lang: "en" },
      getElementById: element,
      createElementNS: (_ns, tag) => ({
        tag, dataset: {}, attributes: {},
        setAttribute(name, value) { this.attributes[name] = value; },
      }),
      addEventListener() {},
    },
    window: { dispatchEvent() {}, setTimeout() {}, clearTimeout() {} },
    CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options?.detail; } },
  });
  vm.runInContext(`${source}\nfunction bindControls() {}\nfunction refreshCycle() {}`, context);
  return { element, run: (code) => vm.runInContext(code, context) };
}

function savingsPayload({ onGrid = 28.7, offGrid = 52.1, superGrid = 82.6, savings = 39.01 } = {}) {
  const rate = { on_peak: 0.504, off_peak: 0.127, super_off_peak: 0.076 };
  const cost = (kwh, key) => Math.round(kwh * rate[key] * 100) / 100;
  return {
    estimated_savings_usd: savings,
    estimated_grid_cost_usd: cost(onGrid, "on_peak") + cost(offGrid, "off_peak") + cost(superGrid, "super_off_peak"),
    tou: {
      on_peak: { grid_import_kwh: onGrid, solar_generation_kwh: 31.2, rate_usd_per_kwh: rate.on_peak,
                 grid_cost_usd: cost(onGrid, "on_peak"), savings_usd: 15.72 },
      off_peak: { grid_import_kwh: offGrid, solar_generation_kwh: 183.4, rate_usd_per_kwh: rate.off_peak,
                  grid_cost_usd: cost(offGrid, "off_peak"), savings_usd: 23.29 },
      super_off_peak: { grid_import_kwh: superGrid, solar_generation_kwh: 0, rate_usd_per_kwh: rate.super_off_peak,
                        grid_cost_usd: cost(superGrid, "super_off_peak"), savings_usd: 0 },
    },
  };
}

function draw(ui, period = savingsPayload()) {
  ui.run(`renderSavingsTou(${JSON.stringify(period)}, {season: "winter"})`);
  return {
    arcs: ui.element("savingsDonutChart").children,
    legend: ui.element("savingsDonutLegend").innerHTML,
    centre: ui.element("savingsDonutTotal").textContent,
  };
}

test("The donut divides grid cost by period plus the share solar covered", () => {
  const ui = panel();
  const { arcs, legend, centre } = draw(ui);

  // Three periods bought from the grid, plus the solar offset.
  assert.equal(arcs.length, 4);
  assert.deepEqual(arcs.map(a => a.dataset.tou), ["on_peak", "off_peak", "super_off_peak", "solar"]);
  // $14.46 + $6.62 + $6.28 grid, + $39.01 solar.
  assert.equal(centre, "$66.37");
  for (const money of ["$14.46", "$6.62", "$6.28", "$39.01"]) {
    assert.ok(legend.includes(money), `legend should carry ${money}`);
  }
  // Four slices, so each is direct-labelled: identity never rests on colour.
  for (const name of ["On-peak", "Off-peak", "Super off-peak", "Solar offset"]) {
    assert.ok(legend.includes(name), `legend should name ${name}`);
  }
  assert.ok(legend.includes("59%"), "solar's share of the whole");
});

test("Slice sweeps are proportional to dollars and together close the ring", () => {
  const ui = panel();
  const { arcs } = draw(ui);
  const sweep = (arc) => {
    // Recover each arc's angular span from the two outer endpoints it was built from.
    const nums = arc.attributes.d.match(/-?\d+\.\d+/g).map(Number);
    const angle = (x, y) => Math.atan2(y - 100, x - 100) * 180 / Math.PI;
    let span = angle(nums[2], nums[3]) - angle(nums[0], nums[1]);
    return span < 0 ? span + 360 : span;
  };
  const spans = arcs.map(sweep);
  const gap = ui.run("DONUT_GAP_DEGREES");
  // Every sweep plus its two half-gaps, summed, is the whole circle.
  assert.ok(Math.abs(spans.reduce((a, b) => a + b, 0) + gap * arcs.length - 360) < 0.5);
  // On-peak is 21.8% of $66.37, so a little under 80 degrees.
  assert.ok(Math.abs(spans[0] + gap - 360 * 14.46 / 66.37) < 0.5);
  // Solar is the largest share, so the largest arc.
  assert.equal(Math.max(...spans), spans[3]);
});

test("A period with no grid purchase is left out rather than drawn as a sliver", () => {
  const ui = panel();
  const { arcs, legend } = draw(ui, savingsPayload({ superGrid: 0 }));
  assert.equal(arcs.length, 3);
  assert.deepEqual(arcs.map(a => a.dataset.tou), ["on_peak", "off_peak", "solar"]);
  assert.ok(!legend.includes("Super off-peak"));
});

test("With nothing priced yet the donut says so instead of drawing an empty ring", () => {
  const ui = panel();
  const { arcs, legend, centre } = draw(
    ui, savingsPayload({ onGrid: 0, offGrid: 0, superGrid: 0, savings: 0 }),
  );
  assert.equal(arcs.length, 0);
  assert.equal(centre, "--");
  assert.ok(legend.includes("Awaiting priced energy"));
});

test("Arc geometry starts at twelve o'clock and closes back on the inner edge", () => {
  const ui = panel();
  const arc = ui.run("donutArcPath(-90, -90 + 90)");
  // Outer radius 84, inner 56, both centred on (100, 100).
  assert.ok(arc.startsWith("M 100.00 16.00"), arc);
  assert.ok(arc.includes("A 84 84"), "outer edge swept at the outer radius");
  assert.ok(arc.includes("A 56 56"), "inner edge swept back at the inner radius");
  assert.ok(arc.endsWith("Z"), "the slice is closed");
  // A quarter turn is not a long arc; three quarters is.
  assert.ok(ui.run("donutArcPath(0, 90)").includes("0 0 1"));
  assert.ok(ui.run("donutArcPath(0, 270)").includes("0 1 1"));
});

test("The table totals row adds up the periods it is summing", () => {
  const ui = panel();
  draw(ui);
  assert.equal(ui.element("savingsTouTotalGridCost").textContent, "$27.36");
  assert.equal(ui.element("savingsTouTotalValue").textContent, "$39.01");
  assert.equal(ui.element("savingsTouTotalGrid").textContent, "163.4 kWh");
  assert.equal(ui.element("savingsTouTotalSolar").textContent, "214.6 kWh");
});
