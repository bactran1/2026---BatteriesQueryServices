const assert = require("node:assert/strict");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const test = require("node:test");

const modulePath = path.join(__dirname, "../monitor/src/battery_monitor/static/home-scene.js");

// The module is an ES module that also self-starts in a browser; under Node
// there is no `document`, so importing it yields only the pure functions.
async function scene() {
  return import(pathToFileURL(modulePath).href);
}

// Kent, WA: where the collector lives.
const LAT = 47.3809;
const LON = -122.2348;

test("The sun position matches the monitor's own NOAA implementation", async () => {
  const { solarPosition } = await scene();
  // Reference values computed with battery_monitor.weather._solar_position.
  const cases = [
    ["2026-06-21T20:00:00Z", 65.96, 173.89],
    ["2026-06-21T08:00:00Z", -19.14, 357.4],
    ["2026-12-21T20:00:00Z", 19.16, 178.26],
    ["2026-09-28T01:30:00Z", 3.57, 263.18],
  ];
  for (const [when, elevation, azimuth] of cases) {
    const position = solarPosition(new Date(when), LAT, LON);
    assert.ok(Math.abs(position.elevation - elevation) < 0.05, `${when} elevation ${position.elevation}`);
    assert.ok(Math.abs(position.azimuth - azimuth) < 0.05, `${when} azimuth ${position.azimuth}`);
  }
});

test("Phase of day follows the sun, and dawn is told from dusk by where the sun is", async () => {
  const { scenePhase } = await scene();
  assert.equal(scenePhase(45, 180), "day");
  assert.equal(scenePhase(12, 120), "day");
  assert.equal(scenePhase(3, 100), "dawn");
  assert.equal(scenePhase(3, 260), "golden");
  assert.equal(scenePhase(-5, 280), "golden");
  assert.equal(scenePhase(-20, 0), "night");
  // No sun data at all reads as day rather than as a dark screen.
  assert.equal(scenePhase(null, null), "day");
});

test("The sky blends between phases and greys with cloud cover, never jumping", async () => {
  const { skyPalette, SKY } = await scene();
  const noon = skyPalette(60, 180, 0);
  assert.equal(noon.phase, "day");
  assert.equal(noon.top, SKY.day.top);
  assert.equal(noon.stars, 0);
  assert.ok(noon.daylight > 0.95);
  assert.equal(noon.lamps, 0);

  const midnight = skyPalette(-40, 0, 0);
  assert.equal(midnight.phase, "night");
  // The render is dark at every hour; the stars are a restrained accent, at
  // their fullest only in the middle of the night.
  assert.equal(midnight.stars, SKY.night.stars);
  assert.ok(midnight.stars > 0 && midnight.stars <= 1);
  assert.equal(midnight.daylight, 0);
  assert.equal(midnight.lamps, 1);

  // Just above civil dusk the night sky still carries some of the sunset.
  const lateDusk = skyPalette(-10, 270, 0);
  assert.equal(lateDusk.phase, "night");
  // The edge of the picture is the page's own black in every phase; the glow
  // around the house is what carries the hour.
  assert.equal(lateDusk.top, SKY.night.top);
  assert.notEqual(lateDusk.low, SKY.night.low);
  assert.ok(lateDusk.stars < midnight.stars && lateDusk.stars > midnight.stars * 0.3);

  // Overcast pulls the colour toward grey and hides the stars.
  const overcastNoon = skyPalette(60, 180, 100);
  assert.notEqual(overcastNoon.top, noon.top);
  assert.ok(overcastNoon.daylight < noon.daylight);
  const overcastNight = skyPalette(-40, 0, 100);
  assert.ok(overcastNight.stars < midnight.stars * 0.2);
});

test("The sun crosses the stage east to west and sits below the horizon at night", async () => {
  const { sunScreenPosition } = await scene();
  const morning = sunScreenPosition(20, 100);
  const noon = sunScreenPosition(60, 180);
  const evening = sunScreenPosition(20, 260);
  assert.ok(morning.x < noon.x && noon.x < evening.x);
  assert.ok(noon.y < morning.y);
  const night = sunScreenPosition(-15, 300);
  assert.ok(night.y > 352, "below the horizon line");
});

test("Conduits carry power only above the meters' noise, in the reported direction", async () => {
  const { flowsFor } = await scene();
  const live = flowsFor({
    mode: "charging", inverterAvailable: true, batteryAvailable: true,
    solarPower: 3200, gridPower: -800, loadPower: 1500, backupPower: 10, batteryPower: 900, soc: 76,
  });
  assert.equal(live.solar.active, true);
  assert.equal(live.grid.active, true);
  assert.equal(live.grid.direction, -1, "export runs toward the pole");
  assert.equal(live.home.active, true);
  assert.equal(live.backup.active, false, "10 W is noise");
  assert.equal(live.battery.active, true);
  assert.equal(live.battery.direction, 1, "charging runs into the cabinet");
  // More power, faster dashes; never faster than the eye can follow.
  assert.ok(live.solar.seconds < live.battery.seconds);
  assert.ok(live.solar.seconds >= 0.9);

  const discharging = flowsFor({ mode: "discharging", inverterAvailable: true, batteryPower: -1200, solarPower: 0, gridPower: 0, loadPower: 1200 });
  assert.equal(discharging.battery.direction, -1);

  // No inverter telemetry: solar, grid and home rest, but the cabinet still shows its own reading.
  const batteryOnly = flowsFor({ mode: "charging", inverterAvailable: false, batteryPower: 600, solarPower: 3000, gridPower: 500, loadPower: 900 });
  assert.equal(batteryOnly.solar.active, false);
  assert.equal(batteryOnly.grid.active, false);
  assert.equal(batteryOnly.battery.active, true);

  // Stale data rests everything, whatever the last numbers were.
  const stale = flowsFor({ mode: "stale", inverterAvailable: true, batteryPower: 900, solarPower: 3000, gridPower: 500, loadPower: 900 });
  assert.ok(Object.values(stale).every((flow) => !flow.active));
});

test("A preview clock takes an ISO time or a time of day", async () => {
  const { parseClockOverride } = await scene();
  assert.equal(parseClockOverride(""), null);
  assert.equal(parseClockOverride("?other=1"), null);
  const iso = parseClockOverride("?sceneClock=2026-09-28T19:30:00");
  assert.ok(iso instanceof Date && !Number.isNaN(iso.getTime()));
  assert.equal(iso.getHours(), 19);
  const clock = parseClockOverride("?sceneClock=06:15");
  assert.equal(clock.getHours(), 6);
  assert.equal(clock.getMinutes(), 15);
  assert.equal(parseClockOverride("?sceneClock=nonsense"), null);
});

test("Colours mix by channel and clamp", async () => {
  const { mixHex } = await scene();
  assert.equal(mixHex("#000000", "#ffffff", 0.5), "#808080");
  assert.equal(mixHex("#ff0000", "#0000ff", 0), "#ff0000");
  assert.equal(mixHex("#ff0000", "#0000ff", 2), "#0000ff");
  assert.equal(mixHex("#fff", "#000", 1), "#000000");
});
