// The Live Home Energy hero: an illustrated home, lit by the real sun.
//
// The scene is one inline SVG built here rather than an image, so every part
// of it can answer to live data: the sky and the light on the house follow the
// sun's actual elevation, clouds thicken with the reported cloud cover, the
// windows come on at dusk, the panels glint while they are producing, and
// energy moves along the conduits in the direction and at the rate the meters
// report. It listens to the same `battery-energy-flow` event and the same
// `data-*` attributes on the section that the dashboard already maintains, and
// to a `battery-weather` event for the sky, so it has no data path of its own.
//
// Sun position is the NOAA solar-position algorithm, the same one the monitor
// uses server-side, recomputed here every minute from the latitude and
// longitude the weather feed carries so the sun keeps moving between weather
// refreshes and when the feed is down. A `?sceneClock=` query parameter
// (an ISO time, or `HH:MM` for today) previews any hour of the day.

const SCENE_WIDTH = 1000;
const SCENE_HEIGHT = 560;
const HORIZON_Y = 352;
const SVG_NS = "http://www.w3.org/2000/svg";

// Where each source and sink lives in the scene. Everything else is placed
// relative to these, and the callouts in the page are anchored to the same
// points as percentages, so the labels stay beside their objects at any size.
const NODES = {
  solar: { x: 560, y: 148 },
  home: { x: 640, y: 318 },
  inverter: { x: 402, y: 300 },
  battery: { x: 262, y: 312 },
  grid: { x: 872, y: 168 },
  backup: { x: 470, y: 350 },
};

// Flow colours: solar amber, grid blue, battery green, load warm white. The
// same hues carry through the callout badges so a colour means one thing.
const FLOW_COLORS = {
  solar: "#ffbf3d",
  grid: "#5b9dff",
  battery: "#3ddc84",
  load: "#ffd89a",
  backup: "#ff8fb1",
  idle: "rgba(255, 255, 255, 0.32)",
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

// Sky palettes by phase of day. Each is [top, middle, horizon]. Cloud cover
// pulls every phase toward its own grey so an overcast noon reads as overcast,
// not as a different time of day.
const SKY = {
  night: { top: "#070b1a", mid: "#101a3b", low: "#1c2b52", grey: "#101318", ink: "#f2f4f8", stars: 1, ground: ["#1c3a31", "#132a24"], warm: 0 },
  dawn: { top: "#3d4d90", mid: "#c58ea6", low: "#ffcaa4", grey: "#5b6270", ink: "#f8f4f2", stars: 0.35, ground: ["#3b6b4c", "#2d5340"], warm: 0.55 },
  golden: { top: "#4a3f86", mid: "#ef8c5a", low: "#ffd4a2", grey: "#5a5a63", ink: "#fff6ee", stars: 0.12, ground: ["#4f8a52", "#3a6a43"], warm: 0.85 },
  day: { top: "#4fa8ff", mid: "#a4d9ff", low: "#e6f5ff", grey: "#aeb6c2", ink: "#0f172a", stars: 0, ground: ["#7fc36a", "#5fa451"], warm: 0.15 },
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
    daylight: clamp((el + 10) / 22, 0, 1) * (1 - cover * 0.45),
    // Windows and the porch lamp come on as the light goes, well before dark.
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
    sun: svg.querySelector("#hsSun"),
    sunGlow: svg.querySelector("#hsSunGlow"),
    moon: svg.querySelector("#hsMoon"),
    stars: svg.querySelector("#hsStars"),
    clouds: svg.querySelector("#hsClouds"),
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

  applyFlows(readFlowInput(section));
  applyLighting();
  fitStage();
  if ("ResizeObserver" in window) {
    new ResizeObserver(fitStage).observe(stage.parentElement || stage);
  } else {
    window.addEventListener("resize", fitStage);
  }

  window.addEventListener("battery-energy-flow", (event) => {
    applyFlows(readFlowInput(section, event.detail));
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
    // The largest 1000x560 box that fits, sat on the stage floor.
    const scale = Math.min(width / SCENE_WIDTH, height / SCENE_HEIGHT);
    const boxWidth = SCENE_WIDTH * scale;
    const boxHeight = SCENE_HEIGHT * scale;
    section.style.setProperty("--hs-box-width", `${boxWidth.toFixed(1)}px`);
    section.style.setProperty("--hs-box-height", `${boxHeight.toFixed(1)}px`);
    section.style.setProperty("--hs-box-left", `${((width - boxWidth) / 2).toFixed(1)}px`);
    section.style.setProperty("--hs-box-top", `${(height - boxHeight).toFixed(1)}px`);
    section.style.setProperty("--hs-scale", scale.toFixed(4));
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

    // The cabinet: state of charge as a fill, LEDs by what the pack is doing.
    const soc = clamp(number(input.soc) ?? 0, 0, 100);
    if (parts.socFill) {
      parts.socFill.setAttribute("height", String((soc / 100) * 54));
      parts.socFill.setAttribute("y", String(348 - (soc / 100) * 54));
      parts.socFill.setAttribute("fill", soc < 20 ? FLOW_COLORS.backup : FLOW_COLORS.battery);
    }
    const ledColour = input.mode === "charging" ? FLOW_COLORS.battery
      : input.mode === "discharging" ? FLOW_COLORS.solar
        : input.mode === "stale" ? "#6b7280" : "#9fb3c8";
    for (const led of parts.leds) led.setAttribute("fill", ledColour);
    if (parts.inverterScreen) {
      parts.inverterScreen.setAttribute("fill", input.inverterAvailable ? "#8fd6ff" : "#334155");
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
    section.style.setProperty("--hs-clouds", clamp(0.12 + state.cloudCover / 100 * 0.85, 0, 1).toFixed(3));
    section.dataset.raining = String(state.precipitation > 0.05);

    // Sun and moon on their arcs. The moon simply keeps the far side of the
    // sky, which is where a viewer expects it and close to true at dusk.
    const sun = sunScreenPosition(position.elevation, position.azimuth);
    if (parts.sun) parts.sun.setAttribute("transform", `translate(${sun.x.toFixed(1)} ${sun.y.toFixed(1)})`);
    const moonAcross = 1 - clamp((((position.azimuth ?? 180) % 360 + 360) % 360 - 70) / 220, 0, 1);
    const moonY = HORIZON_Y - clamp(-position.elevation, 0, 90) / 90 * (HORIZON_Y - 90);
    if (parts.moon) {
      parts.moon.setAttribute("transform", `translate(${(90 + moonAcross * (SCENE_WIDTH - 180)).toFixed(1)} ${moonY.toFixed(1)})`);
      parts.moon.style.opacity = String(clamp((-position.elevation - 2) / 6, 0, 1));
    }
    if (parts.sun) parts.sun.style.opacity = String(clamp((position.elevation + 4) / 6, 0, 1));

    // Light on the panels: the sun's height and the sky's clarity, and only
    // while the array is producing, so a bright but disconnected roof does
    // not pretend.
    const producing = section.dataset.solarActive === "true";
    const glint = producing ? clamp(palette.daylight, 0, 1) : palette.daylight * 0.25;
    section.style.setProperty("--hs-glint", glint.toFixed(3));
    // The house shadow swings with the sun's side.
    const az = ((position.azimuth ?? 180) % 360 + 360) % 360;
    const side = clamp((az - 180) / 90, -1, 1);
    if (parts.shadow) parts.shadow.setAttribute("transform", `translate(${(-side * 26).toFixed(1)} 0) scale(${(1 + Math.abs(side) * 0.35).toFixed(2)} 1)`);
    section.style.setProperty("--hs-light-side", side.toFixed(2));
  }

  return { applyFlows, applyLighting, state };
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
    preserveAspectRatio: "xMidYMax meet",
    class: "hs",
    "aria-hidden": "true",
    focusable: "false",
  });
  svg.append(defs());

  // Sky and the far ground.
  svg.append(el("rect", { class: "hs-sky", x: -1200, y: -600, width: SCENE_WIDTH + 2400, height: SCENE_HEIGHT + 600, fill: "url(#hsSky)" }));
  svg.append(stars());
  svg.append(clouds());
  svg.append(el("ellipse", { class: "hs-haze", cx: 500, cy: HORIZON_Y + 4, rx: 1500, ry: 90, fill: "url(#hsHaze)" }));
  svg.append(sun());
  svg.append(moon());
  svg.append(el("path", { class: "hs-hill hs-hill--far", d: "M-1200 372 C -900 340, -600 356, -300 350 S 120 318, 400 344 S 700 322, 860 338 S 1300 356, 1600 340 S 2000 360, 2200 350 L 2200 400 L -1200 400 Z", fill: "url(#hsGroundFar)" }));
  svg.append(el("path", { class: "hs-hill hs-hill--near", d: `M-1200 ${HORIZON_Y + 34} C -800 ${HORIZON_Y + 10}, -400 ${HORIZON_Y + 40}, -40 ${HORIZON_Y + 30} C 200 ${HORIZON_Y + 8}, 420 ${HORIZON_Y + 40}, 620 ${HORIZON_Y + 24} S 900 ${HORIZON_Y + 12}, 1040 ${HORIZON_Y + 36} S 1600 ${HORIZON_Y + 14}, 2200 ${HORIZON_Y + 40} L 2200 ${SCENE_HEIGHT + 400} L -1200 ${SCENE_HEIGHT + 400} Z`, fill: "url(#hsGround)" }));

  svg.append(trees());
  svg.append(el("ellipse", { id: "hsShadow", class: "hs-shadow", cx: 560, cy: 404, rx: 200, ry: 20, fill: "rgba(0,0,0,0.22)" }));
  svg.append(utilityPole());
  svg.append(house());
  svg.append(inverterBox());
  svg.append(batteryCabinet());
  svg.append(flows());
  svg.append(rain());
  return svg;
}

function defs() {
  const d = el("defs");
  d.append(gradient("hsSky", [["0", "var(--hs-sky-top, #4fa8ff)"], ["0.55", "var(--hs-sky-mid, #a4d9ff)"], ["1", "var(--hs-sky-low, #e6f5ff)"]], true));
  d.append(gradient("hsGround", [["0", "var(--hs-ground-top, #7fc36a)"], ["1", "var(--hs-ground-low, #5fa451)"]], true));
  d.append(gradient("hsGroundFar", [["0", "var(--hs-ground-top, #7fc36a)"], ["1", "var(--hs-ground-top, #7fc36a)"]], true, "0.72"));
  d.append(gradient("hsHaze", [["0", "var(--hs-sky-low, #e6f5ff)"], ["1", "var(--hs-sky-low, #e6f5ff)"]], false, undefined, true));
  d.append(gradient("hsRoof", [["0", "#4b5563"], ["1", "#1f2937"]], true));
  d.append(gradient("hsWallFront", [["0", "#f7f2ea"], ["1", "#e3dccf"]], true));
  d.append(gradient("hsWallSide", [["0", "#d9d2c4"], ["1", "#bcb3a3"]], true));
  d.append(gradient("hsPanel", [["0", "#1e3a8a"], ["0.5", "#1d4ed8"], ["1", "#172554"]], true));
  d.append(gradient("hsCabinet", [["0", "#2a2f36"], ["1", "#14171c"]], false));
  d.append(gradient("hsModule", [["0", "#3b4250"], ["1", "#20252d"]], true));
  d.append(gradient("hsSunGlow", [["0", "rgba(255, 214, 120, 0.85)"], ["0.45", "rgba(255, 190, 80, 0.28)"], ["1", "rgba(255, 190, 80, 0)"]], false, undefined, true));
  d.append(gradient("hsMoonGlow", [["0", "rgba(210, 226, 255, 0.55)"], ["1", "rgba(210, 226, 255, 0)"]], false, undefined, true));
  d.append(gradient("hsWindow", [["0", "#ffe6a8"], ["1", "#ffb454"]], true));
  d.append(gradient("hsLampGlow", [["0", "rgba(255, 205, 120, 0.7)"], ["1", "rgba(255, 205, 120, 0)"]], false, undefined, true));
  // Soft glow for the flows and the lit windows.
  const glow = el("filter", { id: "hsGlow", x: "-40%", y: "-40%", width: "180%", height: "180%" });
  glow.append(el("feGaussianBlur", { stdDeviation: "3.2", result: "blur" }));
  const merge = el("feMerge");
  merge.append(el("feMergeNode", { in: "blur" }), el("feMergeNode", { in: "SourceGraphic" }));
  glow.append(merge);
  d.append(glow);
  const soft = el("filter", { id: "hsSoft", x: "-20%", y: "-20%", width: "140%", height: "140%" });
  soft.append(el("feGaussianBlur", { stdDeviation: "6" }));
  d.append(soft);
  // The roof slope, so panels and their glints share one transform.
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
  // A fixed field, so the sky is the same sky every night.
  let seed = 7;
  const random = () => { seed = (seed * 9301 + 49297) % 233280; return seed / 233280; };
  for (let index = 0; index < 64; index += 1) {
    const x = 20 + random() * (SCENE_WIDTH - 40);
    const y = 16 + random() * (HORIZON_Y - 120);
    const r = 0.7 + random() * 1.3;
    g.append(el("circle", { cx: x.toFixed(1), cy: y.toFixed(1), r: r.toFixed(2), fill: "#ffffff", class: "hs-star", style: `--hs-twinkle-delay: ${(random() * 6).toFixed(2)}s; --hs-twinkle-dur: ${(2.5 + random() * 3).toFixed(2)}s` }));
  }
  return g;
}

function sun() {
  const g = el("g", { id: "hsSun", class: "hs-sun" });
  g.append(el("circle", { id: "hsSunGlow", r: 96, fill: "url(#hsSunGlow)" }));
  g.append(el("circle", { r: 26, fill: "#fff1c2", class: "hs-sun-disc" }));
  g.append(el("circle", { r: 22, fill: "#ffd166" }));
  return g;
}

function moon() {
  const g = el("g", { id: "hsMoon", class: "hs-moon" });
  g.append(el("circle", { r: 70, fill: "url(#hsMoonGlow)" }));
  const disc = el("circle", { r: 18, fill: "#eef3ff" });
  const bite = el("circle", { cx: 8, cy: -5, r: 15, fill: "var(--hs-sky-top, #070b1a)", opacity: "0.92" });
  g.append(disc, bite);
  return g;
}

function clouds() {
  const g = el("g", { id: "hsClouds", class: "hs-clouds" });
  const cloud = (x, y, scale, delay, dur) => {
    const c = el("g", { class: "hs-cloud", transform: `translate(${x} ${y}) scale(${scale})` });
    const drift = el("g", { class: "hs-cloud-drift", style: `--hs-drift-delay: ${delay}s; --hs-drift-dur: ${dur}s` });
    for (const [cx, cy, rx, ry] of [[0, 0, 62, 24], [-40, 6, 38, 18], [44, 4, 44, 20], [10, -16, 36, 22]]) {
      drift.append(el("ellipse", { cx, cy, rx, ry }));
    }
    c.append(drift);
    return c;
  };
  g.append(cloud(180, 96, 1, 0, 140), cloud(560, 62, 0.72, -50, 170), cloud(840, 118, 0.88, -110, 155));
  return g;
}

function trees() {
  const g = el("g", { class: "hs-trees hs-lit" });
  const tree = (x, y, s) => {
    const t = el("g", { transform: `translate(${x} ${y}) scale(${s})` });
    t.append(el("rect", { x: -3, y: -6, width: 6, height: 22, rx: 2, fill: "#5b3a24" }));
    t.append(el("ellipse", { cx: 0, cy: -22, rx: 20, ry: 24, fill: "var(--hs-ground-low, #5fa451)" }));
    t.append(el("ellipse", { cx: -8, cy: -12, rx: 16, ry: 16, fill: "var(--hs-ground-top, #7fc36a)" }));
    return t;
  };
  g.append(tree(96, 372, 1.15), tree(150, 384, 0.9), tree(960, 380, 1.05));
  return g;
}

function utilityPole() {
  const g = el("g", { class: "hs-pole hs-lit" });
  const { x } = NODES.grid;
  g.append(el("rect", { x: x - 5, y: 150, width: 10, height: 240, rx: 3, fill: "#6b5341" }));
  g.append(el("rect", { x: x - 42, y: 168, width: 84, height: 7, rx: 2, fill: "#5a4535" }));
  g.append(el("rect", { x: x - 30, y: 190, width: 60, height: 6, rx: 2, fill: "#5a4535" }));
  for (const dx of [-34, -12, 12, 34]) g.append(el("rect", { x: x + dx - 3, y: 160, width: 6, height: 9, rx: 2, fill: "#9ca3af" }));
  // Transformer can.
  g.append(el("rect", { x: x + 8, y: 206, width: 26, height: 40, rx: 6, fill: "#4b5563" }));
  // Lines off to the edge of the world.
  g.append(el("path", { d: `M ${x - 34} 160 C ${x + 60} 150, ${x + 120} 156, 1040 140`, stroke: "#374151", "stroke-width": 2, fill: "none", opacity: 0.8 }));
  g.append(el("path", { d: `M ${x + 34} 160 C ${x + 90} 154, ${x + 130} 160, 1040 152`, stroke: "#374151", "stroke-width": 2, fill: "none", opacity: 0.8 }));
  return g;
}

function house() {
  const root = el("g", { class: "hs-house" });
  const g = el("g", { class: "hs-house-body hs-lit" });
  const lights = el("g", { class: "hs-house-lights" });
  root.append(g, lights);
  // Side wall (left, in shade), front wall, roof planes, chimney.
  g.append(el("polygon", { points: "470,260 560,236 560,392 470,392", fill: "url(#hsWallSide)" }));
  g.append(el("polygon", { points: "560,236 790,236 790,392 560,392", fill: "url(#hsWallFront)" }));
  // Roof: the left slope carries the array and faces the sun.
  g.append(el("polygon", { class: "hs-roof", points: "452,262 560,182 800,182 800,236 560,236", fill: "url(#hsRoof)" }));
  g.append(el("polygon", { points: "452,262 560,182 560,236 470,260", fill: "#111827", opacity: 0.35 }));
  g.append(el("rect", { x: 728, y: 190, width: 22, height: 44, fill: "#9a6b53" }));
  g.append(el("rect", { x: 724, y: 186, width: 30, height: 8, rx: 2, fill: "#7c5442" }));
  // Eaves and trim.
  g.append(el("rect", { x: 556, y: 232, width: 248, height: 6, rx: 2, fill: "#374151" }));
  // Front: door with porch lamp, three windows.
  g.append(el("rect", { x: 660, y: 318, width: 40, height: 74, rx: 3, fill: "#7c4a35" }));
  g.append(el("circle", { cx: 692, cy: 358, r: 2.2, fill: "#f4d58d" }));
  g.append(el("rect", { x: 712, y: 300, width: 8, height: 6, rx: 1, fill: "#374151" }));
  lights.append(el("circle", { id: "hsLampGlow", class: "hs-lamp-glow", cx: 716, cy: 312, r: 34, fill: "url(#hsLampGlow)" }));
  lights.append(el("circle", { id: "hsLamp", class: "hs-lamp", cx: 716, cy: 312, r: 4, fill: "#fde68a" }));
  for (const [x, y, w, h] of [[588, 262, 42, 40], [732, 262, 42, 40], [588, 322, 42, 40]]) {
    g.append(el("rect", { class: "hs-window-frame", x: x - 3, y: y - 3, width: w + 6, height: h + 6, rx: 3, fill: "#374151" }));
    // Dark glass by day, with a hint of the sky in it; warm light through it at night.
    g.append(el("rect", { class: "hs-window-glass", x, y, width: w, height: h, rx: 2, fill: "#243247" }));
    g.append(el("rect", { class: "hs-window-sky", x: x + 3, y: y + 3, width: w * 0.5, height: h - 6, rx: 1.5, fill: "url(#hsSky)", opacity: 0.35 }));
    lights.append(el("rect", { class: "hs-window", x, y, width: w, height: h, rx: 2, fill: "url(#hsWindow)" }));
    lights.append(el("path", { d: `M ${x + w / 2} ${y} v ${h} M ${x} ${y + h / 2} h ${w}`, stroke: "#374151", "stroke-width": 2, opacity: 0.85 }));
  }
  // Side-wall window.
  g.append(el("polygon", { class: "hs-window-glass", points: "492,282 526,272 526,314 492,322", fill: "#243247" }));
  lights.append(el("polygon", { class: "hs-window hs-window--side", points: "492,282 526,272 526,314 492,322", fill: "url(#hsWindow)" }));
  // Solar array on the left slope: a skewed grid of cells with a glint each.
  const array = el("g", { class: "hs-array", transform: "matrix(1 0 -0.66 1 0 0) translate(134 0)" });
  for (let row = 0; row < 3; row += 1) {
    for (let col = 0; col < 4; col += 1) {
      const x = 490 + col * 54;
      const y = 190 + row * 15.5;
      array.append(el("rect", { x, y, width: 50, height: 13, rx: 1.4, fill: "url(#hsPanel)", stroke: "#0b1120", "stroke-width": 0.8 }));
      array.append(el("rect", { class: "hs-panel-glint", x: x + 3, y: y + 2, width: 44, height: 4, rx: 1, fill: "#ffffff", style: `--hs-glint-delay: ${((row * 4 + col) * 0.22).toFixed(2)}s` }));
    }
  }
  g.append(array);
  // Ground line under the house.
  g.append(el("rect", { x: 466, y: 390, width: 328, height: 6, rx: 2, fill: "#374151", opacity: 0.55 }));
  return root;
}

function inverterBox() {
  const g = el("g", { class: "hs-inverter hs-lit" });
  const { x, y } = NODES.inverter;
  g.append(el("rect", { x: x - 30, y: y - 40, width: 60, height: 84, rx: 8, fill: "#e5e7eb", stroke: "#9ca3af", "stroke-width": 1.5 }));
  g.append(el("rect", { x: x - 22, y: y - 30, width: 44, height: 22, rx: 3, id: "hsInverterScreen", class: "hs-inverter-screen", fill: "#8fd6ff" }));
  g.append(el("rect", { x: x - 22, y: y + 2, width: 44, height: 30, rx: 3, fill: "#cbd5e1" }));
  for (const dy of [8, 16, 24]) g.append(el("rect", { x: x - 16, y: y + dy, width: 32, height: 2.5, rx: 1, fill: "#94a3b8" }));
  g.append(el("rect", { x: x - 30, y: y + 44, width: 60, height: 8, rx: 2, fill: "#9ca3af", opacity: 0.6 }));
  return g;
}

function batteryCabinet() {
  const g = el("g", { class: "hs-cabinet hs-lit" });
  const { x } = NODES.battery;
  g.append(el("rect", { x: x - 46, y: 262, width: 92, height: 130, rx: 8, fill: "url(#hsCabinet)", stroke: "#0b0d10", "stroke-width": 1.5 }));
  for (let index = 0; index < 3; index += 1) {
    const y = 274 + index * 38;
    g.append(el("rect", { x: x - 38, y, width: 76, height: 30, rx: 4, fill: "url(#hsModule)", stroke: "#0f1216", "stroke-width": 1 }));
    g.append(el("rect", { x: x - 30, y: y + 8, width: 36, height: 14, rx: 2, fill: "#111418" }));
    g.append(el("circle", { class: "hs-led", cx: x + 24, cy: y + 15, r: 3.2, fill: "#9fb3c8" }));
    g.append(el("circle", { cx: x + 24, cy: y + 15, r: 6, fill: "none", class: "hs-led-ring" }));
  }
  // The charge gauge on the cabinet's side.
  g.append(el("rect", { x: x + 50, y: 292, width: 10, height: 56, rx: 3, fill: "rgba(255,255,255,0.12)", stroke: "rgba(255,255,255,0.28)" }));
  g.append(el("rect", { id: "hsSocFill", x: x + 51, y: 348, width: 8, height: 0, rx: 2.5, fill: FLOW_COLORS.battery }));
  g.append(el("rect", { x: x - 46, y: 392, width: 92, height: 6, rx: 2, fill: "#0b0d10", opacity: 0.5 }));
  return g;
}

// The conduits. Every route is a smooth path from source to sink; a faint
// track always shows the topology, a dashed overlay moves with power, and two
// dots ride the path on an animateMotion so direction is unmistakable.
const ROUTES = {
  solar: `M ${NODES.solar.x - 40} ${NODES.solar.y + 60} C ${NODES.solar.x - 120} ${NODES.solar.y + 120}, ${NODES.inverter.x + 40} ${NODES.inverter.y - 90}, ${NODES.inverter.x} ${NODES.inverter.y - 40}`,
  battery: `M ${NODES.battery.x + 46} ${NODES.battery.y + 20} C ${NODES.battery.x + 80} ${NODES.battery.y + 20}, ${NODES.inverter.x - 60} ${NODES.inverter.y + 20}, ${NODES.inverter.x - 30} ${NODES.inverter.y + 20}`,
  home: `M ${NODES.inverter.x + 30} ${NODES.inverter.y} C ${NODES.inverter.x + 60} ${NODES.inverter.y}, ${NODES.home.x - 120} ${NODES.home.y + 40}, ${NODES.home.x - 80} ${NODES.home.y + 40}`,
  backup: `M ${NODES.inverter.x + 30} ${NODES.inverter.y + 30} C ${NODES.inverter.x + 50} ${NODES.inverter.y + 30}, ${NODES.backup.x - 30} ${NODES.backup.y + 20}, ${NODES.backup.x} ${NODES.backup.y + 20}`,
  grid: `M ${NODES.grid.x - 20} ${NODES.grid.y + 40} C ${NODES.grid.x - 60} ${NODES.grid.y + 120}, ${NODES.home.x + 200} ${NODES.home.y + 20}, ${NODES.home.x + 150} ${NODES.home.y + 40}`,
};

function flows() {
  const g = el("g", { class: "hs-flows" });
  for (const [key, d] of Object.entries(ROUTES)) {
    g.append(el("path", { id: `hsFlow-${key}-track`, class: "hs-flow-track", d, fill: "none", stroke: FLOW_COLORS.idle, "stroke-width": 5, "stroke-linecap": "round", "data-active": "false" }));
    g.append(el("path", { id: `hsFlow-${key}-dash`, class: "hs-flow-dash", d, fill: "none", stroke: FLOW_COLORS.idle, "stroke-width": 3.2, "stroke-linecap": "round", "data-active": "false" }));
    for (let index = 0; index < 2; index += 1) {
      const dot = el("circle", { class: "hs-flow-dot", r: 4.2, fill: FLOW_COLORS.idle, "data-flow": key, "data-active": "false", filter: "url(#hsGlow)" });
      const motion = el("animateMotion", { dur: "4s", repeatCount: "indefinite", begin: `${index * 2}s`, keyPoints: "0;1", keyTimes: "0;1", calcMode: "linear" });
      motion.append(el("mpath", { href: `#hsFlow-${key}-track` }));
      dot.append(motion);
      g.append(dot);
    }
  }
  return g;
}

function rain() {
  const g = el("g", { class: "hs-rain", "aria-hidden": "true" });
  let seed = 3;
  const random = () => { seed = (seed * 9301 + 49297) % 233280; return seed / 233280; };
  for (let index = 0; index < 34; index += 1) {
    const x = random() * SCENE_WIDTH;
    g.append(el("line", { x1: x, y1: 0, x2: x - 6, y2: 22, stroke: "rgba(190, 215, 255, 0.55)", "stroke-width": 1.4, "stroke-linecap": "round", class: "hs-drop", style: `--hs-drop-delay: ${(random() * 1.4).toFixed(2)}s; --hs-drop-dur: ${(0.9 + random() * 0.5).toFixed(2)}s` }));
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
  FLOW_COLORS,
  NODES,
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
