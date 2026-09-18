const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {pathToFileURL} = require("node:url");
const test = require("node:test");
const vm = require("node:vm");
const staticDir = path.join(__dirname, "../monitor/src/battery_monitor/static");

// Minimal 2D canvas stand-in: the scene paints branding and per-pack LCD textures,
// and three only reads back the canvas at draw time, which never happens here.
function stubCanvas() {
  const context = {
    canvas: {width: 0, height: 0},
    calls: [],
    record(name, args) { this.calls.push([name, ...args]); },
    measureText(text) { return {width: String(text).length * 12}; },
    createRadialGradient() { return {addColorStop() {}}; },
  };
  for (const name of [
    "clearRect", "fillRect", "strokeRect", "fillText", "beginPath", "ellipse", "fill", "stroke",
  ]) {
    context[name] = (...args) => context.record(name, args);
  }
  return {
    getContext() { return context; },
    context,
    set width(value) { context.canvas.width = value; },
    get width() { return context.canvas.width; },
    set height(value) { context.canvas.height = value; },
    get height() { return context.canvas.height; },
  };
}

async function scene() {
  const THREE = await import(pathToFileURL(path.join(staticDir, "vendor/three.module.min.js")).href);
  const source = fs.readFileSync(path.join(staticDir, "rack-flow.js"), "utf8")
    .replace('import * as THREE from "three";', "");
  const canvases = [];
  const context = vm.createContext({
    THREE,
    document: {
      createElement() {
        const canvas = stubCanvas();
        canvases.push(canvas);
        return canvas;
      },
    },
  });
  vm.runInContext(`${source}\nfunction startRackFlowScene() {}`, context);
  return {THREE, canvases, run: code => vm.runInContext(code, context)};
}

test("The rack stack carries one Eco-worthy module per pack and stays centred", async () => {
  const {run} = await scene();
  const pitch = run("MODULE.pitch");
  for (const count of [1, 3, 5, 8]) {
    const layout = run(`rackLayout(${count})`);
    assert.equal(layout.length, count);
    // Top pack first, evenly pitched, and the stack's midpoint sits on the origin.
    for (let index = 1; index < layout.length; index += 1) {
      assert.ok(Math.abs((layout[index - 1] - layout[index]) - pitch) < 1e-9);
    }
    assert.ok(Math.abs(layout.reduce((sum, y) => sum + y, 0)) < 1e-9);
  }
  // Out-of-range pack counts fall back to something renderable.
  assert.equal(run("rackLayout(0)").length, run("DEFAULT_MODULES"));
  assert.equal(run("rackLayout(99)").length, run("MAX_MODULES"));
});

test("Each pack taps the bus riser and every conduit segment is single-axis", async () => {
  const {run} = await scene();
  const layout = run("rackLayout(4)");
  const network = run("createRackNetwork(createRackMaterials(), rackLayout(4))");
  assert.equal(network.taps.length, 4);
  assert.equal(network.routes.length, 5);
  const terminalX = run("TERMINAL_X");
  const busX = run("BUS_X");
  for (const route of network.routes) {
    assert.ok(route.curve.getLength() > 0);
    for (const segment of route.curve.curves) {
      const delta = segment.v2.clone().sub(segment.v1);
      assert.equal([delta.x, delta.y, delta.z].filter(value => Math.abs(value) > 1e-8).length, 1);
    }
  }
  network.taps.forEach((tap, index) => {
    assert.ok(Math.abs(tap.curve.getPointAt(0).x - terminalX) < 1e-8);
    assert.ok(Math.abs(tap.curve.getPointAt(0).y - layout[index]) < 1e-8);
    assert.ok(Math.abs(tap.curve.getPointAt(1).x - busX) < 1e-8);
  });
  // The riser spans the whole stack and the rack output leaves past the top pack.
  assert.ok(network.trunk.curve.getPointAt(0).y < layout[layout.length - 1]);
  assert.ok(network.trunk.curve.getPointAt(1).y > layout[0]);
  assert.ok(network.trunk.curve.getPointAt(1).x > busX);
});

test("A single-pack rack still builds a bus riser with a travellable trunk", async () => {
  const {run} = await scene();
  const network = run("createRackNetwork(createRackMaterials(), rackLayout(1))");
  assert.equal(network.taps.length, 1);
  assert.ok(network.trunk.curve.getLength() > 0.5);
  for (const segment of network.trunk.curve.curves) {
    assert.ok(segment.v1.distanceTo(segment.v2) > 1e-6);
  }
});

test("Pulses move at one constant speed on the taps and on the bus alike", async () => {
  const {run} = await scene();
  const network = run("createRackNetwork(createRackMaterials(), rackLayout(3))");
  const rate = run("pulseProgressRate");
  const speed = run("PULSE_SPEED_DEFAULT");
  const expected = speed * run("PULSE_REFERENCE_LENGTH");
  assert.ok(network.trunk.length > network.taps[0].length * 2);
  for (const route of network.routes) {
    assert.ok(Math.abs(rate(route, speed) * route.length - expected) < 1e-9);
  }
});

test("Charging pulls power from the bus into a pack, discharging pushes it back", async () => {
  const {run} = await scene();
  const network = run("createRackNetwork(createRackMaterials(), rackLayout(2))");
  const configure = run("configureRoute");
  const isActive = run("isRouteActive");
  const [tap] = network.taps;

  // The tap curve runs pack -> bus, so a charging pack must travel it backwards.
  configure(tap, "charging", 1, true, -1, true);
  assert.equal(tap.direction, -1);
  assert.equal(isActive(tap), true);

  configure(tap, "discharging", 1, true, 1, true);
  assert.equal(tap.direction, 1);
  assert.equal(isActive(tap), true);

  // Idle and non-reporting packs park their conduit.
  configure(tap, "idle", 0, true, 1, true);
  assert.equal(isActive(tap), false);
  configure(tap, "discharging", 1, true, 1, false);
  assert.equal(tap.mode, "stale");
  assert.equal(isActive(tap), false);
});

test("A module shows the Eco-worthy hardware details the pack telemetry drives", async () => {
  const {run} = await scene();
  const module = run("createBatteryModule(createRackMaterials(), 0)");
  assert.equal(module.socLedMaterials.length, run("SOC_LEDS"));
  assert.equal(module.terminals.length, 2);
  assert.ok(module.runMaterial !== module.alarmMaterial);
  assert.ok(module.portMaterial !== module.stripeMaterial);
  // Faceplate furniture sits proud of the panel itself so nothing z-fights it.
  const faceFront = run("FACE_FRONT");
  const faceZ = run("FACE_Z");
  const furniture = module.group.children.filter(child => child.position.z > faceZ);
  assert.ok(furniture.length > 30, "the faceplate should carry real hardware detail");
  furniture.forEach(child => assert.ok(child.position.z >= faceFront - 1e-6));
  // Everything behind the panel stays inside the chassis.
  assert.ok(Math.abs(module.face.position.z - faceZ) < 1e-9);
  module.group.children
    .filter(child => child.position.z <= faceZ && child !== module.face)
    .forEach(child => assert.ok(child.position.z <= run("BODY.depth") / 2 + 1e-9));
  // The DC terminal block is where the conduit attaches.
  module.terminals.forEach(post => assert.ok(Math.abs(post.position.x - run("TERMINAL_X")) < 1e-8));
});

test("A pack's LCD repaints only when its readout changes", async () => {
  const {run} = await scene();
  const module = run("createBatteryModule(createRackMaterials(), 0)");
  const draw = run("drawModuleScreen");
  const context = module.screenContext;
  const pack = {soc: 92, voltage: 53.4, current: -6, power: -324};

  draw(module, pack, true, "discharging");
  const painted = context.calls.filter(call => call[0] === "fillText").map(call => call[1]);
  assert.ok(painted.includes("92"));
  assert.ok(painted.includes("%"));
  assert.ok(painted.includes("53.4 V"));
  assert.ok(painted.includes("6.0 A"));
  assert.ok(painted.includes("DISCHARGING"));

  const afterFirst = context.calls.length;
  draw(module, pack, true, "discharging");
  assert.equal(context.calls.length, afterFirst, "unchanged telemetry must not repaint");

  draw(module, pack, false, "stale");
  assert.ok(context.calls.length > afterFirst);
  assert.ok(context.calls.some(call => call[0] === "fillText" && call[1] === "OFFLINE"));
});

test("Pack telemetry from the dashboard is normalised before it reaches the scene", async () => {
  const {run} = await scene();
  const normalize = run("normalizeRackPacks");
  assert.equal(normalize("not json").length, 0);
  assert.equal(normalize(null).length, 0);
  assert.equal(normalize(new Array(20).fill({id: "x"})).length, run("MAX_MODULES"));
  const [pack] = normalize(JSON.stringify([
    {id: "rack-1", mode: "charging", soc: 92, power: 324, current: 6, voltage: 53.4, reporting: true},
  ]));
  assert.deepEqual(JSON.parse(JSON.stringify(pack)), {
    id: "rack-1", mode: "charging", soc: 92, power: 324,
    current: 6, voltage: 53.4, alarm: false, reporting: true,
  });
  // Unknown modes and missing readings degrade to a stale pack with no readout.
  const [unknown] = normalize([{id: "rack-2", mode: "exploding", soc: null}]);
  assert.equal(unknown.mode, "stale");
  assert.equal(unknown.soc, null);
  assert.equal(unknown.reporting, false);
});

test("Rebuilding the stack frees the old geometry but keeps shared materials alive", async () => {
  const {run} = await scene();
  const materials = run("createRackMaterials()");
  const rack = run("buildRack(createRackMaterials(), 3)");
  const dispose = run("disposeObject");
  let geometriesDisposed = 0;
  rack.group.traverse(child => {
    if (!child.geometry) return;
    const original = child.geometry.dispose.bind(child.geometry);
    child.geometry.dispose = () => { geometriesDisposed += 1; original(); };
  });
  let sharedDisposed = 0;
  Object.values(materials).forEach(material => {
    if (!material?.userData?.shared) return;
    material.dispose = () => { sharedDisposed += 1; };
  });
  dispose(rack.group);
  assert.ok(geometriesDisposed > 20);
  assert.equal(sharedDisposed, 0);
});

test("The stage frames the stack and its bus, and grows with the pack count", async () => {
  const {run} = await scene();
  const small = run("buildRack(createRackMaterials(), 2)").bounds;
  const large = run("buildRack(createRackMaterials(), 6)").bounds;
  assert.ok(large.max.y - large.min.y > small.max.y - small.min.y);
  // Both include the faceplate, the bus riser, and the rack output run.
  for (const bounds of [small, large]) {
    assert.ok(bounds.min.x <= -run("MODULE.width") / 2 + 1e-9);
    assert.ok(bounds.max.x >= run("BUS_X") + run("BUS_OUT") - 1e-9);
  }
});
