const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {pathToFileURL} = require("node:url");
const test = require("node:test");
const vm = require("node:vm");
const staticDir = path.join(__dirname, "../monitor/src/battery_monitor/static");

async function scene() {
  const THREE = await import(pathToFileURL(path.join(staticDir, "vendor/three.module.min.js")).href);
  const source = fs.readFileSync(path.join(staticDir, "energy-flow.js"), "utf8")
    .replace('import * as THREE from "three";', "");
  const context = vm.createContext({THREE});
  vm.runInContext(`${source}\nfunction startEnergyFlowScene() {}`, context);
  return {THREE, run: code => vm.runInContext(code, context)};
}

test("All flow paths are straight, orthogonal, and attached to defined ports", async () => {
  const {run} = await scene();
  const network = run("createFlowNetwork(createMaterials())");
  const ports = run("POWER_PORTS");
  assert.equal(network.routes.length, 6);
  for (const route of network.routes) {
    assert.ok(route.curve.getLength() > 0);
    for (const segment of route.curve.curves) {
      const delta = segment.v2.clone().sub(segment.v1);
      assert.equal([delta.x, delta.y, delta.z].filter(value => Math.abs(value) > 1e-8).length, 1);
    }
  }
  assert.ok(network.grid.curve.getPointAt(1).distanceTo(ports.meter) < 1e-8);
  assert.ok(network.load.curve.getPointAt(0).distanceTo(ports.meter) < 1e-8);
  assert.ok(network.backup.curve.getPointAt(0).distanceTo(ports.inverterBackup) < 1e-8);
  assert.ok(network.battery.curve.getPointAt(1).distanceTo(ports.battery) < 1e-8);
});

test("Every pulse covers the same distance per second on every conduit, at any power", async () => {
  const {run} = await scene();
  const network = run("createFlowNetwork(createMaterials())");
  const rate = run("pulseProgressRate");
  const speed = run("PULSE_SPEED_DEFAULT");
  // The inverter-battery run is far shorter than the Home load run...
  assert.ok(network.load.length > network.battery.length * 10);
  // ...yet a pulse moves the same scene units per second on both, and on every route.
  const expected = speed * run("PULSE_REFERENCE_LENGTH");
  for (const route of network.routes) {
    assert.ok(Math.abs(rate(route, speed) * route.length - expected) < 1e-9);
  }
  // Power no longer affects travel speed.
  const configure = run("configureRoute");
  configure(network.battery, "charging", 1, true, 1, true);
  const lowPower = rate(network.battery, speed);
  configure(network.battery, "charging", 5000, true, 1, true);
  assert.equal(rate(network.battery, speed), lowPower);
});

test("Modern equipment holds three cabinet modules plus a floor-standing unit, with independent load signals", async () => {
  const {THREE, run} = await scene();
  const system = run("createRenogySystem(createMaterials())");
  assert.equal(system.batteryModules.length, 4);
  assert.deepEqual(Array.from(system.batteryModules, (module) => module.kind), ["rack", "rack", "rack", "floor"]);
  // One cabinet slot per rack pack, laid out top to bottom inside the cabinet face.
  const offsets = run("CABINET_MODULE_OFFSETS");
  assert.equal(offsets.length, 3);
  assert.deepEqual([...offsets], [...offsets].sort((a, b) => b - a));
  assert.ok(Math.max(...offsets) + 0.31 / 2 < 1.32 / 2);
  // The floor-standing unit stands on the floor between the cabinet and the meter.
  const floor = run("FLOOR_BATTERY");
  assert.ok(floor.x - floor.width / 2 > 1.63 + 0.92 / 2);
  assert.ok(floor.x + floor.width / 2 < 3.05 - 0.55 / 2);
  assert.ok(Math.abs(system.floorBattery.position.y - floor.height / 2 - floor.lift - floor.floorY) < 1e-9);
  assert.equal(system.floorBattery.visible, true);
  assert.notEqual(system.loadSignalMaterial, system.backupSignalMaterial);
  const bounds = new THREE.Box3().setFromObject(system.group);
  assert.ok(bounds.getSize(new THREE.Vector3()).x < 9);
  assert.ok(Number.isFinite(bounds.max.y));
  assert.equal(run("HOUSE_SCENE_SCALE"), 0.8);
});

test("Rack packs fill the cabinet and the floor-standing pack takes the floor unit", async () => {
  const {run} = await scene();
  const packs = run('normalizePackTelemetry([{id: "rack-1"}, {id: "rack-4", form: "floor"}, {id: "rack-2"}, {id: "rack-3"}, {id: "rack-5"}])');
  assert.deepEqual(Array.from(packs, (pack) => pack.form), ["rack", "floor", "rack", "rack", "rack"]);
  const assign = run("assignPacksToModules");
  const modules = [{kind: "rack"}, {kind: "rack"}, {kind: "rack"}, {kind: "floor"}];
  const assigned = assign(modules, packs);
  assert.deepEqual(Array.from(assigned, (pack) => pack?.id), ["rack-1", "rack-2", "rack-3", "rack-4"]);
  // Without a floor-standing pack the floor unit stays empty rather than taking a rack pack.
  const rackOnly = assign(modules, Array.from(packs).filter((pack) => pack.form === "rack"));
  assert.equal(rackOnly[3], undefined);
  assert.equal(rackOnly[2].id, "rack-3");
  // Unknown forms are rack packs, and an oversized list is capped, never doubled up.
  assert.equal(run('normalizePackTelemetry([{id: "x", form: "tower"}])[0].form'), "rack");
  assert.equal(run("normalizePackTelemetry(new Array(20).fill({id: \"x\"})).length"), run("MAX_SCENE_PACKS"));
});

test("Unmetered service link stays inactive; supported direction reverses with power", async () => {
  const {run} = await scene();
  run("var route = createFlowNetwork(createMaterials()).acLink");
  run('configureRoute(route, "charging", 10, true, 1, false)');
  assert.equal(run("isRouteActive(route)"), false);
  run('configureRoute(route, "discharging", 10, true, -1, true)');
  assert.equal(run("isRouteActive(route)"), true);
  assert.equal(run("route.direction"), -1);
});
