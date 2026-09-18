import * as THREE from "three";

// The rack scene deliberately mirrors the Live home energy scene's visual language
// (same flow palette, same constant-speed pulses, same conduit styling) but its stage
// holds nothing except the Eco-worthy battery modules and the energy flowing in and
// out of them: no house, no inverter, no grid.
const FLOW_COLORS = {
  charging: 0xd9ff3f,
  discharging: 0xff6258,
  idle: 0xff9f0a,
  stale: 0x777b82,
};

// CSS colours for the on-module LCD, keyed by the same modes.
const LCD_COLORS = {
  charging: "#d9ff3f",
  discharging: "#ff6258",
  idle: "#ff9f0a",
  stale: "#8a8f97",
};

const BRAND_GREEN = "#57c26a";
const BUS_COLOR = 0x72d7ff;

// One Eco-worthy 48 V / 100 Ah rack module is 442 x 420 x 132 mm (19-inch, 3U).
// Scene units keep that ratio so the stack reads as real rack hardware.
const MODULE = { width: 3.58, height: 1.07, depth: 3.4, pitch: 1.19 };
const BODY = { width: 3.3, height: MODULE.height, depth: MODULE.depth };
const FACE = { width: MODULE.width, height: MODULE.height - 0.05, thickness: 0.06 };
const FACE_Z = BODY.depth / 2 + FACE.thickness / 2;
const FACE_FRONT = FACE_Z + FACE.thickness / 2;

const MAX_MODULES = 8;
const DEFAULT_MODULES = 3;
const SOC_LEDS = 6;

// Terminal block on the right of each faceplate, the rack bus riser it taps into,
// and how far the bus runs past the stack before the rack output leaves the frame.
const TERMINAL_X = 1.42;
const PORT_Z = FACE_FRONT + 0.06;
const BUS_X = 2.62;
const BUS_FOOT = 0.4;
const BUS_HEAD = 0.9;
const BUS_OUT = 1.15;

const CAMERA_POSITION = new THREE.Vector3(5.4, 3.3, 10.6);
const CAMERA_LOOK_AT = new THREE.Vector3(0, 0, 0);
const BLOOM = { strength: 0.12, radius: 0.6, threshold: 0.62 };
const ACTIVE_LINE_OPACITY = 0.82;
const ACTIVE_GLOW_OPACITY = 0.03;
// Pulses travel one constant world-space speed on every conduit, exactly like the
// home scene: short pack taps and the long bus riser move at the same rate.
const PULSE_SPEED_DEFAULT = 0.2;
const PULSE_SPEED_MIN = 0.02;
const PULSE_SPEED_MAX = 0.6;
const PULSE_REFERENCE_LENGTH = 3.5;

function startRackFlowScene() {
  const section = document.getElementById("rackSummarySection");
  const stage = document.getElementById("rackFlowStage");
  const canvas = document.getElementById("rackFlowCanvas");
  if (!section || !stage || !canvas) return;

  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({
      canvas,
      alpha: true,
      antialias: true,
      powerPreference: "high-performance",
      preserveDrawingBuffer: true,
    });
  } catch (error) {
    showFallback(section, canvas, error);
    return;
  }

  renderer.setClearColor(0x000000, 0);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.06;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFShadowMap;

  const scene = new THREE.Scene();
  const camera = new THREE.OrthographicCamera(-5, 5, 3, -3, 0.1, 60);
  camera.position.copy(CAMERA_POSITION);
  camera.lookAt(CAMERA_LOOK_AT);

  const root = new THREE.Group();
  scene.add(root);

  const materials = createRackMaterials();
  let rackCount = DEFAULT_MODULES;
  let rack = buildRack(materials, rackCount);
  root.add(rack.group);

  // The framing basis never moves, so the stage can be framed from the camera's
  // resting orientation while per-frame parallax still nudges the live camera.
  const frameBasis = (() => {
    const helper = new THREE.Object3D();
    helper.position.copy(CAMERA_POSITION);
    helper.lookAt(CAMERA_LOOK_AT);
    helper.updateMatrixWorld(true);
    return helper.matrixWorld.clone().invert();
  })();

  const ambient = new THREE.HemisphereLight(0xeef4ff, 0x0e1013, 1.9);
  const keyLight = new THREE.DirectionalLight(0xffffff, 3.2);
  keyLight.position.set(-3.4, 6.6, 8.4);
  keyLight.castShadow = true;
  keyLight.shadow.mapSize.set(1024, 1024);
  keyLight.shadow.camera.left = -6;
  keyLight.shadow.camera.right = 6;
  keyLight.shadow.camera.top = 6;
  keyLight.shadow.camera.bottom = -6;
  keyLight.shadow.bias = -0.0004;
  const rimLight = new THREE.DirectionalLight(0xcfe2ea, 1.5);
  rimLight.position.set(6.2, 2.4, -4.6);
  const fillLight = new THREE.DirectionalLight(0xdbe6ee, 1.25);
  fillLight.position.set(3.2, 1.4, 7.8);
  scene.add(ambient, keyLight, rimLight, fillLight);

  const rackState = {
    mode: "stale",
    soc: 0,
    power: 0,
    current: 0,
    batteryCount: 0,
    packs: [],
  };

  const motionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
  const finePointerQuery = window.matchMedia("(hover: hover) and (pointer: fine)");
  const pointer = new THREE.Vector2();
  const parallax = new THREE.Vector2();
  let frameRequest = 0;
  let frameCount = 0;
  let isIntersecting = true;
  let isDocumentVisible = !document.hidden;
  let disposed = false;
  let composer = null;
  let bloomPass = null;
  let pulseSpeed = resolvePulseSpeed(section.dataset.pulseSpeed);
  let lineGlow = section.dataset.lineGlow === "true" || section.dataset.lineGlow === "1";
  let glowStrength = resolveGlowStrength(section.dataset.glowStrength);

  function resolveGlowStrength(raw) {
    if (raw === undefined || raw === null || raw === "") return BLOOM.strength;
    const value = Number(raw);
    return Number.isFinite(value) ? clamp(value, 0, 1.5) : BLOOM.strength;
  }

  function resolvePulseSpeed(raw) {
    if (raw === undefined || raw === null || raw === "") return PULSE_SPEED_DEFAULT;
    const value = Number(raw);
    return Number.isFinite(value)
      ? clamp(value, PULSE_SPEED_MIN, PULSE_SPEED_MAX)
      : PULSE_SPEED_DEFAULT;
  }

  function applyRouteStyle() {
    rack.network.routes.forEach((route) => styleRouteGlow(route, lineGlow, ACTIVE_LINE_OPACITY));
  }

  function readSectionState(detail = {}) {
    return {
      mode: validMode(detail.mode ?? section.dataset.rackMode),
      soc: clamp(finite(detail.soc ?? section.dataset.rackSoc), 0, 100),
      power: finite(detail.power ?? section.dataset.rackPower),
      current: finite(detail.current ?? section.dataset.rackCurrent),
      batteryCount: Math.max(0, Math.round(finite(detail.batteryCount ?? section.dataset.rackCount))),
      packs: normalizeRackPacks(detail.packs ?? section.dataset.rackPacks),
    };
  }

  // Grow or shrink the stack to the rack's real pack count. Rebuilding is cheap and
  // rare (only when the collector's inventory changes) and keeps the stack centred.
  function ensureRackSize(count) {
    const next = clamp(Math.round(count) || DEFAULT_MODULES, 1, MAX_MODULES);
    if (next === rackCount) return false;
    root.remove(rack.group);
    disposeObject(rack.group);
    rackCount = next;
    rack = buildRack(materials, rackCount);
    root.add(rack.group);
    return true;
  }

  function applyRackState(detail = {}) {
    Object.assign(rackState, readSectionState(detail));
    const resized = ensureRackSize(Math.max(rackState.packs.length, rackState.batteryCount));
    const rackColor = FLOW_COLORS[rackState.mode];
    const rackLive = rackState.mode !== "stale";

    rack.modules.forEach((module, index) => {
      const pack = rackState.packs[index];
      const reporting = Boolean(pack?.reporting);
      const mode = reporting ? validMode(pack.mode) : "stale";
      const color = FLOW_COLORS[mode];
      const soc = clamp(pack?.soc ?? 0, 0, 100);
      const known = reporting && pack?.soc !== null && pack?.soc !== undefined;
      const lit = known ? Math.max(1, Math.ceil((soc / 100) * SOC_LEDS)) : 0;

      module.litLeds = lit;
      module.mode = mode;
      module.reporting = reporting;
      module.socLedMaterials.forEach((material, ledIndex) => {
        const on = ledIndex < lit;
        material.color.setHex(on ? color : 0x2a2e33);
        material.emissive.setHex(on ? color : 0x101214);
        material.emissiveIntensity = on ? 1.3 : 0.05;
      });
      setSignal(module.runMaterial, reporting ? 0x51d48a : 0x2b3034, reporting);
      setSignal(module.alarmMaterial, pack?.alarm ? 0xff4d4d : 0x35292b, Boolean(pack?.alarm));
      setSignal(module.portMaterial, reporting ? color : FLOW_COLORS.stale, reporting && isActiveRouteMode(mode));
      module.stripeMaterial.color.setHex(color);
      module.stripeMaterial.emissive.setHex(color);
      module.stripeMaterial.emissiveIntensity = reporting && isActiveRouteMode(mode) ? 1.15 : 0.12;
      drawModuleScreen(module, pack, reporting, mode);

      const tap = rack.network.taps[index];
      if (!tap) return;
      const packPower = pack?.power ?? 0;
      const active = reporting && isActiveRouteMode(mode);
      // The tap curve runs pack -> bus, so discharging travels forward and charging back.
      configureRoute(tap, mode, routeMagnitude(packPower), active, mode === "charging" ? -1 : 1, reporting, color);
    });

    const trunkActive = rackLive && isActiveRouteMode(rackState.mode);
    configureRoute(
      rack.network.trunk,
      rackState.mode,
      routeMagnitude(rackState.power),
      trunkActive,
      rackState.mode === "charging" ? -1 : 1,
      rackLive,
      trunkActive ? rackColor : BUS_COLOR,
    );

    canvas.dataset.rackModules = String(rack.modules.length);
    canvas.dataset.rackMode = rackState.mode;
    canvas.dataset.activeRoutes = String(rack.network.routes.filter(isRouteActive).length);
    canvas.dataset.rackDirection = rackState.mode === "charging"
      ? "bus-to-packs"
      : rackState.mode === "discharging"
        ? "packs-to-bus"
        : "paused";
    canvas.dataset.topology = "packs-and-bus-only";
    canvas.dataset.hardware = "eco-worthy-rack";
    applyRouteStyle();
    if (disposed) return;
    if (resized) resize();
    else renderOnce(performance.now());
    scheduleFrame();
  }

  function shouldAnimate() {
    return !disposed
      && !motionQuery.matches
      && isIntersecting
      && isDocumentVisible
      && rack.network.routes.some(isRouteActive);
  }

  function updateParticles(time) {
    const tangent = new THREE.Vector3();
    const position = new THREE.Vector3();

    rack.network.routes.forEach((route) => {
      const active = isRouteActive(route);
      const speed = pulseProgressRate(route, pulseSpeed);
      route.particles.forEach((particle, index) => {
        particle.visible = active;
        if (!particle.visible) return;
        const progress = wrap01(index + route.phaseOffset + route.direction * time * 0.001 * speed);
        route.curve.getPointAt(progress, position);
        route.curve.getTangentAt(progress, tangent).multiplyScalar(route.direction).normalize();
        particle.position.copy(position);
        particle.quaternion.setFromUnitVectors(route.forwardAxis, tangent);
        particle.scale.setScalar(clamp(Math.sin(Math.PI * progress) * 1.6, 0.35, 1));
      });
      route.particleMaterial.opacity = active ? 0.96 : 0;
      route.particleGlowMaterial.opacity = active ? 0.08 : 0;
    });

    rack.modules.forEach((module, index) => {
      // The topmost lit cell breathes while the pack is moving power, the way a real
      // SOC gauge steps as it fills or drains.
      if (module.reporting && isActiveRouteMode(module.mode) && module.litLeds > 0) {
        const material = module.socLedMaterials[module.litLeds - 1];
        material.emissiveIntensity = 1.05 + Math.sin(time * 0.0042 + index * 0.8) * 0.42;
        module.stripeMaterial.emissiveIntensity = 1.0 + Math.sin(time * 0.0036 + index * 0.62) * 0.3;
      }
      pulseSignal(module.portMaterial, module.reporting && isActiveRouteMode(module.mode), time, index * 0.45);
    });

    const flowColor = FLOW_COLORS[rackState.mode];
    updatePuddle(rack.puddle, rack.network.routes.some(isRouteActive), flowColor, time, 0.4);
  }

  function renderOnce(time) {
    if (disposed) return;
    updateParticles(time);
    parallax.x += (pointer.x - parallax.x) * 0.05;
    parallax.y += (pointer.y - parallax.y) * 0.05;
    camera.position.set(
      CAMERA_POSITION.x + parallax.x * 0.5,
      CAMERA_POSITION.y + parallax.y * 0.34,
      CAMERA_POSITION.z - parallax.x * 0.22,
    );
    camera.lookAt(
      CAMERA_LOOK_AT.x + parallax.x * 0.1,
      CAMERA_LOOK_AT.y + parallax.y * 0.06,
      CAMERA_LOOK_AT.z,
    );
    root.rotation.y = parallax.x * 0.03;
    if (composer) composer.render();
    else renderer.render(scene, camera);
    frameCount += 1;
    if (frameCount === 1 || frameCount % 10 === 0) canvas.dataset.frame = String(frameCount);
  }

  function animate(time) {
    frameRequest = 0;
    renderOnce(time);
    scheduleFrame();
  }

  function scheduleFrame() {
    if (!frameRequest && shouldAnimate()) frameRequest = window.requestAnimationFrame(animate);
  }

  async function setupPostProcessing() {
    try {
      const [{ EffectComposer }, { RenderPass }, { UnrealBloomPass }, { OutputPass }] =
        await Promise.all([
          import("three/addons/postprocessing/EffectComposer.js"),
          import("three/addons/postprocessing/RenderPass.js"),
          import("three/addons/postprocessing/UnrealBloomPass.js"),
          import("three/addons/postprocessing/OutputPass.js"),
        ]);
      if (disposed) return;
      const size = renderer.getSize(new THREE.Vector2());
      const nextComposer = new EffectComposer(renderer);
      nextComposer.setPixelRatio(renderer.getPixelRatio());
      nextComposer.addPass(new RenderPass(scene, camera));
      const bloom = new UnrealBloomPass(size, glowStrength, BLOOM.radius, BLOOM.threshold);
      nextComposer.addPass(bloom);
      nextComposer.addPass(new OutputPass());
      composer = nextComposer;
      bloomPass = bloom;
      canvas.dataset.bloom = "on";
      resize();
    } catch (error) {
      composer = null;
      bloomPass = null;
      canvas.dataset.bloom = "off";
      console.warn("Rack-flow bloom unavailable; rendering without post-processing.", error);
    }
  }

  // Measure how much of the stage the stack covers once projected along the camera's
  // resting axis, so a three-pack and an eight-pack rack are both framed the same.
  function projectedBounds() {
    const box = rack.bounds;
    const corner = new THREE.Vector3();
    let minX = Infinity;
    let maxX = -Infinity;
    let minY = Infinity;
    let maxY = -Infinity;
    for (let index = 0; index < 8; index += 1) {
      corner.set(
        index & 1 ? box.max.x : box.min.x,
        index & 2 ? box.max.y : box.min.y,
        index & 4 ? box.max.z : box.min.z,
      ).applyMatrix4(frameBasis);
      minX = Math.min(minX, corner.x);
      maxX = Math.max(maxX, corner.x);
      minY = Math.min(minY, corner.y);
      maxY = Math.max(maxY, corner.y);
    }
    return { minX, maxX, minY, maxY };
  }

  function resize() {
    if (disposed) return;
    const bounds = stage.getBoundingClientRect();
    const width = Math.max(1, Math.round(bounds.width));
    const height = Math.max(1, Math.round(bounds.height));
    const aspect = width / height;
    const view = projectedBounds();
    const padding = width <= 600 ? 0.28 : 0.42;
    const contentWidth = view.maxX - view.minX;
    const contentHeight = view.maxY - view.minY;
    let viewWidth = contentWidth + padding * 2;
    let viewHeight = contentHeight + padding * 2;
    if (viewWidth / viewHeight < aspect) viewWidth = viewHeight * aspect;
    else viewHeight = viewWidth / aspect;
    // Spend only as much of the stage's spare room as it takes to clear the overlay
    // copy -- sideways when there is width to give, downwards otherwise -- so the
    // stack stays as close to centred, and as large, as the stage allows.
    const slackX = (viewWidth - contentWidth) / 2;
    const slackY = (viewHeight - contentHeight) / 2;
    const unitsX = viewWidth / width;
    const unitsY = viewHeight / height;
    const copy = stage.querySelector(".rack-flow__copy");
    const copyBox = copy ? copy.getBoundingClientRect() : null;
    const clearX = copyBox ? copyBox.right - bounds.left + 14 : 0;
    const clearY = copyBox ? copyBox.bottom - bounds.top + 10 : 0;
    let shift = 0;
    let drop = 0;
    const roomX = Math.max(0, slackX - padding * 0.5);
    const roomY = Math.max(0, slackY - padding * 0.5);
    const needX = clearX * unitsX - slackX;
    const needY = clearY * unitsY - slackY;
    if (needX > 0 && roomX >= needX) shift = needX;
    else if (needY > 0) drop = Math.min(needY, roomY);
    const centerX = (view.minX + view.maxX) / 2 - shift;
    const centerY = (view.minY + view.maxY) / 2 + drop;
    camera.left = centerX - viewWidth / 2;
    camera.right = centerX + viewWidth / 2;
    camera.top = centerY + viewHeight / 2;
    camera.bottom = centerY - viewHeight / 2;
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, width <= 600 ? 1.5 : 2));
    renderer.setSize(width, height, false);
    renderer.shadowMap.enabled = width > 480;
    if (composer) {
      composer.setPixelRatio(renderer.getPixelRatio());
      composer.setSize(width, height);
    }
    if (bloomPass) bloomPass.strength = glowStrength;
    camera.updateProjectionMatrix();
    renderOnce(performance.now());
  }

  function updateTheme() {
    const dark = document.documentElement.dataset.theme === "dark";
    materials.chassis.color.setHex(dark ? 0x353a3f : 0x3c4248);
    materials.chassisSide.color.setHex(dark ? 0x25292d : 0x2b3036);
    materials.face.color.setHex(dark ? 0x1b1f23 : 0x1f2429);
    materials.faceInset.color.setHex(dark ? 0x0d1013 : 0x101418);
    materials.trim.color.setHex(dark ? 0xcbd1d6 : 0xd8dee3);
    ambient.intensity = dark ? 1.85 : 2.0;
    keyLight.intensity = dark ? 3.1 : 3.4;
    rimLight.intensity = dark ? 1.6 : 1.4;
    renderer.toneMappingExposure = dark ? 1.08 : 1.04;
    renderOnce(performance.now());
  }

  const resizeObserver = "ResizeObserver" in window ? new ResizeObserver(resize) : null;
  resizeObserver?.observe(stage);
  if (!resizeObserver) window.addEventListener("resize", resize);

  const intersectionObserver = "IntersectionObserver" in window
    ? new IntersectionObserver((entries) => {
        isIntersecting = entries[0]?.isIntersecting ?? true;
        if (!isIntersecting && frameRequest) {
          window.cancelAnimationFrame(frameRequest);
          frameRequest = 0;
        }
        scheduleFrame();
      }, { rootMargin: "120px" })
    : null;
  intersectionObserver?.observe(section);

  const themeObserver = new MutationObserver((records) => {
    if (records.some((record) => record.attributeName === "data-theme")) updateTheme();
  });
  themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

  window.addEventListener("battery-rack-flow", (event) => applyRackState(event.detail));
  window.addEventListener("energy-glow-change", (event) => {
    const next = Number(event.detail);
    if (!Number.isFinite(next)) return;
    glowStrength = clamp(next, 0, 1.5);
    if (bloomPass) bloomPass.strength = glowStrength;
    renderOnce(performance.now());
  });
  window.addEventListener("energy-line-glow-change", (event) => {
    lineGlow = Boolean(event.detail);
    applyRouteStyle();
    renderOnce(performance.now());
  });
  window.addEventListener("energy-pulse-speed-change", (event) => {
    const next = Number(event.detail);
    if (!Number.isFinite(next)) return;
    pulseSpeed = clamp(next, PULSE_SPEED_MIN, PULSE_SPEED_MAX);
    renderOnce(performance.now());
    scheduleFrame();
  });
  document.addEventListener("visibilitychange", () => {
    isDocumentVisible = !document.hidden;
    if (!isDocumentVisible && frameRequest) {
      window.cancelAnimationFrame(frameRequest);
      frameRequest = 0;
    }
    scheduleFrame();
  });
  motionQuery.addEventListener?.("change", () => {
    renderOnce(performance.now());
    scheduleFrame();
  });
  stage.addEventListener("pointermove", (event) => {
    if (!finePointerQuery.matches || motionQuery.matches) return;
    const bounds = stage.getBoundingClientRect();
    pointer.set(
      clamp(((event.clientX - bounds.left) / bounds.width) * 2 - 1, -1, 1),
      clamp(-(((event.clientY - bounds.top) / bounds.height) * 2 - 1), -1, 1),
    );
    if (!shouldAnimate()) renderOnce(performance.now());
  }, { passive: true });
  stage.addEventListener("pointerleave", () => {
    pointer.set(0, 0);
    if (!shouldAnimate()) renderOnce(performance.now());
  });
  canvas.addEventListener("webglcontextlost", (event) => {
    event.preventDefault();
    disposed = true;
    composer = null;
    bloomPass = null;
    if (frameRequest) window.cancelAnimationFrame(frameRequest);
    showFallback(section, canvas, new Error("WebGL context lost"));
  });

  canvas.dataset.renderer = "webgl";
  canvas.dataset.camera = "orthographic";
  canvas.dataset.sceneReady = "true";
  canvas.dataset.sceneStyle = "eco-worthy-rack";
  section.dataset.rackRenderMode = "webgl";
  resize();
  updateTheme();
  applyRackState();
  setupPostProcessing();
}

function createRackMaterials() {
  const shared = (material) => {
    material.userData.shared = true;
    return material;
  };
  return {
    chassis: shared(new THREE.MeshStandardMaterial({ color: 0x3c4248, metalness: 0.66, roughness: 0.38 })),
    chassisSide: shared(new THREE.MeshStandardMaterial({ color: 0x2b3036, metalness: 0.6, roughness: 0.46 })),
    face: shared(new THREE.MeshStandardMaterial({ color: 0x1f2429, metalness: 0.5, roughness: 0.34 })),
    faceInset: shared(new THREE.MeshStandardMaterial({ color: 0x101418, metalness: 0.38, roughness: 0.52 })),
    trim: shared(new THREE.MeshStandardMaterial({ color: 0xd8dee3, metalness: 0.8, roughness: 0.24 })),
    screw: shared(new THREE.MeshStandardMaterial({ color: 0x9aa1a8, metalness: 0.86, roughness: 0.3 })),
    terminalPositive: shared(new THREE.MeshStandardMaterial({ color: 0xc23a33, metalness: 0.42, roughness: 0.42 })),
    terminalNegative: shared(new THREE.MeshStandardMaterial({ color: 0x14171a, metalness: 0.42, roughness: 0.46 })),
    port: shared(new THREE.MeshStandardMaterial({ color: 0x0b0d10, metalness: 0.3, roughness: 0.6 })),
    busbar: shared(new THREE.MeshStandardMaterial({ color: 0x8b9298, metalness: 0.82, roughness: 0.28 })),
    flowLine: new THREE.MeshStandardMaterial({
      color: FLOW_COLORS.stale,
      emissive: FLOW_COLORS.stale,
      emissiveIntensity: 0.05,
      metalness: 0.08,
      roughness: 0.28,
      transparent: true,
      opacity: 0.14,
      depthWrite: false,
    }),
    flowGlow: new THREE.MeshBasicMaterial({
      color: FLOW_COLORS.stale,
      transparent: true,
      opacity: 0.02,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    }),
    particle: new THREE.MeshBasicMaterial({
      color: FLOW_COLORS.stale, transparent: true, opacity: 0, depthWrite: false,
    }),
    particleGlow: new THREE.MeshBasicMaterial({
      color: FLOW_COLORS.stale, transparent: true, opacity: 0,
      blending: THREE.AdditiveBlending, depthWrite: false,
    }),
    brand: sharedBrandMaterial(),
  };
}

// The Eco-worthy faceplate label is one texture shared by every module in the stack.
function sharedBrandMaterial() {
  const texture = brandTexture();
  const material = new THREE.MeshBasicMaterial({ map: texture, transparent: true });
  material.userData.shared = true;
  return material;
}

function brandTexture() {
  const canvas = document.createElement("canvas");
  canvas.width = 640;
  canvas.height = 220;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  // Leaf mark, then the wordmark, then the pack's model line.
  ctx.fillStyle = BRAND_GREEN;
  ctx.beginPath();
  ctx.ellipse(38, 62, 26, 15, -Math.PI / 4, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = "#eef2f4";
  ctx.font = "700 64px 'Helvetica Neue', Helvetica, Arial, sans-serif";
  ctx.textBaseline = "middle";
  ctx.fillText("ECO", 78, 62);
  ctx.fillStyle = BRAND_GREEN;
  ctx.fillText("-WORTHY", 200, 62);
  ctx.fillStyle = "rgba(226,232,236,0.68)";
  ctx.font = "600 34px 'Helvetica Neue', Helvetica, Arial, sans-serif";
  ctx.fillText("LiFePO4  48V  100Ah  ·  5.12 kWh", 20, 136);
  ctx.fillStyle = "rgba(226,232,236,0.34)";
  ctx.font = "600 26px 'Helvetica Neue', Helvetica, Arial, sans-serif";
  ctx.fillText("SERVER RACK BATTERY  ·  RS485 / CAN", 20, 182);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 4;
  texture.needsUpdate = true;
  return texture;
}

function rackLayout(count) {
  const total = clamp(Math.round(count) || DEFAULT_MODULES, 1, MAX_MODULES);
  const top = ((total - 1) * MODULE.pitch) / 2;
  return Array.from({ length: total }, (_, index) => top - index * MODULE.pitch);
}

function buildRack(materials, count) {
  const group = new THREE.Group();
  const layout = rackLayout(count);
  const modules = layout.map((y, index) => {
    const module = createBatteryModule(materials, index);
    module.group.position.y = y;
    group.add(module.group);
    return module;
  });
  const network = createRackNetwork(materials, layout);
  const grounding = createGrounding(layout[layout.length - 1] - MODULE.height / 2 - 0.12);
  group.add(network.group, grounding.group);
  return { group, layout, modules, network, puddle: grounding.puddle, bounds: rackBounds(layout) };
}

// World-space box the stack, its bus riser, and the rack output occupy.
function rackBounds(layout) {
  const top = layout[0];
  const bottom = layout[layout.length - 1];
  return new THREE.Box3(
    new THREE.Vector3(-MODULE.width / 2, bottom - MODULE.height / 2 - 0.3, -MODULE.depth / 2),
    new THREE.Vector3(BUS_X + BUS_OUT, top + BUS_HEAD, PORT_Z),
  );
}

// A single 3U Eco-worthy rack pack: chassis, 19-inch faceplate with mounting ears,
// branding, LCD, SOC gauge, status LEDs, comms ports and the DC terminal block.
function createBatteryModule(materials, index) {
  const group = new THREE.Group();

  const body = mesh(new THREE.BoxGeometry(BODY.width, BODY.height, BODY.depth), materials.chassis, true, true);
  group.add(body);
  // Side skins and the ventilated lid read as sheet metal rather than a plain slab.
  [-1, 1].forEach((side) => {
    const skin = mesh(new THREE.BoxGeometry(0.03, BODY.height - 0.08, BODY.depth - 0.12), materials.chassisSide);
    skin.position.set(side * (BODY.width / 2 - 0.005), 0, -0.04);
    group.add(skin);
  });
  for (let slot = 0; slot < 7; slot += 1) {
    const vent = mesh(new THREE.BoxGeometry(BODY.width - 0.6, 0.012, 0.075), materials.faceInset);
    vent.position.set(0, BODY.height / 2 + 0.002, -0.95 + slot * 0.2);
    group.add(vent);
  }

  const face = mesh(new THREE.BoxGeometry(FACE.width, FACE.height, FACE.thickness), materials.face, true);
  face.position.z = FACE_Z;
  group.add(face);

  const front = FACE_FRONT;
  const place = (object, x, y, z = front) => {
    object.position.set(x, y, z);
    group.add(object);
    return object;
  };

  // Rack ears with mounting screws.
  [-1, 1].forEach((side) => {
    [0.34, -0.34].forEach((y) => {
      const screw = mesh(new THREE.CylinderGeometry(0.038, 0.038, 0.035, 12), materials.screw);
      screw.rotation.x = Math.PI / 2;
      place(screw, side * 1.66, y, front + 0.01);
    });
    const earSeam = mesh(new THREE.BoxGeometry(0.02, FACE.height - 0.06, 0.012), materials.faceInset);
    place(earSeam, side * 1.52, 0, front + 0.006);
  });

  // Recessed grab handle on the left of the faceplate.
  const handleWell = mesh(new THREE.BoxGeometry(0.42, 0.34, 0.03), materials.faceInset);
  place(handleWell, -1.28, 0, front + 0.004);
  const handleBar = mesh(new THREE.BoxGeometry(0.36, 0.06, 0.05), materials.trim);
  place(handleBar, -1.28, -0.1, front + 0.03);

  // Branding plate.
  const brand = new THREE.Mesh(new THREE.PlaneGeometry(1.24, 0.43), materials.brand);
  place(brand, -0.42, 0.11, front + 0.006);

  // Ventilation slits below the branding.
  for (let slit = 0; slit < 9; slit += 1) {
    const vent = mesh(new THREE.BoxGeometry(0.018, 0.16, 0.014), materials.faceInset);
    place(vent, -0.94 + slit * 0.055, -0.3, front + 0.005);
  }

  // LCD readout.
  const screenWell = mesh(new THREE.BoxGeometry(0.76, 0.4, 0.035), materials.faceInset);
  place(screenWell, 0.42, 0.15, front + 0.004);
  const { texture: screenTexture, context: screenContext } = screenSurface();
  const screenMaterial = new THREE.MeshBasicMaterial({ map: screenTexture });
  screenMaterial.userData.ownTexture = true;
  const screen = new THREE.Mesh(new THREE.PlaneGeometry(0.7, 0.34), screenMaterial);
  place(screen, 0.42, 0.15, front + 0.024);

  // Six-cell SOC gauge under the screen.
  const socLedMaterials = [];
  for (let led = 0; led < SOC_LEDS; led += 1) {
    const material = createSignalMaterial(FLOW_COLORS.stale);
    const cell = mesh(new THREE.BoxGeometry(0.085, 0.07, 0.03), material);
    place(cell, 0.115 + led * 0.11, -0.25, front + 0.008);
    socLedMaterials.push(material);
  }

  // RUN / ALM indicators and the power button.
  const runMaterial = createSignalMaterial(0x2b3034);
  const alarmMaterial = createSignalMaterial(0x35292b);
  const runLed = mesh(new THREE.SphereGeometry(0.035, 12, 8), runMaterial);
  place(runLed, 0.9, -0.1, front + 0.012);
  const alarmLed = mesh(new THREE.SphereGeometry(0.035, 12, 8), alarmMaterial);
  place(alarmLed, 1.0, -0.1, front + 0.012);
  const button = mesh(new THREE.CylinderGeometry(0.055, 0.055, 0.05, 16), materials.trim);
  button.rotation.x = Math.PI / 2;
  place(button, 0.95, 0.15, front + 0.02);

  // RS485 / CAN port bank and the DIP address switch.
  [0, 1, 2].forEach((port) => {
    const socket = mesh(new THREE.BoxGeometry(0.1, 0.12, 0.05), materials.port);
    place(socket, 1.08 + port * 0.115, -0.3, front + 0.008);
  });
  const dip = mesh(new THREE.BoxGeometry(0.28, 0.1, 0.035), materials.trim);
  place(dip, 1.16, 0.28, front + 0.006);
  for (let pin = 0; pin < 4; pin += 1) {
    const toggle = mesh(new THREE.BoxGeometry(0.03, 0.05, 0.02), materials.faceInset);
    place(toggle, 1.07 + pin * 0.06, 0.29, front + 0.024);
  }

  // DC terminal block: the flow conduit leaves the rack from here.
  const terminals = [
    [0.22, materials.terminalPositive],
    [-0.22, materials.terminalNegative],
  ].map(([y, material]) => {
    const post = mesh(new THREE.CylinderGeometry(0.085, 0.095, 0.12, 14), material, true);
    post.rotation.x = Math.PI / 2;
    return place(post, TERMINAL_X, y, front + 0.06);
  });
  const terminalGuard = mesh(new THREE.BoxGeometry(0.28, 0.62, 0.03), materials.faceInset);
  place(terminalGuard, TERMINAL_X, 0, front + 0.004);
  const portMaterial = createSignalMaterial(FLOW_COLORS.stale);
  const portLight = mesh(new THREE.BoxGeometry(0.1, 0.08, 0.05), portMaterial);
  place(portLight, TERMINAL_X, 0, front + 0.03);

  // Flow stripe down the left edge, mirroring the home scene's device stripes.
  const stripeMaterial = createSignalMaterial(FLOW_COLORS.stale);
  const stripe = mesh(new THREE.BoxGeometry(0.05, FACE.height - 0.18, 0.05), stripeMaterial);
  place(stripe, -1.66, 0, front + 0.004);

  return {
    group,
    index,
    body,
    face,
    terminals,
    socLedMaterials,
    runMaterial,
    alarmMaterial,
    portMaterial,
    stripeMaterial,
    screenTexture,
    screenContext,
    screenSignature: "",
    litLeds: 0,
    mode: "stale",
    reporting: false,
  };
}

function screenSurface() {
  const canvas = document.createElement("canvas");
  canvas.width = 320;
  canvas.height = 156;
  const context = canvas.getContext("2d");
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 4;
  return { texture, context };
}

// Repaint a module's LCD only when its readout actually changes.
function drawModuleScreen(module, pack, reporting, mode) {
  const context = module.screenContext;
  if (!context) return;
  const soc = reporting ? optionalFinite(pack?.soc) : null;
  const voltage = reporting ? optionalFinite(pack?.voltage) : null;
  const current = reporting ? optionalFinite(pack?.current) : null;
  const signature = `${reporting}|${mode}|${soc}|${voltage}|${current}`;
  if (signature === module.screenSignature) return;
  module.screenSignature = signature;

  const { width, height } = context.canvas;
  const accent = LCD_COLORS[mode] || LCD_COLORS.stale;
  context.clearRect(0, 0, width, height);
  context.fillStyle = reporting ? "#080b0d" : "#070809";
  context.fillRect(0, 0, width, height);
  context.strokeStyle = "rgba(255,255,255,0.08)";
  context.lineWidth = 4;
  context.strokeRect(2, 2, width - 4, height - 4);

  context.textBaseline = "middle";
  context.fillStyle = accent;
  context.font = "700 72px 'Helvetica Neue', Helvetica, Arial, sans-serif";
  const socText = soc === null ? "--" : String(Math.round(soc));
  context.fillText(socText, 18, 56);
  const socWidth = context.measureText(socText).width;
  context.font = "700 30px 'Helvetica Neue', Helvetica, Arial, sans-serif";
  context.fillText("%", 24 + socWidth, 74);

  context.fillStyle = "rgba(226,232,236,0.82)";
  context.font = "600 30px 'Helvetica Neue', Helvetica, Arial, sans-serif";
  context.fillText(voltage === null ? "--.- V" : `${voltage.toFixed(1)} V`, 170, 44);
  context.fillText(current === null ? "--.- A" : `${Math.abs(current).toFixed(1)} A`, 170, 84);

  const badge = reporting ? MODE_BADGES[mode] || "--" : "OFFLINE";
  context.fillStyle = accent;
  context.globalAlpha = 0.18;
  context.fillRect(16, 106, width - 32, 34);
  context.globalAlpha = 1;
  context.fillStyle = accent;
  context.font = "700 26px 'Helvetica Neue', Helvetica, Arial, sans-serif";
  context.fillText(badge, 28, 124);
  module.screenTexture.needsUpdate = true;
}

const MODE_BADGES = {
  charging: "CHARGING",
  discharging: "DISCHARGING",
  idle: "STANDBY",
  stale: "NO DATA",
};

// Each pack taps the rack bus riser through its terminal block; the riser carries the
// combined rack flow out of the frame. Every segment is single-axis, like the home scene.
function createRackNetwork(materials, layout) {
  const group = new THREE.Group();
  const top = layout[0];
  const bottom = layout[layout.length - 1];

  const taps = layout.map((y, index) => createFlowRoute(
    createStraightPath([
      new THREE.Vector3(TERMINAL_X, y, PORT_Z),
      new THREE.Vector3(BUS_X, y, PORT_Z),
    ]),
    materials,
    1,
    (index * 0.37) % 1,
    0.026,
  ));

  const trunk = createFlowRoute(
    createStraightPath([
      new THREE.Vector3(BUS_X, bottom - BUS_FOOT, PORT_Z),
      new THREE.Vector3(BUS_X, top + BUS_HEAD, PORT_Z),
      new THREE.Vector3(BUS_X + BUS_OUT, top + BUS_HEAD, PORT_Z),
    ]),
    materials,
    1,
    0.11,
    0.038,
  );

  // Copper riser behind the conduit so the bus reads as hardware, not just a line.
  const riser = mesh(
    new THREE.BoxGeometry(0.075, (top - bottom) + BUS_FOOT + BUS_HEAD, 0.04),
    materials.busbar,
    true,
  );
  riser.position.set(BUS_X, (top + BUS_HEAD + bottom - BUS_FOOT) / 2, PORT_Z - 0.07);
  group.add(riser);
  layout.forEach((y) => {
    const lug = mesh(new THREE.BoxGeometry(0.14, 0.1, 0.05), materials.busbar);
    lug.position.set(BUS_X, y, PORT_Z - 0.05);
    group.add(lug);
  });

  const routes = taps.concat(trunk);
  routes.forEach((route) => group.add(route.group));
  return { group, taps, trunk, routes };
}

function createStraightPath(points) {
  const path = new THREE.CurvePath();
  for (let index = 1; index < points.length; index += 1) {
    path.add(new THREE.LineCurve3(points[index - 1], points[index]));
  }
  return path;
}

function pulseProgressRate(route, pulseSpeed) {
  return (pulseSpeed * PULSE_REFERENCE_LENGTH) / route.length;
}

function createFlowRoute(curve, materials, particleCount, phaseOffset, radius = 0.027) {
  const group = new THREE.Group();
  const lineMaterial = materials.flowLine.clone();
  const glowMaterial = materials.flowGlow.clone();
  const particleMaterial = materials.particle.clone();
  const particleGlowMaterial = materials.particleGlow.clone();
  const line = mesh(new THREE.TubeGeometry(curve, 64, radius, 6, false), lineMaterial);
  const glow = mesh(new THREE.TubeGeometry(curve, 64, radius * 2.7, 8, false), glowMaterial);
  group.add(glow, line);

  const coreGeometry = new THREE.SphereGeometry(0.075, 16, 12);
  const glowGeometry = new THREE.SphereGeometry(0.112, 16, 12);
  const particles = Array.from({ length: particleCount }, () => {
    const particle = new THREE.Group();
    const halo = mesh(glowGeometry, particleGlowMaterial);
    const core = mesh(coreGeometry, particleMaterial);
    halo.scale.setScalar(0.85);
    core.scale.setScalar(0.75);
    particle.add(halo, core);
    particle.visible = false;
    group.add(particle);
    return particle;
  });

  return {
    group,
    curve,
    length: Math.max(curve.getLength(), 0.001),
    particles,
    lineMaterial,
    glowMaterial,
    particleMaterial,
    particleGlowMaterial,
    phaseOffset,
    forwardAxis: new THREE.Vector3(0, 0, 1),
    mode: "stale",
    magnitude: 0,
    reporting: false,
    active: false,
    direction: 1,
  };
}

function configureRoute(route, mode, magnitude, active, direction, reporting, activeColor = null) {
  route.mode = reporting ? validMode(mode) : "stale";
  route.magnitude = Math.max(0, finite(magnitude));
  route.reporting = Boolean(reporting);
  route.active = Boolean(active) && route.reporting && isActiveRouteMode(route.mode);
  route.direction = direction < 0 ? -1 : 1;
  const color = route.active ? activeColor ?? FLOW_COLORS[route.mode] : FLOW_COLORS.stale;
  route.lineMaterial.color.setHex(color);
  route.lineMaterial.emissive.setHex(color);
  route.glowMaterial.color.setHex(color);
  route.particleMaterial.color.setHex(color);
  route.particleGlowMaterial.color.setHex(color);
}

function styleRouteGlow(route, lineGlow, activeOpacity) {
  route.lineMaterial.opacity = route.active
    ? activeOpacity
    : route.reporting ? 0.18 : 0.11;
  route.lineMaterial.emissiveIntensity = route.active && lineGlow ? 0.7 : 0.04;
  route.glowMaterial.opacity = lineGlow ? (route.active ? ACTIVE_GLOW_OPACITY : 0.01) : 0;
}

// Soft contact shadow under the stack plus an additive puddle that catches the
// conduit light while power is moving, exactly like the home scene's grounding.
function createGrounding(baseY) {
  const group = new THREE.Group();
  const addPlane = (width, depth, y, material) => {
    const plane = mesh(new THREE.PlaneGeometry(width, depth), material);
    plane.rotation.x = -Math.PI / 2;
    plane.position.set(0.35, y, 0.1);
    plane.renderOrder = -1;
    group.add(plane);
    return plane;
  };
  addPlane(7.2, 5.1, baseY, new THREE.MeshBasicMaterial({
    map: radialGradientTexture([
      [0, "rgba(0,0,0,0.55)"],
      [0.58, "rgba(0,0,0,0.22)"],
      [1, "rgba(0,0,0,0)"],
    ]),
    transparent: true,
    depthWrite: false,
    opacity: 0.92,
  }));
  const glowMaterial = new THREE.MeshBasicMaterial({
    map: radialGradientTexture([
      [0, "rgba(255,255,255,0.95)"],
      [0.45, "rgba(255,255,255,0.4)"],
      [1, "rgba(255,255,255,0)"],
    ]),
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    opacity: 0,
  });
  addPlane(5.6, 3.9, baseY + 0.012, glowMaterial);
  return { group, puddle: { material: glowMaterial, intensity: 0.58 } };
}

function radialGradientTexture(stops) {
  const size = 128;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  const gradient = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  stops.forEach(([offset, color]) => gradient.addColorStop(offset, color));
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, size, size);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.needsUpdate = true;
  return texture;
}

function updatePuddle(puddle, active, colorHex, time, phase) {
  if (!puddle) return;
  puddle.material.color.setHex(colorHex);
  puddle.material.opacity = active
    ? puddle.intensity * (0.72 + Math.sin(time * 0.0038 + phase) * 0.22)
    : 0;
}

function createSignalMaterial(color) {
  return new THREE.MeshStandardMaterial({
    color,
    emissive: color,
    emissiveIntensity: 0.28,
    metalness: 0.08,
    roughness: 0.22,
  });
}

function setSignal(material, color, active) {
  material.color.setHex(color);
  material.emissive.setHex(color);
  material.emissiveIntensity = active ? 1.4 : 0.22;
}

function pulseSignal(material, active, time, phase) {
  material.emissiveIntensity = active
    ? 1.2 + Math.sin(time * 0.004 + phase) * 0.36
    : 0.22;
}

function isRouteActive(route) {
  return Boolean(route?.active && route.reporting && isActiveRouteMode(route.mode));
}

function isActiveRouteMode(mode) {
  return mode === "charging" || mode === "discharging";
}

function normalizeRackPacks(value) {
  let packs = value;
  if (typeof value === "string") {
    try {
      packs = JSON.parse(value);
    } catch {
      packs = [];
    }
  }
  if (!Array.isArray(packs)) return [];
  return packs.slice(0, MAX_MODULES).map((pack) => ({
    id: String(pack?.id || ""),
    mode: validMode(pack?.mode),
    soc: optionalFinite(pack?.soc),
    power: optionalFinite(pack?.power),
    current: optionalFinite(pack?.current),
    voltage: optionalFinite(pack?.voltage),
    alarm: Boolean(pack?.alarm),
    reporting: Boolean(pack?.reporting),
  }));
}

// Free a retired stack's GPU resources, leaving the materials shared by every rack
// (chassis, faceplate, branding) alive for the replacement.
function disposeObject(object) {
  object.traverse((child) => {
    if (child.geometry) child.geometry.dispose();
    const list = Array.isArray(child.material)
      ? child.material
      : child.material ? [child.material] : [];
    list.forEach((material) => {
      if (material.userData?.shared) return;
      if (material.userData?.ownTexture && material.map) material.map.dispose();
      material.dispose();
    });
  });
}

function mesh(geometry, material, castShadow = false, receiveShadow = false) {
  const object = new THREE.Mesh(geometry, material);
  object.castShadow = castShadow;
  object.receiveShadow = receiveShadow;
  return object;
}

function showFallback(section, canvas, error) {
  section.classList.add("is-rack-fallback");
  section.dataset.rackRenderMode = "fallback";
  canvas.hidden = true;
  canvas.dataset.sceneReady = "false";
  if (error) console.warn("Rack-flow WebGL scene unavailable; using the CSS fallback.", error);
}

function optionalFinite(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function finite(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

function routeMagnitude(power) {
  return Math.abs(finite(power)) / 250;
}

function clamp(value, minimum, maximum) {
  return Math.min(maximum, Math.max(minimum, value));
}

function wrap01(value) {
  return ((value % 1) + 1) % 1;
}

function validMode(value) {
  return Object.hasOwn(FLOW_COLORS, value) ? value : "stale";
}

try {
  startRackFlowScene();
} catch (error) {
  const section = document.getElementById("rackSummarySection");
  const canvas = document.getElementById("rackFlowCanvas");
  if (section && canvas) {
    canvas.dataset.sceneError = error instanceof Error ? error.message : String(error);
    showFallback(section, canvas, error);
  }
}
