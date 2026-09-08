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

test("Modern equipment contains three distinct battery modules and independent load signals", async () => {
  const {THREE, run} = await scene();
  const system = run("createRenogySystem(createMaterials())");
  assert.equal(system.batteryModules.length, 3);
  assert.notEqual(system.loadSignalMaterial, system.backupSignalMaterial);
  const bounds = new THREE.Box3().setFromObject(system.group);
  assert.ok(bounds.getSize(new THREE.Vector3()).x < 9);
  assert.ok(Number.isFinite(bounds.max.y));
  assert.equal(run("HOUSE_SCENE_SCALE"), 0.8);
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
