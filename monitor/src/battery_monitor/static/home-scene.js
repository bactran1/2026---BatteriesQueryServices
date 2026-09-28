// The Live Home Energy hero: a dark, isometric render of the home, in the
// manner of EcoFlow's PowerInsight panel.
//
// The scene is one inline SVG built here rather than an image, so every part
// of it answers to live data: the ambient light follows the sun's actual
// elevation (from the coordinates the weather feed carries, recomputed each
// minute), the interior lights and the porch lamp come on at dusk, the panels
// take a sheen while they produce, the cabinet shows its charge and its LEDs,
// and energy moves along the conduits in the direction and at the rate the
// meters report. Callouts are dark pills tied to their objects by thin leader
// lines, positioned from the same projected points the drawing uses.
//
// It listens to the `battery-energy-flow` event and the section's `data-*`
// attributes the dashboard already maintains, and to a `battery-weather`
// event for the light, so it has no data path of its own. A `?sceneClock=`
// query parameter (an ISO time, or `HH:MM` for today) previews any hour.

const SCENE_WIDTH = 1000;
const SCENE_HEIGHT = 560;
const HORIZON_Y = 352;
const SVG_NS = "http://www.w3.org/2000/svg";

// The isometric projection. World units: x runs down-right on screen, y runs
// down-left, z is up. One unit is about a metre of house.
const ISO = { ox: 470, oy: 224, u: 38, h: 34 };
function P(x, y, z = 0) {
  return [ISO.ox + (x - y) * ISO.u, ISO.oy + (x + y) * (ISO.u / 2) - z * ISO.h];
}
function pts(...points) {
  return points.map(([x, y, z]) => P(x, y, z).map((v) => v.toFixed(1)).join(",")).join(" ");
}

// Where each source and sink lives, in world units, and the screen point the
// callouts' leader lines end on.
const NODES = {
  solar: { x: 2.95, y: 5.6, z: 4.4 },
  home: { x: 2.5, y: 8.05, z: 2.35 },
  inverter: { x: 5.05, y: 2.6, z: 1.7 },
  battery: { x: 5.0, y: 4.05, z: 0.8 },
  grid: { x: -1.0, y: 8.7, z: 4.85 },
  backup: { x: 7.55, y: -1.6, z: 1.15 },
};

// Flow colours, softened for the dark render: solar amber, grid teal, battery
// green, home warm white, backup rose. The pills' dots carry the same hues.
const FLOW_COLORS = {
  solar: "#ffb84a",
  grid: "#37c8d6",
  battery: "#3ddc84",
  load: "#ffd89a",
  backup: "#ff8fb1",
  idle: "rgba(255, 255, 255, 0.18)",
};

// Above this many watts a path is considered carrying power; below it the
// meters are within their own noise and the path rests.
const ACTIVE_WATTS = 25;
// A path's dash speed: one full cycle per this many seconds at 1 kW, faster
// with power, clamped so a trickle still visibly moves and a surge never blurs.
const DASH_SECONDS_AT_1KW = 2.6;
const DASH_SECONDS_MIN = 0.9;
const DASH_SECONDS_MAX = 7;
const PULSE_SPEED_DEFAULT = 0.2;

// Ambient light by phase of day. The render is dark at every hour, as the
// panel it follows is; the phases differ in how much light falls on the
// house, how warm it is, and whether the rooms are lit. `sky` is the faint
// ground glow around the house, blended toward the page's black.
const SKY = {
  night: { top: "#0b0c0f", mid: "#0d0e12", low: "#111318", grey: "#0b0c0f", ink: "#f2f4f8", stars: 0.5, ground: ["#1a1d23", "#111317"], warm: 0.1 },
  dawn: { top: "#0b0c0f", mid: "#121016", low: "#1b151a", grey: "#0f0f13", ink: "#f8f4f2", stars: 0.15, ground: ["#221f26", "#141317"], warm: 0.55 },
  golden: { top: "#0b0c0f", mid: "#151110", low: "#211815", grey: "#100f11", ink: "#fff6ee", stars: 0.05, ground: ["#262019", "#161312"], warm: 0.85 },
  day: { top: "#0b0c0f", mid: "#121419", low: "#1a1d24", grey: "#101216", ink: "#f5f7fb", stars: 0, ground: ["#2a2f38", "#181b20"], warm: 0.15 },
};

// ---------------------------------------------------------------------------
// Pure geometry and colour, shared with the tests.
// ---------------------------------------------------------------------------

// Geometric sun elevation and clockwise azimuth from true north, NOAA's
// low-precision algorithm; accurate to well under a degree, which is far
// finer than the scene can show.
function solarPosition(date, latitude, longitude) {
  const julianDay = date.getTime() / 86400000 + 2440587.5;
  const century = (julianDay - 2451545) / 36525;
  const meanLongitude = (280.46646 + century * (36000.76983 + century * 0.0003032)) % 360;
  const meanAnomaly = 357.52911 + century * (35999.05029 - 0.0001537 * century);
  const eccentricity = 0.016708634 - century * (0.000042037 + 0.0000001267 * century);
  const anomaly = toRadians(meanAnomaly);
  const centre = Math.sin(anomaly) * (1.914602 - century * (0.004817 + 0.000014 * century))
    + Math.sin(2 * anomaly) * (0.019993 - 0.000101 * century)
    + Math.sin(3 * anomaly) * 0.000289;
  const trueLongitude = meanLongitude + centre;
  const omega = 125.04 - 1934.136 * century;
  const apparentLongitude = trueLongitude - 0.00569 - 0.00478 * Math.sin(toRadians(omega));
  const meanObliquity = 23 + (26 + (21.448 - century * (46.815 + century * (0.00059 - century * 0.001813))) / 60) / 60;
  const obliquity = meanObliquity + 0.00256 * Math.cos(toRadians(omega));
  const declination = Math.asin(Math.sin(toRadians(obliquity)) * Math.sin(toRadians(apparentLongitude)));
  const y = Math.tan(toRadians(obliquity / 2)) ** 2;
  const equationOfTime = 4 * toDegrees(
    y * Math.sin(2 * toRadians(meanLongitude))
    - 2 * eccentricity * Math.sin(anomaly)
    + 4 * eccentricity * y * Math.sin(anomaly) * Math.cos(2 * toRadians(meanLongitude))
    - 0.5 * y * y * Math.sin(4 * toRadians(meanLongitude))
    - 1.25 * eccentricity * eccentricity * Math.sin(2 * anomaly),
  );
  const minutesUtc = date.getUTCHours() * 60 + date.getUTCMinutes() + date.getUTCSeconds() / 60;
  const trueSolarMinutes = (minutesUtc + equationOfTime + 4 * longitude + 1440) % 1440;
  const hourAngle = trueSolarMinutes / 4 < 0 ? trueSolarMinutes / 4 + 180 : trueSolarMinutes / 4 - 180;
  const lat = toRadians(latitude);
  const ha = toRadians(hourAngle);
  const zenith = Math.acos(clamp(
    Math.sin(lat) * Math.sin(declination) + Math.cos(lat) * Math.cos(declination) * Math.cos(ha),
    -1, 1,
  ));
  const elevation = 90 - toDegrees(zenith);
  let azimuth = toDegrees(Math.acos(clamp(
    (Math.sin(lat) * Math.cos(zenith) - Math.sin(declination)) / (Math.cos(lat) * Math.sin(zenith) || 1e-9),
    -1, 1,
  )));
  azimuth = hourAngle > 0 ? (azimuth + 180) % 360 : (540 - azimuth) % 360;
  return { elevation, azimuth };
}

// When there is no location, a plain clock: up at six, down at six, the arc
// of a temperate spring. Better than a scene frozen at noon.
function clockSolarPosition(date) {
  const hour = date.getHours() + date.getMinutes() / 60;
  const elevation = 55 * Math.sin(Math.PI * (hour - 6) / 12);
  const azimuth = 90 + ((hour - 6) / 12) * 180;
  return { elevation, azimuth };
}

// Night below civil dusk, a coloured sky either side of the horizon, day once
// the sun is well up. Whether the coloured sky is dawn or golden hour depends
// on which way the sun is going, which the azimuth tells: east of south it is
// rising.
function scenePhase(elevation, azimuth) {
  if (elevation === null || !Number.isFinite(elevation)) return "day";
  if (elevation < -8) return "night";
  if (elevation < 10) {
    const az = ((azimuth ?? 180) % 360 + 360) % 360;
    return az < 180 ? "dawn" : "golden";
  }
  return "day";
}

// The palette for a phase, greyed by cloud cover and, near a phase boundary,
// blended with its neighbour so the sky never jumps.
function skyPalette(elevation, azimuth, cloudCover) {
  const phase = scenePhase(elevation, azimuth);
  const base = SKY[phase];
  let next = null;
  let blend = 0;
  const el = elevation === null || !Number.isFinite(elevation) ? 45 : elevation;
  if (phase === "night" && el > -14) { next = SKY[scenePhase(-7, azimuth)]; blend = (el + 14) / 6; }
  else if ((phase === "dawn" || phase === "golden") && el < -4) { next = SKY.night; blend = (-4 - el) / 4; }
  else if ((phase === "dawn" || phase === "golden") && el > 5) { next = SKY.day; blend = (el - 5) / 5; }
  else if (phase === "day" && el < 16) { next = SKY[scenePhase(5, azimuth)]; blend = (16 - el) / 6; }
  blend = clamp(blend, 0, 1);

  const cover = clamp((cloudCover ?? 0) / 100, 0, 1);
  const grey = 0.55 * cover;
  const pick = (key) => {
    const colour = next ? mixHex(base[key], next[key], blend) : base[key];
    const greyTone = next ? mixHex(base.grey, next.grey, blend) : base.grey;
    return mixHex(colour, greyTone, grey);
  };
  const number = (key) => (next ? base[key] * (1 - blend) + next[key] * blend : base[key]);
  return {
    phase,
    top: pick("top"),
    mid: pick("mid"),
    low: pick("low"),
    ink: next ? mixHex(base.ink, next.ink, blend) : base.ink,
    groundTop: mixHex(next ? mixHex(base.ground[0], next.ground[0], blend) : base.ground[0], base.grey, grey * 0.5),
    groundLow: mixHex(next ? mixHex(base.ground[1], next.ground[1], blend) : base.ground[1], base.grey, grey * 0.5),
    stars: number("stars") * (1 - cover * 0.85),
    warm: number("warm"),
    // How much daylight falls on the house: none at night, full by mid-morning,
    // and still a warm two-thirds with the sun on the horizon.
    daylight: clamp((el + 10) / 22, 0, 1) * (1 - cover * 0.35),
    // The rooms and the porch lamp come on as the light goes, well before dark.
    lamps: clamp((6 - el) / 9, 0, 1),
  };
}

// Where the sun sits on the stage for a given elevation and azimuth: east on
// the left, west on the right, the horizon at HORIZON_Y.
function sunScreenPosition(elevation, azimuth) {
  const az = ((azimuth ?? 180) % 360 + 360) % 360;
  const across = clamp((az - 70) / (290 - 70), 0, 1);
  const x = 90 + across * (SCENE_WIDTH - 180);
  const lift = elevation === null || !Number.isFinite(elevation)
    ? 0.6
    : elevation >= 0
      ? Math.min(1, elevation / 55)
      : Math.max(-0.12, elevation / 90);
  const y = HORIZON_Y - lift * (HORIZON_Y - 130);
  return { x, y };
}

// Which conduits carry power, which way, and how fast, from the section's
// numbers. Sign conventions follow the dashboard: grid positive is import,
// battery positive is charging.
function flowsFor(input) {
  const inverter = Boolean(input.inverterAvailable);
  const solar = number(input.solarPower);
  const grid = number(input.gridPower);
  const load = number(input.loadPower);
  const backup = number(input.backupPower);
  const battery = number(input.batteryPower);
  const batteryKnown = input.batteryAvailable !== false && battery !== null;
  const stale = input.mode === "stale";

  const flow = (key, watts, color, forward) => {
    const magnitude = Math.abs(watts ?? 0);
    const active = !stale && magnitude >= ACTIVE_WATTS;
    return {
      key,
      color,
      active,
      watts: magnitude,
      direction: forward ? 1 : -1,
      seconds: active
        ? clamp(DASH_SECONDS_AT_1KW / Math.max(magnitude / 1000, 0.05), DASH_SECONDS_MIN, DASH_SECONDS_MAX)
        : DASH_SECONDS_MAX,
    };
  };

  return {
    solar: flow("solar", inverter ? solar : 0, FLOW_COLORS.solar, true),
    grid: flow("grid", inverter ? grid : 0, FLOW_COLORS.grid, (grid ?? 0) >= 0),
    home: flow("home", inverter ? load : 0, FLOW_COLORS.load, true),
    backup: flow("backup", inverter ? backup : 0, FLOW_COLORS.backup, true),
    battery: flow("battery", batteryKnown ? battery : 0, FLOW_COLORS.battery, (battery ?? 0) >= 0),
  };
}

// ---------------------------------------------------------------------------
// The scene.
// ---------------------------------------------------------------------------

function startHomeScene() {
  const section = document.getElementById("energyFlowSection");
  const stage = document.getElementById("homeScene");
  if (!section || !stage) return;

  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const svg = buildScene();
  stage.replaceChildren(svg);
  stage.dataset.sceneStyle = "illustrated-home";
  stage.dataset.topology = "home-grid-solar-inverter-battery-load";

  const parts = {
    stars: svg.querySelector("#hsStars"),
    panels: Array.from(svg.querySelectorAll(".hs-panel-glint")),
    windows: Array.from(svg.querySelectorAll(".hs-window")),
    lamp: svg.querySelector("#hsLamp"),
    lampGlow: svg.querySelector("#hsLampGlow"),
    socFill: svg.querySelector("#hsSocFill"),
    leds: Array.from(svg.querySelectorAll(".hs-led")),
    inverterScreen: svg.querySelector("#hsInverterScreen"),
    flows: {},
    shadow: svg.querySelector("#hsShadow"),
  };
  for (const key of ["solar", "grid", "home", "backup", "battery"]) {
    parts.flows[key] = {
      track: svg.querySelector(`#hsFlow-${key}-track`),
      dash: svg.querySelector(`#hsFlow-${key}-dash`),
      dots: Array.from(svg.querySelectorAll(`.hs-flow-dot[data-flow="${key}"]`)),
    };
  }

  const state = {
    weather: null,
    latitude: null,
    longitude: null,
    cloudCover: 0,
    precipitation: 0,
    clockOverride: parseClockOverride(window.location?.search),
    pulseSpeed: PULSE_SPEED_DEFAULT,
    glow: 1,
    lineGlow: true,
    palette: null,
    visible: true,
  };

  placeCallouts(section);
  applyFlows(readFlowInput(section));
  applyLighting();
  fitStage();
  keepCalloutsInView(section);
  if ("ResizeObserver" in window) {
    new ResizeObserver(fitStage).observe(stage.parentElement || stage);
  } else {
    window.addEventListener("resize", fitStage);
  }

  window.addEventListener("battery-energy-flow", (event) => {
    applyFlows(readFlowInput(section, event.detail));
    keepCalloutsInView(section);
  });
  window.addEventListener("battery-weather", (event) => {
    const weather = event.detail && typeof event.detail === "object" ? event.detail : {};
    state.weather = weather;
    state.latitude = number(weather.latitude);
    state.longitude = number(weather.longitude);
    state.cloudCover = number(weather.cloud_cover_percent) ?? 0;
    state.precipitation = number(weather.precipitation_mm) ?? 0;
    applyLighting();
  });
  window.addEventListener("energy-pulse-speed-change", (event) => {
    const speed = Number(event.detail);
    if (Number.isFinite(speed) && speed > 0) {
      state.pulseSpeed = speed;
      section.style.setProperty("--hs-speed", String(PULSE_SPEED_DEFAULT / speed));
    }
  });
  window.addEventListener("energy-glow-change", (event) => {
    const glow = Number(event.detail);
    if (Number.isFinite(glow)) section.style.setProperty("--hs-glow", String(clamp(glow, 0, 3)));
  });
  window.addEventListener("energy-line-glow-change", (event) => {
    section.dataset.lineGlow = String(Boolean(event.detail));
  });
  window.addEventListener("energy-active-opacity-change", (event) => {
    const opacity = Number(event.detail);
    if (Number.isFinite(opacity)) section.style.setProperty("--hs-active-opacity", String(clamp(opacity, 0.2, 1)));
  });

  // The sun moves about a quarter of a degree a minute; once a minute is more
  // than the eye can tell. The observer stops even that while the section is
  // scrolled away, and the CSS animations pause with it.
  const tick = window.setInterval(() => { if (state.visible) applyLighting(); }, 60000);
  if ("IntersectionObserver" in window) {
    const observer = new IntersectionObserver((entries) => {
      state.visible = entries.some((entry) => entry.isIntersecting);
      section.classList.toggle("is-offscreen", !state.visible);
      if (state.visible) applyLighting();
    }, { threshold: 0.05 });
    observer.observe(section);
  }
  window.addEventListener("pagehide", () => window.clearInterval(tick), { once: true });

  function fitStage() {
    const host = stage.parentElement || stage;
    const width = host.clientWidth;
    const height = host.clientHeight;
    if (!width || !height) return;
    // The largest 1000x560 box that fits, centred on the stage. A narrow
    // screen may ask (through --hs-zoom) for a closer view: the box then
    // outgrows the stage's width and the edges of the picture crop, with
    // --hs-focus naming the point of the scene to keep in the middle.
    const style = getComputedStyle(section);
    const zoom = Math.max(1, Number.parseFloat(style.getPropertyValue("--hs-zoom")) || 1);
    const focus = clamp(Number.parseFloat(style.getPropertyValue("--hs-focus")) || 0.5, 0, 1);
    const scale = Math.min(width * zoom / SCENE_WIDTH, height / SCENE_HEIGHT);
    const boxWidth = SCENE_WIDTH * scale;
    const boxHeight = SCENE_HEIGHT * scale;
    const left = boxWidth <= width ? (width - boxWidth) / 2 : clamp(width / 2 - focus * boxWidth, width - boxWidth, 0);
    section.style.setProperty("--hs-box-width", `${boxWidth.toFixed(1)}px`);
    section.style.setProperty("--hs-box-height", `${boxHeight.toFixed(1)}px`);
    section.style.setProperty("--hs-box-left", `${left.toFixed(1)}px`);
    section.style.setProperty("--hs-box-top", `${((height - boxHeight) / 2).toFixed(1)}px`);
    section.style.setProperty("--hs-scale", scale.toFixed(4));
    keepCalloutsInView(section);
  }

  function applyFlows(input) {
    const flows = flowsFor(input);
    let activeRoutes = 0;
    for (const [key, flow] of Object.entries(flows)) {
      const part = parts.flows[key];
      if (!part?.track) continue;
      activeRoutes += flow.active ? 1 : 0;
      part.track.dataset.active = String(flow.active);
      part.dash.dataset.active = String(flow.active);
      part.dash.style.setProperty("--hs-flow-seconds", `${flow.seconds}s`);
      part.dash.style.animationDirection = flow.direction > 0 ? "normal" : "reverse";
      part.dash.setAttribute("stroke", flow.active ? flow.color : FLOW_COLORS.idle);
      part.track.setAttribute("stroke", flow.active ? flow.color : FLOW_COLORS.idle);
      for (const dot of part.dots) {
        dot.dataset.active = String(flow.active);
        dot.setAttribute("fill", flow.color);
        const motion = dot.querySelector("animateMotion");
        if (motion) {
          motion.setAttribute("dur", `${flow.seconds * 1.8}s`);
          motion.setAttribute("keyPoints", flow.direction > 0 ? "0;1" : "1;0");
        }
      }
    }
    stage.dataset.activeRoutes = String(activeRoutes);
    stage.dataset.sourceTelemetry = input.inverterAvailable ? "inverter-and-direct-battery" : "direct-battery-only";

    // The cabinet: state of charge as the gauge's fill, LEDs by what it does.
    const soc = clamp(number(input.soc) ?? 0, 0, 100);
    if (parts.socFill) {
      const top = parts.socFill.dataset.top.split(",").map(Number);
      const bottom = parts.socFill.dataset.bottom.split(",").map(Number);
      parts.socFill.setAttribute("x2", String(bottom[0] + (top[0] - bottom[0]) * soc / 100));
      parts.socFill.setAttribute("y2", String(bottom[1] + (top[1] - bottom[1]) * soc / 100));
      parts.socFill.setAttribute("stroke", soc < 20 ? FLOW_COLORS.backup : FLOW_COLORS.battery);
    }
    const ledColour = input.mode === "charging" ? FLOW_COLORS.battery
      : input.mode === "discharging" ? FLOW_COLORS.solar
        : input.mode === "stale" ? "#6b7280" : "#9fb3c8";
    for (const led of parts.leds) led.setAttribute("fill", ledColour);
    if (parts.inverterScreen) {
      parts.inverterScreen.setAttribute("fill", input.inverterAvailable ? "#7fd0ff" : "#334155");
    }
    section.dataset.sceneMode = input.mode || "stale";
    section.dataset.solarActive = String(flows.solar.active);
  }

  function applyLighting() {
    const now = state.clockOverride ?? new Date();
    const position = state.latitude !== null && state.longitude !== null
      ? solarPosition(now, state.latitude, state.longitude)
      : state.weather && number(state.weather.solar_elevation_degrees) !== null && !state.clockOverride
        ? { elevation: number(state.weather.solar_elevation_degrees), azimuth: number(state.weather.solar_azimuth_degrees) ?? 180 }
        : clockSolarPosition(now);
    const palette = skyPalette(position.elevation, position.azimuth, state.cloudCover);
    state.palette = palette;

    section.dataset.phase = palette.phase;
    section.style.setProperty("--hs-sky-top", palette.top);
    section.style.setProperty("--hs-sky-mid", palette.mid);
    section.style.setProperty("--hs-sky-low", palette.low);
    section.style.setProperty("--hs-ink", palette.ink);
    section.style.setProperty("--hs-ground-top", palette.groundTop);
    section.style.setProperty("--hs-ground-low", palette.groundLow);
    section.style.setProperty("--hs-daylight", palette.daylight.toFixed(3));
    section.style.setProperty("--hs-lamps", palette.lamps.toFixed(3));
    section.style.setProperty("--hs-warm", palette.warm.toFixed(3));
    section.style.setProperty("--hs-stars", palette.stars.toFixed(3));
    section.dataset.raining = String(state.precipitation > 0.05);

    // The light itself: no sun disc in a render like this, only where it falls.
    // Light on the panels: the sun's height and the sky's clarity, and only
    // while the array is producing, so a bright but disconnected roof does
    // not pretend.
    const producing = section.dataset.solarActive === "true";
    const glint = producing ? clamp(palette.daylight * 0.55, 0, 0.55) : palette.daylight * 0.15;
    section.style.setProperty("--hs-glint", glint.toFixed(3));
    const az = ((position.azimuth ?? 180) % 360 + 360) % 360;
    section.style.setProperty("--hs-light-side", clamp((az - 180) / 90, -1, 1).toFixed(2));
  }

  return { applyFlows, applyLighting, state };
}

// A pill's width is its text's, not the picture's, so on a narrow stage one
// near the edge can run past it; such a pill slides back inside, its leader
// still reaching it from under its body.
function keepCalloutsInView(section) {
  const bounds = section.getBoundingClientRect();
  if (!bounds.width) return;
  for (const pill of section.querySelectorAll(".energy-flow__callout")) {
    if (getComputedStyle(pill).position !== "absolute") continue;
    pill.style.setProperty("--hs-pill-shift", "0px");
    const rect = pill.getBoundingClientRect();
    const overflowRight = rect.right - (bounds.right - 8);
    const overflowLeft = (bounds.left + 8) - rect.left;
    const shift = overflowRight > 0 ? -overflowRight : overflowLeft > 0 ? overflowLeft : 0;
    if (shift) pill.style.setProperty("--hs-pill-shift", `${shift.toFixed(1)}px`);
  }
}

function placeCallouts(section) {
  for (const [key, callout] of Object.entries(CALLOUTS)) {
    const pill = section.querySelector(`.energy-flow__callout--${key}`);
    if (!pill) continue;
    const [px, py] = calloutPoints(callout).pill;
    pill.style.setProperty("--hs-pill-x", `${(px / SCENE_WIDTH * 100).toFixed(2)}%`);
    pill.style.setProperty("--hs-pill-y", `${(py / SCENE_HEIGHT * 100).toFixed(2)}%`);
    pill.dataset.side = callout.side;
  }
}

function readFlowInput(section, detail = null) {
  const data = section.dataset;
  return {
    mode: detail?.mode ?? data.mode ?? "stale",
    soc: detail?.soc ?? data.soc,
    batteryPower: detail?.power ?? data.batteryPower,
    batteryAvailable: detail ? detail.mode !== "stale" : data.mode !== "stale",
    inverterAvailable: (detail?.inverterAvailable ?? data.inverterAvailable) === true
      || String(detail?.inverterAvailable ?? data.inverterAvailable) === "true",
    solarPower: detail?.solarPower ?? data.solarPower,
    gridPower: detail?.gridPower ?? data.gridPower,
    loadPower: detail?.loadPower ?? data.loadPower,
    backupPower: detail?.backupPower ?? data.backupPower,
  };
}

function parseClockOverride(search) {
  if (!search) return null;
  const params = new URLSearchParams(search);
  const value = params.get("sceneClock");
  if (!value) return null;
  if (/^\d{1,2}:\d{2}$/.test(value)) {
    const [hours, minutes] = value.split(":").map(Number);
    const date = new Date();
    date.setHours(hours, minutes, 0, 0);
    return date;
  }
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

// ---------------------------------------------------------------------------
// Drawing. Plain SVG, built once; everything that moves is moved by
// attributes, CSS variables and CSS animations, so the frame loop is only the
// once-a-minute sun.
// ---------------------------------------------------------------------------

function buildScene() {
  const svg = el("svg", {
    viewBox: `0 0 ${SCENE_WIDTH} ${SCENE_HEIGHT}`,
    preserveAspectRatio: "xMidYMid meet",
    class: "hs",
    "aria-hidden": "true",
    focusable: "false",
  });
  svg.append(defs());
  // The glow around the house; beyond it the section's own black shows.
  svg.append(el("rect", { class: "hs-sky", x: -160, y: -120, width: SCENE_WIDTH + 320, height: SCENE_HEIGHT + 240, fill: "url(#hsSky)" }));
  svg.append(stars());
  // The ground: a pool of faint light the house sits in, fading to the page.
  const [gx, gy] = P(3.2, 2.6, 0);
  svg.append(el("ellipse", { class: "hs-ground", cx: gx, cy: gy, rx: 640, ry: 215, fill: "url(#hsGround)" }));
  const [sx, sy] = P(6.2, 3.8, 0);
  svg.append(el("ellipse", { id: "hsShadow", class: "hs-shadow", cx: sx, cy: sy, rx: 330, ry: 52, fill: "url(#hsShadowGlow)" }));
  svg.append(trees());
  svg.append(utilityPole());
  svg.append(el("ellipse", { id: "hsLampGlow", class: "hs-lamp-glow", cx: P(5.9, 6.0, 0)[0], cy: P(5.9, 6.0, 0)[1] + 4, rx: 130, ry: 38, fill: "url(#hsLampGlow)" }));
  svg.append(annex());
  svg.append(house());
  svg.append(car());
  svg.append(inverterBox());
  svg.append(batteryCabinet());
  svg.append(flows());
  svg.append(leaders());
  svg.append(rain());
  return svg;
}

function defs() {
  const d = el("defs");
  const sky = el("radialGradient", { id: "hsSky", cx: "50%", cy: "55%", r: "50%" });
  sky.append(el("stop", { offset: "0", style: "stop-color: var(--hs-sky-low, #111318)" }));
  sky.append(el("stop", { offset: "0.55", style: "stop-color: var(--hs-sky-mid, #0d0e12)" }));
  sky.append(el("stop", { offset: "1", style: "stop-color: var(--hs-sky-top, #0b0c0f); stop-opacity: 0" }));
  d.append(sky);
  const ground = el("radialGradient", { id: "hsGround", cx: "50%", cy: "50%", r: "50%" });
  ground.append(el("stop", { offset: "0", style: "stop-color: var(--hs-ground-top, #23272e)" }));
  ground.append(el("stop", { offset: "0.5", style: "stop-color: var(--hs-ground-low, #15181c); stop-opacity: 0.7" }));
  ground.append(el("stop", { offset: "1", style: "stop-color: var(--hs-ground-low, #15181c); stop-opacity: 0" }));
  d.append(ground);
  d.append(gradient("hsShadowGlow", [["0", "rgba(0, 0, 0, 0.55)"], ["1", "rgba(0, 0, 0, 0)"]], false, undefined, true));
  d.append(gradient("hsWallFront", [["0", "#2b2f36"], ["1", "#1c1f25"]], true));
  d.append(gradient("hsWallSide", [["0", "#1a1d22"], ["1", "#111317"]], true));
  d.append(gradient("hsRoof", [["0", "#1b1e24"], ["1", "#0c0e11"]], true));
  d.append(gradient("hsRoofAnnex", [["0", "#22262d"], ["1", "#15181d"]], true));
  d.append(gradient("hsWood", [["0", "#5b3f27"], ["0.55", "#4a3220"], ["1", "#2e1f14"]], true));
  d.append(gradient("hsPanel", [["0", "#16213b"], ["0.5", "#1a2a4d"], ["1", "#0f1729"]], true));
  d.append(gradient("hsGlass", [["0", "#f6cf8c"], ["0.45", "#e9a556"], ["1", "#9a4f1e"]], true));
  d.append(gradient("hsGlassDay", [["0", "#3a4352"], ["1", "#1f252e"]], true));
  d.append(gradient("hsCabinet", [["0", "#2a2e35"], ["1", "#111317"]], false));
  d.append(gradient("hsModule", [["0", "#33383f"], ["1", "#1a1d22"]], true));
  d.append(gradient("hsLampGlow", [["0", "rgba(255, 190, 110, 0.32)"], ["1", "rgba(255, 190, 110, 0)"]], false, undefined, true));
  d.append(gradient("hsWindowGlow", [["0", "rgba(255, 196, 120, 0.55)"], ["1", "rgba(255, 196, 120, 0)"]], false, undefined, true));
  const glow = el("filter", { id: "hsGlow", x: "-40%", y: "-40%", width: "180%", height: "180%" });
  glow.append(el("feGaussianBlur", { stdDeviation: "2.6", result: "blur" }));
  const merge = el("feMerge");
  merge.append(el("feMergeNode", { in: "blur" }), el("feMergeNode", { in: "SourceGraphic" }));
  glow.append(merge);
  d.append(glow);
  const soft = el("filter", { id: "hsSoft", x: "-30%", y: "-30%", width: "160%", height: "160%" });
  soft.append(el("feGaussianBlur", { stdDeviation: "9" }));
  d.append(soft);
  return d;
}

function gradient(id, stops, vertical, opacity, radial = false) {
  const g = radial
    ? el("radialGradient", { id, cx: "50%", cy: "50%", r: "50%" })
    : el("linearGradient", { id, x1: "0", y1: "0", x2: vertical ? "0" : "1", y2: vertical ? "1" : "0" });
  for (const [offset, colour] of stops) {
    g.append(el("stop", { offset, style: `stop-color: ${colour}${opacity ? `; stop-opacity: ${opacity}` : ""}` }));
  }
  return g;
}

function stars() {
  const g = el("g", { id: "hsStars", class: "hs-stars" });
  let seed = 7;
  const random = () => { seed = (seed * 9301 + 49297) % 233280; return seed / 233280; };
  for (let index = 0; index < 48; index += 1) {
    const x = 20 + random() * (SCENE_WIDTH - 40);
    const y = 10 + random() * 150;
    const r = 0.5 + random() * 1.1;
    g.append(el("circle", { cx: x.toFixed(1), cy: y.toFixed(1), r: r.toFixed(2), fill: "#ffffff", class: "hs-star", style: `--hs-twinkle-delay: ${(random() * 6).toFixed(2)}s; --hs-twinkle-dur: ${(2.5 + random() * 3).toFixed(2)}s` }));
  }
  return g;
}

function trees() {
  const g = el("g", { class: "hs-trees hs-lit" });
  const tree = (x, y, s) => {
    const [sx, sy] = P(x, y, 0);
    const t = el("g", { transform: `translate(${sx.toFixed(1)} ${sy.toFixed(1)}) scale(${s})` });
    t.append(el("rect", { x: -4, y: -14, width: 8, height: 30, rx: 2, fill: "#191512" }));
    t.append(el("ellipse", { cx: 0, cy: -46, rx: 34, ry: 42, fill: "#0c130f" }));
    t.append(el("ellipse", { cx: -15, cy: -30, rx: 25, ry: 25, fill: "#0f1a14" }));
    t.append(el("ellipse", { cx: 15, cy: -27, rx: 23, ry: 23, fill: "#0e1711" }));
    t.append(el("ellipse", { cx: 4, cy: -58, rx: 18, ry: 18, fill: "#111d15" }));
    return t;
  };
  g.append(tree(-1.6, 1.2, 1.25), tree(-3.2, 4.2, 1.05), tree(0.6, -5.4, 1.3), tree(3.8, -6.6, 1.1), tree(6.4, -7.2, 0.9));
  return g;
}

// The utility pole, far left, with its wires off to the edge and to the house.
function utilityPole() {
  const g = el("g", { class: "hs-pole hs-lit" });
  const { x, y } = NODES.grid;
  const base = P(x, y, 0);
  const top = P(x, y, 5.2);
  g.append(el("line", { x1: base[0], y1: base[1], x2: top[0], y2: top[1], stroke: "#2a2622", "stroke-width": 7, "stroke-linecap": "round" }));
  const arm = P(x, y, 4.85);
  g.append(el("line", { x1: arm[0] - 30, y1: arm[1], x2: arm[0] + 30, y2: arm[1], stroke: "#25211d", "stroke-width": 5, "stroke-linecap": "round" }));
  for (const dx of [-24, -8, 8, 24]) g.append(el("rect", { x: arm[0] + dx - 2, y: arm[1] - 8, width: 4, height: 7, rx: 1.5, fill: "#6b7280" }));
  // Wires to the ridge and to the gable's eave, with a little sag.
  const ridge = P(HOUSE.RIDGE_X, HOUSE.Y1 - 0.2, HOUSE.RIDGE_Z);
  const eave = P(HOUSE.X1 + 0.3, HOUSE.Y1 + 0.1, HOUSE.EAVE);
  for (const [dx, end] of [[-20, ridge], [22, eave]]) {
    const from = [arm[0] + dx, arm[1] - 6];
    const mid = [(from[0] + end[0]) / 2, Math.max(from[1], end[1]) + 22];
    g.append(el("path", { d: `M ${from[0]} ${from[1]} Q ${mid[0]} ${mid[1]} ${end[0]} ${end[1]}`, stroke: "#3a3d44", "stroke-width": 1.4, fill: "none", opacity: 0.9 }));
  }
  // Lines off to the edge of the world.
  g.append(el("path", { d: `M ${arm[0] - 28} ${arm[1] - 6} C ${arm[0] - 120} ${arm[1] + 4}, ${arm[0] - 220} ${arm[1] - 30}, -200 ${arm[1] - 50}`, stroke: "#33363d", "stroke-width": 1.4, fill: "none", opacity: 0.85 }));
  g.append(el("path", { d: `M ${arm[0] + 30} ${arm[1] - 6} C ${arm[0] - 80} ${arm[1] + 14}, ${arm[0] - 200} ${arm[1] - 16}, -200 ${arm[1] - 30}`, stroke: "#33363d", "stroke-width": 1.2, fill: "none", opacity: 0.7 }));
  return g;
}

// The main house: a long gabled block, its ridge along y, so the glazed
// gable end faces the viewer's left and the long clad wall, with the door,
// the cabinet and the inverter, faces the viewer's right under the array.
const HOUSE = { X0: 0, X1: 5, Y0: 0, Y1: 8, EAVE: 3.0, RIDGE_X: 2.4, RIDGE_Z: 4.75 };

function house() {
  const root = el("g", { class: "hs-house" });
  const body = el("g", { class: "hs-house-body hs-lit" });
  const lights = el("g", { class: "hs-house-lights" });
  root.append(body, lights);
  const { X0, X1, Y0, Y1, EAVE, RIDGE_X, RIDGE_Z } = HOUSE;

  // The gable end (y = Y1) and the long wall (x = X1).
  body.append(el("polygon", { points: pts([X0, Y1, 0], [X1, Y1, 0], [X1, Y1, EAVE], [RIDGE_X, Y1, RIDGE_Z], [X0, Y1, EAVE]), fill: "url(#hsWallSide)" }));
  body.append(el("polygon", { points: pts([X1, Y0, 0], [X1, Y1, 0], [X1, Y1, EAVE], [X1, Y0, EAVE]), fill: "url(#hsWood)" }));
  // Vertical boards on the long wall.
  for (let y = Y0 + 0.25; y < Y1; y += 0.25) {
    body.append(el("line", { x1: P(X1, y, 0)[0], y1: P(X1, y, 0)[1], x2: P(X1, y, EAVE - 0.02)[0], y2: P(X1, y, EAVE - 0.02)[1], stroke: "rgba(0,0,0,0.26)", "stroke-width": 0.7 }));
  }
  // Roof slope over the long wall, with its overhang, and the fascia.
  const OV = 0.32;
  body.append(el("polygon", { class: "hs-roof", points: pts([X1 + OV, Y0 - OV, EAVE - 0.05], [X1 + OV, Y1 + OV, EAVE - 0.05], [RIDGE_X, Y1 + OV, RIDGE_Z], [RIDGE_X, Y0 - OV, RIDGE_Z]), fill: "url(#hsRoof)" }));
  body.append(el("polygon", { points: pts([X1 + OV, Y0 - OV, EAVE - 0.05], [X1 + OV, Y1 + OV, EAVE - 0.05], [X1 + OV, Y1 + OV, EAVE - 0.28], [X1 + OV, Y0 - OV, EAVE - 0.28]), fill: "#0c0d10" }));
  // The gable's edge of the roof: a thin dark band over the pentagon.
  body.append(el("polygon", { points: pts([X0 - OV, Y1 + OV, EAVE - 0.05], [RIDGE_X, Y1 + OV, RIDGE_Z], [X1 + OV, Y1 + OV, EAVE - 0.05], [X1 + OV, Y1 + OV, EAVE - 0.28], [RIDGE_X, Y1 + OV, RIDGE_Z - 0.23], [X0 - OV, Y1 + OV, EAVE - 0.28]), fill: "#0d0f12" }));

  // Glazing on the gable end: a two-storey glass wall, the wooden rooms
  // behind it, and a window in the gable.
  const glass = (points, key) => {
    body.append(el("polygon", { class: "hs-window-glass", points, fill: "url(#hsGlassDay)" }));
    lights.append(el("polygon", { class: "hs-window", points, fill: "url(#hsGlass)", "data-window": key }));
  };
  const G0 = 0.35, G1 = 4.65, GZ0 = 0.22, GZ1 = 2.85;
  glass(pts([G0, Y1, GZ0], [G1, Y1, GZ0], [G1, Y1, GZ1], [G0, Y1, GZ1]), "gable");
  // The rooms: a floor slab, a wooden back wall, a stair of shelves.
  lights.append(el("polygon", { class: "hs-interior", points: pts([G0, Y1, 1.5], [G1, Y1, 1.5], [G1, Y1, 1.62], [G0, Y1, 1.62]), fill: "#4a2a14", opacity: 0.85 }));
  lights.append(el("polygon", { class: "hs-interior", points: pts([G0 + 0.3, Y1, GZ0], [G0 + 0.9, Y1, GZ0], [G0 + 0.9, Y1, 1.5], [G0 + 0.3, Y1, 1.5]), fill: "#8a5a2c", opacity: 0.45 }));
  lights.append(el("polygon", { class: "hs-interior", points: pts([G1 - 1.4, Y1, 1.62], [G1 - 0.4, Y1, 1.62], [G1 - 0.4, Y1, 2.5], [G1 - 1.4, Y1, 2.5]), fill: "#8a5a2c", opacity: 0.4 }));
  lights.append(el("polygon", { class: "hs-interior", points: pts([G0 + 1.3, Y1, GZ0 + 0.3], [G0 + 2.4, Y1, GZ0 + 0.3], [G0 + 2.4, Y1, GZ0 + 0.55], [G0 + 1.3, Y1, GZ0 + 0.55]), fill: "#3a2314", opacity: 0.8 }));
  // Mullions.
  for (const x of [1.42, 2.5, 3.58]) {
    lights.append(el("line", { class: "hs-mullion", x1: P(x, Y1, GZ0)[0], y1: P(x, Y1, GZ0)[1], x2: P(x, Y1, GZ1)[0], y2: P(x, Y1, GZ1)[1], stroke: "#0b0c0f", "stroke-width": 2.2 }));
  }
  lights.append(el("line", { class: "hs-mullion", x1: P(G0, Y1, 1.56)[0], y1: P(G0, Y1, 1.56)[1], x2: P(G1, Y1, 1.56)[0], y2: P(G1, Y1, 1.56)[1], stroke: "#0b0c0f", "stroke-width": 2.6 }));
  glass(pts([1.5, Y1, 3.2], [3.3, Y1, 3.2], [3.3, Y1, 3.95], [1.5, Y1, 3.95]), "gable-loft");

  // A window and the door on the long wall, and the porch lamp by the door.
  glass(pts([X1, 6.5, 1.2], [X1, 7.4, 1.2], [X1, 7.4, 2.4], [X1, 6.5, 2.4]), "side");
  body.append(el("polygon", { points: pts([X1, 5.35, 0], [X1, 6.15, 0], [X1, 6.15, 2.2], [X1, 5.35, 2.2]), fill: "#2a1c11" }));
  body.append(el("polygon", { points: pts([X1, 5.42, 0.05], [X1, 6.08, 0.05], [X1, 6.08, 2.13], [X1, 5.42, 2.13]), fill: "#3d2917" }));
  const lamp = P(X1 + 0.02, 6.3, 2.4);
  body.append(el("rect", { x: lamp[0] - 3, y: lamp[1] - 4, width: 6, height: 5, rx: 1, fill: "#2f333a" }));
  lights.append(el("circle", { id: "hsLamp", class: "hs-lamp", cx: lamp[0], cy: lamp[1] + 3, r: 3, fill: "#ffd98a" }));
  lights.append(el("circle", { class: "hs-lamp-halo", cx: lamp[0], cy: lamp[1] + 6, r: 26, fill: "url(#hsWindowGlow)" }));

  // The array: three rows up the slope, eight across, edge to edge.
  const array = el("g", { class: "hs-array" });
  const slope = (y, s) => [X1 + OV - s * (X1 + OV - RIDGE_X), y, EAVE - 0.05 + s * (RIDGE_Z - EAVE + 0.05)];
  for (let row = 0; row < 3; row += 1) {
    for (let col = 0; col < 8; col += 1) {
      const y0 = Y0 + 0.1 + col * 1.0, y1 = y0 + 0.92;
      const s0 = 0.1 + row * 0.29, s1 = s0 + 0.26;
      const points = pts(slope(y0, s0), slope(y1, s0), slope(y1, s1), slope(y0, s1));
      array.append(el("polygon", { points, fill: "url(#hsPanel)", stroke: "#0a0f1c", "stroke-width": 0.9 }));
      array.append(el("polygon", { class: "hs-panel-glint", points, fill: "#7fa3e6", style: `--hs-glint-delay: ${((row * 8 + col) * 0.22).toFixed(2)}s` }));
      const mid = pts(slope(y0, (s0 + s1) / 2), slope(y1, (s0 + s1) / 2));
      array.append(el("polyline", { points: mid, stroke: "rgba(120, 150, 210, 0.18)", "stroke-width": 0.6, fill: "none" }));
    }
  }
  body.append(array);
  return root;
}

// The annex: a lower flat-roofed block at the far end, forward of the long
// wall, with the garage door facing the drive.
const ANNEX = { X0: 5, X1: 7.5, Y0: -3.5, Y1: 0, Z: 2.35 };

function annex() {
  const g = el("g", { class: "hs-annex hs-lit" });
  const { X0, X1, Y0, Y1, Z } = ANNEX;
  g.append(el("polygon", { points: pts([X0, Y1, 0], [X1, Y1, 0], [X1, Y1, Z], [X0, Y1, Z]), fill: "url(#hsWallSide)" }));
  g.append(el("polygon", { points: pts([X1, Y0, 0], [X1, Y1, 0], [X1, Y1, Z], [X1, Y0, Z]), fill: "url(#hsWood)" }));
  g.append(el("polygon", { points: pts([X0, Y0, Z], [X1, Y0, Z], [X1, Y1, Z], [X0, Y1, Z]), fill: "url(#hsRoofAnnex)" }));
  g.append(el("polygon", { points: pts([X1 + 0.15, Y0 - 0.15, Z], [X1 + 0.15, Y1 + 0.1, Z], [X1 + 0.15, Y1 + 0.1, Z - 0.16], [X1 + 0.15, Y0 - 0.15, Z - 0.16]), fill: "#0d0f12" }));
  g.append(el("polygon", { points: pts([X0 - 0.1, Y1 + 0.1, Z], [X1 + 0.15, Y1 + 0.1, Z], [X1 + 0.15, Y1 + 0.1, Z - 0.16], [X0 - 0.1, Y1 + 0.1, Z - 0.16]), fill: "#0b0c0f" }));
  for (let y = Y0 + 0.25; y < Y1; y += 0.25) {
    g.append(el("line", { x1: P(X1, y, 0)[0], y1: P(X1, y, 0)[1], x2: P(X1, y, Z - 0.16)[0], y2: P(X1, y, Z - 0.16)[1], stroke: "rgba(0,0,0,0.26)", "stroke-width": 0.7 }));
  }
  // The garage door.
  g.append(el("polygon", { points: pts([X1, Y0 + 0.5, 0], [X1, Y0 + 2.6, 0], [X1, Y0 + 2.6, 1.9], [X1, Y0 + 0.5, 1.9]), fill: "#2b2f36" }));
  for (let z = 0.35; z < 1.9; z += 0.38) {
    g.append(el("line", { x1: P(X1, Y0 + 0.5, z)[0], y1: P(X1, Y0 + 0.5, z)[1], x2: P(X1, Y0 + 2.6, z)[0], y2: P(X1, Y0 + 2.6, z)[1], stroke: "rgba(0,0,0,0.35)", "stroke-width": 0.9 }));
  }
  return g;
}

// A Tesla Model Y (the Juniper refresh) on the drive, nose to the garage's
// far end: a low-poly build from its side profile, so the fastback roof,
// the glass roof, the full-width tail light bar and the wheel arches read.
function car() {
  const root = el("g", { class: "hs-car" });
  const g = el("g", { class: "hs-car-body hs-lit" });
  // The tail light bar is its own light, so it stays lit after dark.
  const lights = el("g", { class: "hs-car-lights" });
  root.append(g, lights);
  const X0 = 8.3, X1 = 9.02, Y0 = -3.05;
  const y = (offset) => Y0 + offset;
  // Side profile, nose to tail: (length along the car, height).
  const profile = [
    [0.0, 0.10], [0.0, 0.29], [0.05, 0.35], [0.5, 0.41], [0.8, 0.61],
    [0.98, 0.635], [1.56, 0.5], [1.68, 0.46], [1.75, 0.41], [1.75, 0.10],
  ];
  const side = (points, attributes) => g.append(el("polygon", { points: pts(...points.map(([l, z]) => [X1, y(l), z])), ...attributes }));
  const top = (l0, z0, l1, z1, inset, attributes) => g.append(el("polygon", {
    points: pts([X0 + inset, y(l0), z0], [X1 - inset, y(l0), z0], [X1 - inset, y(l1), z1], [X0 + inset, y(l1), z1]), ...attributes,
  }));

  // Body side, its skirt, and the wheel arches cut into it.
  side(profile, { fill: "#a8261d" });
  side([[0.0, 0.10], [1.75, 0.10], [1.75, 0.17], [0.0, 0.17]], { fill: "#6f1712" });
  for (const wheel of [0.4, 1.36]) {
    const [ax, ay] = P(X1 + 0.01, y(wheel), 0.19);
    g.append(el("ellipse", { cx: ax, cy: ay, rx: 8.6, ry: 5.6, fill: "#7a1a13" }));
  }
  // Side glass and the pillars, then the door seam and the mirror.
  side([[0.56, 0.425], [0.8, 0.595], [0.98, 0.615], [1.54, 0.49], [1.56, 0.44]], { fill: "#1b2430" });
  // The shoulder crease along the belt line.
  g.append(el("polyline", { points: pts([X1 + 0.005, y(0.5), 0.415], [X1 + 0.005, y(1.68), 0.462]), stroke: "rgba(255,255,255,0.22)", "stroke-width": 0.9, fill: "none" }));
  const pillar = (l0, z0, l1, z1) => g.append(el("line", { x1: P(X1, y(l0), z0)[0], y1: P(X1, y(l0), z0)[1], x2: P(X1, y(l1), z1)[0], y2: P(X1, y(l1), z1)[1], stroke: "#a8261d", "stroke-width": 1.3 }));
  pillar(1.02, 0.44, 1.04, 0.612);
  g.append(el("line", { x1: P(X1, y(1.05), 0.17)[0], y1: P(X1, y(1.05), 0.17)[1], x2: P(X1, y(1.05), 0.42)[0], y2: P(X1, y(1.05), 0.42)[1], stroke: "rgba(0,0,0,0.35)", "stroke-width": 0.8 }));
  const mirror = P(X1 + 0.02, y(0.6), 0.47);
  g.append(el("rect", { x: mirror[0] - 1, y: mirror[1] - 2, width: 4, height: 3, rx: 1, fill: "#7a1a13" }));

  // Rear: the body, the darker bumper, the light bar across its width.
  const rear = (z0, z1, inset, attributes, target = g) => target.append(el("polygon", {
    points: pts([X0 + inset, y(1.75), z0], [X1 - inset, y(1.75), z0], [X1 - inset, y(1.75), z1], [X0 + inset, y(1.75), z1]), ...attributes,
  }));
  rear(0.10, 0.41, 0, { fill: "#8f1d16" });
  rear(0.10, 0.2, 0, { fill: "#24272d" });
  rear(0.31, 0.365, 0.03, { fill: "#ff4d3f", filter: "url(#hsGlow)" }, lights);
  rear(0.33, 0.345, 0.05, { fill: "#ffd0c8", opacity: 0.8 }, lights);
  rear(0.22, 0.29, 0.26, { fill: "#d9dde3", opacity: 0.8 });

  // Top: hood, the glass house set in from the shoulders, trunk and lip.
  top(0.05, 0.35, 0.5, 0.41, 0, { fill: "#d63a2e" });
  top(0.5, 0.41, 1.68, 0.46, 0, { fill: "#c9352a" });
  top(0.5, 0.41, 0.8, 0.61, 0.06, { fill: "#22303f" });
  top(0.8, 0.61, 0.98, 0.635, 0.06, { fill: "#141a23" });
  top(0.98, 0.635, 1.56, 0.5, 0.06, { fill: "#1d2835" });
  top(1.68, 0.46, 1.75, 0.41, 0, { fill: "#b52d23" });

  // Wheels: tyre and rim.
  for (const wheel of [0.4, 1.36]) {
    const [ax, ay] = P(X1 + 0.02, y(wheel), 0.13);
    g.append(el("ellipse", { cx: ax, cy: ay, rx: 7.2, ry: 4.7, fill: "#0b0c0f" }));
    g.append(el("ellipse", { cx: ax + 0.4, cy: ay - 0.2, rx: 3.6, ry: 2.3, fill: "#585d66" }));
    g.append(el("ellipse", { cx: ax + 0.4, cy: ay - 0.2, rx: 1.2, ry: 0.8, fill: "#22252b" }));
  }
  return root;
}

function inverterBox() {
  const g = el("g", { class: "hs-inverter hs-lit" });
  const { x, y, z } = NODES.inverter;
  g.append(el("polygon", { points: pts([x, y - 0.34, z - 0.5], [x, y + 0.34, z - 0.5], [x, y + 0.34, z + 0.5], [x, y - 0.34, z + 0.5]), fill: "#d5d8de", stroke: "#8b9098", "stroke-width": 0.8 }));
  g.append(el("polygon", { id: "hsInverterScreen", class: "hs-inverter-screen", points: pts([x, y - 0.26, z + 0.08], [x, y + 0.26, z + 0.08], [x, y + 0.26, z + 0.38], [x, y - 0.26, z + 0.38]), fill: "#7fd0ff" }));
  for (const dz of [-0.1, -0.22, -0.34]) {
    g.append(el("line", { x1: P(x, y - 0.22, z + dz)[0], y1: P(x, y - 0.22, z + dz)[1], x2: P(x, y + 0.22, z + dz)[0], y2: P(x, y + 0.22, z + dz)[1], stroke: "#8b9098", "stroke-width": 1.2 }));
  }
  return g;
}

// The cabinet: three modules stacked against the long wall, the charge
// gauge on its side, an LED per module.
function batteryCabinet() {
  const g = el("g", { class: "hs-cabinet hs-lit" });
  const { x, y } = NODES.battery;
  const X0 = x - 0.5, X1 = x + 0.05, Y0 = y - 0.6, Y1 = y + 0.6, H = 1.55;
  g.append(el("polygon", { points: pts([X0, Y1, 0], [X1, Y1, 0], [X1, Y1, H], [X0, Y1, H]), fill: "#0f1114" }));
  g.append(el("polygon", { points: pts([X1, Y0, 0], [X1, Y1, 0], [X1, Y1, H], [X1, Y0, H]), fill: "url(#hsCabinet)" }));
  g.append(el("polygon", { points: pts([X0, Y0, H], [X1, Y0, H], [X1, Y1, H], [X0, Y1, H]), fill: "#2a2e35" }));
  for (let index = 0; index < 3; index += 1) {
    const z0 = 0.12 + index * 0.47, z1 = z0 + 0.4;
    g.append(el("polygon", { points: pts([X1 + 0.01, Y0 + 0.08, z0], [X1 + 0.01, Y1 - 0.08, z0], [X1 + 0.01, Y1 - 0.08, z1], [X1 + 0.01, Y0 + 0.08, z1]), fill: "url(#hsModule)", stroke: "#0b0c0f", "stroke-width": 0.8 }));
    g.append(el("polygon", { points: pts([X1 + 0.02, Y0 + 0.18, z0 + 0.12], [X1 + 0.02, Y0 + 0.7, z0 + 0.12], [X1 + 0.02, Y0 + 0.7, z0 + 0.28], [X1 + 0.02, Y0 + 0.18, z0 + 0.28]), fill: "#0b0c0f" }));
    const led = P(X1 + 0.02, Y1 - 0.2, z0 + 0.2);
    g.append(el("circle", { class: "hs-led", cx: led[0], cy: led[1], r: 2.4, fill: "#9fb3c8" }));
  }
  // Charge gauge on the left face.
  const gaugeTop = P(X0 + 0.12, Y1 + 0.01, 1.35), gaugeBottom = P(X0 + 0.12, Y1 + 0.01, 0.2);
  g.append(el("line", { x1: gaugeTop[0], y1: gaugeTop[1], x2: gaugeBottom[0], y2: gaugeBottom[1], stroke: "rgba(255,255,255,0.14)", "stroke-width": 5, "stroke-linecap": "round" }));
  g.append(el("line", { id: "hsSocFill", x1: gaugeBottom[0], y1: gaugeBottom[1], x2: gaugeBottom[0], y2: gaugeBottom[1], stroke: FLOW_COLORS.battery, "stroke-width": 3.4, "stroke-linecap": "round", "data-top": `${gaugeTop[0]},${gaugeTop[1]}`, "data-bottom": `${gaugeBottom[0]},${gaugeBottom[1]}` }));
  return g;
}

// The conduits: straight iso runs, along the ground and along the walls, the
// way the panel draws them. A faint track always shows the topology; a dashed
// overlay moves with power; two dots ride each path so direction is plain.
// Each path is drawn in its "forward" direction: solar into the inverter,
// grid import from the pole to the inverter, the inverter out to the home and
// the backup circuit, and the inverter into the cabinet, so a charging
// battery fills and a discharging one (reverse) empties.
function route(...points) {
  return points.map((point, index) => `${index ? "L" : "M"} ${P(...point).map((v) => v.toFixed(1)).join(" ")}`).join(" ");
}
const WALL = HOUSE.X1 + 0.06;
const ROUTES = {
  solar: route([WALL, 2.6, 2.95], [WALL, 2.6, 2.2]),
  battery: route([WALL, 2.6, 1.2], [WALL, 2.6, 0.55], [WALL, 3.45, 0.55]),
  home: route([WALL, 2.6, 1.5], [WALL, 7.5, 1.5], [WALL, 7.5, 2.3]),
  backup: route([WALL, 2.6, 1.0], [WALL, 0.06, 1.0], [ANNEX.X1 - 0.1, 0.06, 1.0], [ANNEX.X1 + 0.06, -0.3, 1.0]),
  grid: route([NODES.grid.x, NODES.grid.y, 0.02], [HOUSE.X1 + 0.5, NODES.grid.y, 0.02], [HOUSE.X1 + 0.5, 2.6, 0.02], [WALL, 2.6, 0.02], [WALL, 2.6, 1.2]),
};

function flows() {
  const g = el("g", { class: "hs-flows" });
  for (const [key, d] of Object.entries(ROUTES)) {
    g.append(el("path", { id: `hsFlow-${key}-track`, class: "hs-flow-track", d, fill: "none", stroke: FLOW_COLORS.idle, "stroke-width": 2.4, "stroke-linecap": "round", "stroke-linejoin": "round", "data-active": "false" }));
    g.append(el("path", { id: `hsFlow-${key}-dash`, class: "hs-flow-dash", d, fill: "none", stroke: FLOW_COLORS.idle, "stroke-width": 1.8, "stroke-linecap": "round", "stroke-linejoin": "round", "data-active": "false" }));
    for (let index = 0; index < 2; index += 1) {
      const dot = el("circle", { class: "hs-flow-dot", r: 2.6, fill: FLOW_COLORS.idle, "data-flow": key, "data-active": "false", filter: "url(#hsGlow)" });
      const motion = el("animateMotion", { dur: "4s", repeatCount: "indefinite", begin: `${index * 2}s`, keyPoints: "0;1", keyTimes: "0;1", calcMode: "linear" });
      motion.append(el("mpath", { href: `#hsFlow-${key}-track` }));
      dot.append(motion);
      g.append(dot);
    }
  }
  return g;
}

// Where each callout pill sits: its leader line ends on `anchor` (world
// units), and starts `offset` screen pixels from there, at the pill's near
// edge; `side` says which way the pill's body extends from that point.
const CALLOUTS = {
  solar: { anchor: [2.95, 5.6, 4.4], offset: [-46, -48], side: "left" },
  grid: { anchor: [NODES.grid.x, NODES.grid.y, 0.6], offset: [46, 46], side: "right" },
  inverter: { anchor: [NODES.inverter.x, NODES.inverter.y, NODES.inverter.z - 0.45], offset: [40, 24], side: "right" },
  load: { anchor: [2.5, HOUSE.Y1 + 0.05, 2.35], offset: [-46, -54], side: "left" },
  backup: { anchor: [ANNEX.X1 + 0.05, -1.6, 1.15], offset: [24, -78], side: "right" },
  battery: { anchor: [NODES.battery.x + 0.06, NODES.battery.y + 0.1, 0.95], offset: [34, 86], side: "right" },
};

function calloutPoints(callout) {
  const [ax, ay] = P(...callout.anchor);
  return { anchor: [ax, ay], pill: [ax + callout.offset[0], ay + callout.offset[1]] };
}

function leaders() {
  const g = el("g", { class: "hs-leaders" });
  for (const [key, callout] of Object.entries(CALLOUTS)) {
    const { anchor, pill } = calloutPoints(callout);
    g.append(el("path", { class: "hs-leader", "data-callout": key, d: `M ${pill[0].toFixed(1)} ${pill[1].toFixed(1)} L ${anchor[0].toFixed(1)} ${anchor[1].toFixed(1)}`, fill: "none", stroke: "rgba(255,255,255,0.55)", "stroke-width": 1 }));
    g.append(el("circle", { class: "hs-leader-dot", "data-callout": key, cx: anchor[0].toFixed(1), cy: anchor[1].toFixed(1), r: 3, fill: "#ffffff" }));
  }
  return g;
}

function rain() {
  const g = el("g", { class: "hs-rain", "aria-hidden": "true" });
  let seed = 3;
  const random = () => { seed = (seed * 9301 + 49297) % 233280; return seed / 233280; };
  for (let index = 0; index < 30; index += 1) {
    const x = random() * SCENE_WIDTH;
    g.append(el("line", { x1: x, y1: 0, x2: x - 5, y2: 20, stroke: "rgba(190, 215, 255, 0.35)", "stroke-width": 1.2, "stroke-linecap": "round", class: "hs-drop", style: `--hs-drop-delay: ${(random() * 1.4).toFixed(2)}s; --hs-drop-dur: ${(0.9 + random() * 0.5).toFixed(2)}s` }));
  }
  return g;
}

// ---------------------------------------------------------------------------
// Helpers.
// ---------------------------------------------------------------------------

function el(name, attributes = {}) {
  const node = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attributes)) {
    if (value === undefined || value === null) continue;
    if (key === "href") node.setAttributeNS("http://www.w3.org/1999/xlink", "xlink:href", String(value));
    node.setAttribute(key, String(value));
  }
  return node;
}

function number(value) {
  const n = typeof value === "string" ? Number(value) : value;
  return typeof n === "number" && Number.isFinite(n) ? n : null;
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function toRadians(degrees) { return degrees * Math.PI / 180; }
function toDegrees(radians) { return radians * 180 / Math.PI; }

function hexToRgb(hex) {
  const value = hex.replace("#", "");
  const full = value.length === 3 ? value.split("").map((c) => c + c).join("") : value;
  const n = parseInt(full, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function mixHex(a, b, t) {
  const amount = clamp(t, 0, 1);
  const [r1, g1, b1] = hexToRgb(a);
  const [r2, g2, b2] = hexToRgb(b);
  const channel = (x, y) => Math.round(x + (y - x) * amount).toString(16).padStart(2, "0");
  return `#${channel(r1, r2)}${channel(g1, g2)}${channel(b1, b2)}`;
}

if (typeof document !== "undefined" && typeof window !== "undefined" && document.getElementById) {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", startHomeScene, { once: true });
  } else {
    startHomeScene();
  }
}

export {
  CALLOUTS,
  FLOW_COLORS,
  NODES,
  P,
  SKY,
  clockSolarPosition,
  flowsFor,
  mixHex,
  parseClockOverride,
  scenePhase,
  skyPalette,
  solarPosition,
  sunScreenPosition,
};
