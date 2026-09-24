const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "../monitor/src/battery_monitor/static/app.js"), "utf8",
);

// Just enough DOM for the topbar readout: it writes markup, a title and the
// hidden flag onto one element.
function page(language = "en") {
  const elements = new Map();
  const element = (id) => {
    if (!elements.has(id)) {
      elements.set(id, {
        id, textContent: "", innerHTML: "", title: undefined, hidden: false, dataset: {}, style: {},
        classList: { toggle() {}, add() {}, remove() {} },
        setAttribute() {}, removeAttribute(name) { if (name === "title") this.title = undefined; },
        querySelectorAll: () => [],
      });
    }
    return elements.get(id);
  };
  const context = vm.createContext({
    document: { documentElement: { lang: language }, getElementById: element,
                createElementNS: () => ({ dataset: {}, setAttribute() {} }), addEventListener() {} },
    window: { dispatchEvent() {}, setTimeout() {}, clearTimeout() {} },
    CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options?.detail; } },
  });
  vm.runInContext(`${source}\nfunction bindControls() {}\nfunction refreshCycle() {}`, context);
  vm.runInContext(`state.language = ${JSON.stringify(language)}`, context);
  return { element, run: (code) => vm.runInContext(code, context) };
}

const healthy = {
  cpu_temperature_c: 46.4, cpu_percent: 4.2, memory_percent: 41.0, disk_percent: 12.5,
  load_1m: 0.31, uptime_seconds: 3 * 86400 + 4 * 3600 + 9 * 60, disk_free_gb: 25.6,
  throttled: { raw: "0x0", active: [], occurred: [] },
};

function render(ui, host, status = "online") {
  ui.run(`renderHostStats(${JSON.stringify(host)}, ${JSON.stringify(status)})`);
  return ui.element("collectorHost");
}

test("A healthy Pi reads as one quiet footnote", () => {
  const strip = render(page(), healthy);
  assert.equal(strip.hidden, false);
  for (const text of ["Pi", "46 °C", "CPU 4.2%", "RAM 41%", "SD 13%"]) {
    assert.ok(strip.innerHTML.includes(text), `should show ${text}`);
  }
  // Nothing is coloured: no item carries a heat modifier.
  assert.ok(!strip.innerHTML.includes("connection-host__item--"));
  assert.ok(strip.title.includes("load 0.31"));
  assert.ok(strip.title.includes("up 3d 4h"));
  assert.ok(strip.title.includes("25.6 GB free"));
});

test("Only the temperature changes colour, and only near the throttle point", () => {
  const warm = render(page(), { ...healthy, cpu_temperature_c: 72 });
  assert.ok(warm.innerHTML.includes('connection-host__item connection-host__item--warm">72 °C'));
  assert.ok(!warm.innerHTML.includes("--hot"));
  const hot = render(page(), { ...healthy, cpu_temperature_c: 81 });
  assert.ok(hot.innerHTML.includes('connection-host__item--hot">81 °C'));
  // The other figures stay plain even when the SoC is hot.
  assert.ok(hot.innerHTML.includes('connection-host__item">CPU'));
});

test("Firmware throttle flags are named, in the viewer's language", () => {
  const en = render(page(), { ...healthy, throttled: { raw: "0x50005", active: ["under_voltage", "throttled"], occurred: ["under_voltage", "throttled"] } });
  assert.ok(en.innerHTML.includes('connection-host__item--hot">under-voltage'));
  assert.ok(en.innerHTML.includes('connection-host__item--hot">throttled'));
  assert.ok(en.title.includes("Since boot: under-voltage, throttled"));
  const vi = render(page("vi"), { ...healthy, throttled: { raw: "0x1", active: ["under_voltage"], occurred: [] } });
  assert.ok(vi.innerHTML.includes("thiếu áp"));
  assert.ok(vi.title.startsWith("Máy thu thập"));
});

test("It hides rather than shows stale numbers when the collector is offline or silent", () => {
  const offline = render(page(), healthy, "offline");
  assert.equal(offline.hidden, true);
  assert.equal(offline.innerHTML, "");
  assert.equal(offline.title, undefined);
  assert.equal(render(page(), null).hidden, true);
  assert.equal(render(page(), {}).hidden, true);
  // A host that could read nothing but the clock has nothing to say.
  assert.equal(render(page(), { sampled_at: "2026-09-24T00:00:00Z" }).hidden, true);
});

test("A field the host could not read is left out, not shown as a dash", () => {
  const partial = render(page(), { cpu_percent: 9.5, cpu_temperature_c: null, memory_percent: 40 });
  assert.equal(partial.hidden, false);
  assert.ok(!partial.innerHTML.includes("°C"));
  assert.ok(partial.innerHTML.includes("CPU 9.5%"));
  assert.ok(!partial.innerHTML.includes("--"));
});
