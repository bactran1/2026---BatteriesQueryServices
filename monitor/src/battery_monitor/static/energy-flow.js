import * as THREE from "three";

const FLOW_COLORS = {
  charging: 0xd9ff3f,
  discharging: 0xff6258,
  idle: 0xff9f0a,
  stale: 0x777b82,
};

const NODE_COLORS = {
  grid: 0x72d7ff,
  inverter: 0xffa31a,
  load: 0xffdf87,
  solar: 0xf2ef50,
};

const CAMERA_POSITION = new THREE.Vector3(7.8, 6.4, 9.6);
const CAMERA_LOOK_AT = new THREE.Vector3(0, -0.05, 0);

function startEnergyFlowScene() {
  const section = document.getElementById("energyFlowSection");
  const stage = document.getElementById("energyFlowStage");
  const canvas = document.getElementById("energyFlowCanvas");
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
  renderer.toneMappingExposure = 1.08;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFShadowMap;

  const scene = new THREE.Scene();
  const camera = new THREE.OrthographicCamera(-5, 5, 3, -3, 0.1, 50);
  camera.position.copy(CAMERA_POSITION);
  camera.lookAt(CAMERA_LOOK_AT);

  const root = new THREE.Group();
  root.position.y = -0.2;
  scene.add(root);

  const materials = createMaterials();
  const energySystem = createRenogySystem(materials);
  const network = createFlowNetwork(materials);
  root.add(energySystem.group, network.group);

  const ground = mesh(new THREE.PlaneGeometry(11, 7.4), materials.ground, false, true);
  ground.position.set(0, -1.3, 0.2);
  ground.rotation.x = -Math.PI / 2;
  root.add(ground);

  const ambient = new THREE.HemisphereLight(0xf4f7ff, 0x111215, 1.75);
  const keyLight = new THREE.DirectionalLight(0xffffff, 3.8);
  keyLight.position.set(-4.5, 7.2, 6.8);
  keyLight.castShadow = true;
  keyLight.shadow.mapSize.set(1024, 1024);
  keyLight.shadow.camera.left = -6;
  keyLight.shadow.camera.right = 6;
  keyLight.shadow.camera.top = 5;
  keyLight.shadow.camera.bottom = -5;
  keyLight.shadow.bias = -0.0004;
  const rimLight = new THREE.DirectionalLight(0xf2ef50, 1.4);
  rimLight.position.set(5.5, 3.2, -4.5);
  const fillLight = new THREE.DirectionalLight(0xb9c8ff, 1.35);
  fillLight.position.set(3.5, 2.8, 7.5);
  const homeGlow = new THREE.PointLight(0xffe5a7, 2.2, 4.5, 2);
  homeGlow.position.set(-1.45, -0.25, 2.5);
  scene.add(ambient, keyLight, rimLight, fillLight, homeGlow);

  const flowState = {
    mode: "stale",
    current: 0,
    power: 0,
    soc: 0,
    batteryCount: 0,
    packs: [],
    inverterAvailable: false,
    gridPower: 0,
    solarPower: 0,
    loadPower: 0,
    batteryPower: 0,
  };
  const motionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
  const finePointerQuery = window.matchMedia("(hover: hover) and (pointer: fine)");
  const pointer = new THREE.Vector2();
  const parallax = new THREE.Vector2();
  let frameRequest = 0;
  let frameCount = 0;
  let needsPixelAudit = true;
  let isIntersecting = true;
  let isDocumentVisible = !document.hidden;
  let disposed = false;

  function readSectionState(detail = {}) {
    return {
      mode: validMode(detail.mode ?? section.dataset.mode),
      current: finite(detail.current ?? section.dataset.current),
      power: finite(detail.power ?? section.dataset.power),
      soc: clamp(finite(detail.soc ?? section.dataset.soc), 0, 100),
      batteryCount: Math.max(0, Math.round(finite(detail.batteryCount ?? section.dataset.batteryCount))),
      packs: normalizePackTelemetry(detail.packs ?? section.dataset.packTelemetry),
      inverterAvailable: booleanValue(detail.inverterAvailable ?? section.dataset.inverterAvailable),
      gridPower: finite(detail.gridPower ?? section.dataset.gridPower),
      solarPower: finite(detail.solarPower ?? section.dataset.solarPower),
      loadPower: finite(detail.loadPower ?? section.dataset.loadPower),
      batteryPower: finite(detail.batteryPower ?? section.dataset.batteryPower),
    };
  }

  function applyFlowState(detail = {}) {
    Object.assign(flowState, readSectionState(detail));
    const flowColor = FLOW_COLORS[flowState.mode];
    const rackMagnitude = Math.max(Math.abs(flowState.current), Math.abs(flowState.power) / 54);
    const live = flowState.mode !== "stale" && flowState.batteryCount > 0;
    const charging = flowState.mode === "charging";
    const discharging = flowState.mode === "discharging";
    const inverterMetered = flowState.inverterAvailable;
    const gridActive = inverterMetered && Math.abs(flowState.gridPower) > 25;
    const solarActive = inverterMetered && flowState.solarPower > 25;
    const loadActive = inverterMetered && flowState.loadPower > 25;
    const batteryActive = live
      && (Math.abs(flowState.batteryPower) > 25 || charging || discharging);

    if (inverterMetered) {
      configureRoute(
        network.grid,
        flowState.gridPower >= 0 ? "charging" : "discharging",
        routeMagnitude(flowState.gridPower),
        gridActive,
        flowState.gridPower >= 0 ? 1 : -1,
        true,
        NODE_COLORS.grid,
      );
      configureRoute(
        network.solar,
        "charging",
        routeMagnitude(flowState.solarPower),
        solarActive,
        1,
        true,
        NODE_COLORS.solar,
      );
      configureRoute(
        network.load,
        "charging",
        routeMagnitude(flowState.loadPower),
        loadActive,
        1,
        true,
        NODE_COLORS.load,
      );
      configureRoute(
        network.battery,
        flowState.batteryPower >= 0 ? "charging" : "discharging",
        routeMagnitude(flowState.batteryPower),
        batteryActive,
        flowState.batteryPower >= 0 ? 1 : -1,
        true,
        flowState.batteryPower >= 0 ? FLOW_COLORS.charging : FLOW_COLORS.discharging,
      );
    } else {
      configureRoute(network.grid, "stale", 0, false, 1, false);
      configureRoute(network.battery, flowState.mode, rackMagnitude, batteryActive, charging ? 1 : -1, live);
      configureRoute(network.load, "stale", 0, false, 1, false);
      configureRoute(network.solar, "stale", 0, false, 1, false);
    }

    const systemActive = network.routes.some(isRouteActive);
    setSignal(energySystem.gridSignalMaterial, NODE_COLORS.grid, network.grid.active);
    setSignal(energySystem.inverterSignalMaterial, systemActive ? flowColor : NODE_COLORS.inverter, systemActive);
    setSignal(energySystem.batterySignalMaterial, network.battery.active ? flowColor : FLOW_COLORS.stale, network.battery.active);
    setSignal(energySystem.loadSignalMaterial, NODE_COLORS.load, network.load.active);
    setSignal(energySystem.solarSignalMaterial, NODE_COLORS.solar, network.solar.active);

    energySystem.batteryModules.forEach((module, index) => {
      const pack = flowState.packs[index];
      const reporting = pack ? pack.reporting : index < flowState.batteryCount;
      const packMode = reporting ? validMode(pack?.mode ?? flowState.mode) : "stale";
      const packColor = FLOW_COLORS[packMode];
      const normalizedSoc = clamp(pack?.soc ?? flowState.soc, 0, 100) / 100;
      module.fill.scale.x = Math.max(0.03, normalizedSoc);
      module.fill.position.x = -0.235 + (0.51 * module.fill.scale.x) / 2;
      module.fillMaterial.color.setHex(packColor);
      module.fillMaterial.opacity = reporting ? 0.96 : 0.22;
      module.signalMaterial.color.setHex(packColor);
      module.signalMaterial.emissive.setHex(packColor);
      module.signalMaterial.emissiveIntensity = reporting && isActiveMode(packMode) ? 1.35 : 0.16;
    });

    canvas.dataset.energyDirection = inverterMetered
      ? "metered-routes"
      : charging
        ? "inverter-to-battery"
        : discharging
          ? "battery-to-inverter"
          : "paused";
    canvas.dataset.energyMode = flowState.mode;
    canvas.dataset.activeRoutes = String(network.routes.filter(isRouteActive).length);
    canvas.dataset.sourceTelemetry = inverterMetered
      ? "inverter-and-direct-battery"
      : "direct-battery-only";
    canvas.dataset.topology = "home-grid-solar-inverter-battery-load";
    canvas.dataset.sceneStyle = "isometric-home-energy";
    if (disposed) return;
    renderOnce(performance.now());
    scheduleFrame();
  }

  function isActiveMode(mode = flowState.mode) {
    return mode === "charging" || mode === "discharging";
  }

  function shouldAnimate() {
    return !disposed
      && !motionQuery.matches
      && isIntersecting
      && isDocumentVisible
      && network.routes.some(isRouteActive);
  }

  function updateParticles(time) {
    const tangent = new THREE.Vector3();
    const position = new THREE.Vector3();

    network.routes.forEach((route) => {
      const active = isRouteActive(route);
      const activeCount = active ? 1 : 0;
      const speed = clamp(0.1 + route.magnitude * 0.009, 0.1, 0.34);

      route.particles.forEach((particle, index) => {
        particle.visible = index < activeCount;
        if (!particle.visible) return;
        const phase = index / activeCount + route.phaseOffset;
        const progress = wrap01(phase + route.direction * time * 0.001 * speed);
        route.curve.getPointAt(progress, position);
        route.curve.getTangentAt(progress, tangent).multiplyScalar(route.direction).normalize();
        particle.position.copy(position);
        particle.quaternion.setFromUnitVectors(route.forwardAxis, tangent);
        const endpointFade = clamp(Math.sin(Math.PI * progress) * 1.6, 0.35, 1);
        particle.scale.setScalar(endpointFade);
      });

      route.particleMaterial.opacity = active ? 0.96 : 0;
      route.particleGlowMaterial.opacity = active ? 0.14 : 0;
    });

    pulseSignal(energySystem.gridSignalMaterial, network.grid.active, time, 0);
    pulseSignal(energySystem.inverterSignalMaterial, network.routes.some(isRouteActive), time, 0.7);
    pulseSignal(energySystem.batterySignalMaterial, network.battery.active, time, 1.15);
    pulseSignal(energySystem.loadSignalMaterial, network.load.active, time, 1.7);
    pulseSignal(energySystem.solarSignalMaterial, network.solar.active, time, 2.1);
    energySystem.windowMaterial.emissiveIntensity = network.load.active
      ? 1.2 + Math.sin(time * 0.0034) * 0.18
      : 0.62;
    homeGlow.intensity = network.load.active
      ? 2.7 + Math.sin(time * 0.0034) * 0.35
      : 1.65;
    energySystem.batteryModules.forEach((module, index) => {
      const pack = flowState.packs[index];
      const reporting = pack ? pack.reporting : index < flowState.batteryCount;
      if (reporting && isActiveMode(pack?.mode ?? flowState.mode)) {
        module.signalMaterial.emissiveIntensity = 1.1 + Math.sin(time * 0.004 + index * 0.85) * 0.38;
      }
    });
  }

  function renderOnce(time) {
    if (disposed) return;
    updateParticles(time);
    parallax.x += (pointer.x - parallax.x) * 0.05;
    parallax.y += (pointer.y - parallax.y) * 0.05;
    camera.position.set(
      CAMERA_POSITION.x + parallax.x * 0.34,
      CAMERA_POSITION.y + parallax.y * 0.2,
      CAMERA_POSITION.z - parallax.x * 0.16,
    );
    camera.lookAt(
      CAMERA_LOOK_AT.x + parallax.x * 0.12,
      CAMERA_LOOK_AT.y + parallax.y * 0.06,
      CAMERA_LOOK_AT.z,
    );
    root.rotation.y = parallax.x * 0.025;
    renderer.render(scene, camera);
    frameCount += 1;
    if (frameCount === 1 || frameCount % 10 === 0) canvas.dataset.frame = String(frameCount);
    if (needsPixelAudit) auditCanvasPixels();
  }

  function auditCanvasPixels() {
    needsPixelAudit = false;
    try {
      const gl = renderer.getContext();
      const width = gl.drawingBufferWidth;
      const height = gl.drawingBufferHeight;
      const pixels = new Uint8Array(width * height * 4);
      gl.readPixels(0, 0, width, height, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
      let sampled = 0;
      let visible = 0;
      for (let index = 0; index < pixels.length; index += 64) {
        sampled += 1;
        if (pixels[index + 3] > 8 && pixels[index] + pixels[index + 1] + pixels[index + 2] > 18) {
          visible += 1;
        }
      }
      canvas.dataset.pixelCoverage = sampled ? (visible / sampled).toFixed(4) : "0";
      canvas.dataset.pixelCheck = visible >= 24 ? "nonblank" : "blank";
    } catch {
      canvas.dataset.pixelCheck = "unavailable";
    }
  }

  function animate(time) {
    frameRequest = 0;
    renderOnce(time);
    scheduleFrame();
  }

  function scheduleFrame() {
    if (!frameRequest && shouldAnimate()) frameRequest = window.requestAnimationFrame(animate);
  }

  function resize() {
    if (disposed) return;
    const bounds = stage.getBoundingClientRect();
    const width = Math.max(1, Math.round(bounds.width));
    const height = Math.max(1, Math.round(bounds.height));
    const aspect = width / height;
    const viewWidth = width <= 480 ? 8.25 : width <= 760 ? 9.6 : 12.4;
    const viewHeight = viewWidth / aspect;
    camera.left = -viewWidth / 2;
    camera.right = viewWidth / 2;
    camera.top = viewHeight / 2;
    camera.bottom = -viewHeight / 2;
    root.position.set(width <= 480 ? -0.12 : -0.05, width <= 480 ? -0.58 : -0.25, 0);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, width <= 600 ? 1.5 : 2));
    renderer.setSize(width, height, false);
    renderer.shadowMap.enabled = width > 480;
    camera.updateProjectionMatrix();
    needsPixelAudit = true;
    renderOnce(performance.now());
  }

  function updateTheme() {
    const dark = document.documentElement.dataset.theme === "dark";
    const palette = dark
      ? {
          wall: 0x292b2f,
          wallSide: 0x202226,
          roof: 0x45484e,
          roofEdge: 0x5c5f66,
          device: 0x3a3d42,
          deviceFace: 0x17181b,
          utility: 0x676b72,
          ground: 0x101113,
        }
      : {
          wall: 0x35373b,
          wallSide: 0x292b2f,
          roof: 0x55585f,
          roofEdge: 0x73767d,
          device: 0x4a4d53,
          deviceFace: 0x202226,
          utility: 0x7a7e85,
          ground: 0x151618,
        };
    materials.wall.color.setHex(palette.wall);
    materials.wallSide.color.setHex(palette.wallSide);
    materials.roof.color.setHex(palette.roof);
    materials.roofEdge.color.setHex(palette.roofEdge);
    materials.device.color.setHex(palette.device);
    materials.deviceFace.color.setHex(palette.deviceFace);
    materials.utility.color.setHex(palette.utility);
    materials.ground.color.setHex(palette.ground);
    ambient.intensity = dark ? 1.85 : 2.05;
    keyLight.intensity = dark ? 3.9 : 4.2;
    rimLight.intensity = dark ? 1.7 : 1.25;
    fillLight.intensity = dark ? 1.65 : 1.5;
    renderer.toneMappingExposure = dark ? 1.12 : 1.08;
    needsPixelAudit = true;
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

  window.addEventListener("battery-energy-flow", (event) => applyFlowState(event.detail));
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
    if (frameRequest) window.cancelAnimationFrame(frameRequest);
    showFallback(section, canvas, new Error("WebGL context lost"));
  });

  canvas.dataset.renderer = "webgl";
  canvas.dataset.camera = "orthographic";
  canvas.dataset.sceneReady = "true";
  section.dataset.renderMode = "webgl";
  resize();
  updateTheme();
  applyFlowState();
}

function createMaterials() {
  return {
    wall: new THREE.MeshStandardMaterial({ color: 0x35373b, metalness: 0.08, roughness: 0.72 }),
    wallSide: new THREE.MeshStandardMaterial({ color: 0x292b2f, metalness: 0.12, roughness: 0.78 }),
    roof: new THREE.MeshStandardMaterial({ color: 0x55585f, metalness: 0.32, roughness: 0.48 }),
    roofEdge: new THREE.MeshStandardMaterial({ color: 0x73767d, metalness: 0.58, roughness: 0.36 }),
    panelFrame: new THREE.MeshStandardMaterial({ color: 0xa4a7ad, metalness: 0.82, roughness: 0.24 }),
    panel: new THREE.MeshStandardMaterial({ color: 0x343a46, metalness: 0.58, roughness: 0.3 }),
    panelGrid: new THREE.MeshStandardMaterial({ color: 0x6f747d, metalness: 0.68, roughness: 0.28 }),
    device: new THREE.MeshStandardMaterial({ color: 0x4a4d53, metalness: 0.56, roughness: 0.36 }),
    deviceFace: new THREE.MeshStandardMaterial({ color: 0x202226, metalness: 0.42, roughness: 0.34 }),
    trim: new THREE.MeshStandardMaterial({ color: 0xe8e9eb, metalness: 0.72, roughness: 0.26 }),
    utility: new THREE.MeshStandardMaterial({ color: 0x7a7e85, metalness: 0.7, roughness: 0.34 }),
    cable: new THREE.MeshStandardMaterial({ color: 0x3b3e43, metalness: 0.65, roughness: 0.5 }),
    ground: new THREE.MeshStandardMaterial({
      color: 0x151618,
      metalness: 0.04,
      roughness: 0.9,
      transparent: true,
      opacity: 0.84,
    }),
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
      color: FLOW_COLORS.stale,
      transparent: true,
      opacity: 0,
      depthWrite: false,
    }),
    particleGlow: new THREE.MeshBasicMaterial({
      color: FLOW_COLORS.stale,
      transparent: true,
      opacity: 0,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    }),
  };
}

function createRenogySystem(materials) {
  const group = new THREE.Group();
  const house = createHouseShell(materials);
  const solar = createSolarArray(materials);
  const powerCenter = createPowerCenter(materials);
  const utility = createUtilityPole(materials);
  group.add(house.group, solar.group, powerCenter.group, utility.group);

  const serviceCable = createTubePath([
    new THREE.Vector3(3.85, 1.1, 0.2),
    new THREE.Vector3(3.25, 0.75, 0.8),
    new THREE.Vector3(2.55, 0.15, 1.68),
    new THREE.Vector3(0.78, 0.1, 1.78),
  ], materials.cable, 0.022);
  group.add(serviceCable);

  return {
    group,
    batteryModules: powerCenter.batteryModules,
    batterySignalMaterial: powerCenter.batterySignalMaterial,
    gridSignalMaterial: utility.signalMaterial,
    inverterSignalMaterial: powerCenter.inverterSignalMaterial,
    loadSignalMaterial: house.loadSignalMaterial,
    solarSignalMaterial: solar.signalMaterial,
    windowMaterial: house.windowMaterial,
  };
}

function createHouseShell(materials) {
  const group = new THREE.Group();
  const body = mesh(new THREE.BoxGeometry(5.05, 2.15, 3.15), materials.wall, true, true);
  body.position.set(-0.55, -0.17, 0);
  const sideWing = mesh(new THREE.BoxGeometry(1.45, 1.7, 2.65), materials.wallSide, true, true);
  sideWing.position.set(-3.05, -0.39, 0.15);
  const roof = mesh(new THREE.BoxGeometry(5.75, 0.18, 3.78), materials.roof, true, true);
  roof.position.set(-0.55, 1.12, -0.02);
  roof.rotation.x = 0.16;
  const roofEdge = mesh(new THREE.BoxGeometry(5.9, 0.07, 3.9), materials.roofEdge, true, true);
  roofEdge.position.set(-0.55, 1.04, -0.02);
  roofEdge.rotation.x = 0.16;
  group.add(body, sideWing, roofEdge, roof);

  const windowMaterial = new THREE.MeshStandardMaterial({
    color: 0xfff8de,
    emissive: 0xffe4a0,
    emissiveIntensity: 0.62,
    metalness: 0.02,
    roughness: 0.16,
  });
  const windowFrame = mesh(new THREE.BoxGeometry(1.78, 1.4, 0.12), materials.trim);
  windowFrame.position.set(-1.55, -0.24, 1.62);
  const windowPane = mesh(new THREE.BoxGeometry(1.62, 1.24, 0.14), windowMaterial);
  windowPane.position.set(-1.55, -0.24, 1.68);
  const mullion = mesh(new THREE.BoxGeometry(0.055, 1.24, 0.16), materials.wallSide);
  mullion.position.set(-1.55, -0.24, 1.76);
  const sill = mesh(new THREE.BoxGeometry(1.72, 0.055, 0.16), materials.wallSide);
  sill.position.set(-1.55, -0.05, 1.76);
  const door = mesh(new THREE.BoxGeometry(0.72, 1.3, 0.12), materials.deviceFace);
  door.position.set(-0.2, -0.3, 1.62);
  const doorGlass = mesh(new THREE.BoxGeometry(0.5, 0.56, 0.14), windowMaterial);
  doorGlass.position.set(-0.2, -0.04, 1.69);
  group.add(windowFrame, windowPane, mullion, sill, door, doorGlass);

  const loadSignalMaterial = createSignalMaterial(NODE_COLORS.load);
  const loadSignal = mesh(new THREE.SphereGeometry(0.075, 16, 10), loadSignalMaterial);
  loadSignal.position.set(-1.15, -0.18, 1.88);
  group.add(loadSignal);

  return { group, windowMaterial, loadSignalMaterial };
}

function createSolarArray(materials) {
  const group = new THREE.Group();
  group.position.set(-0.65, 1.32, 0.06);
  group.rotation.x = 0.16;

  const columns = 4;
  const rows = 2;
  for (let row = 0; row < rows; row += 1) {
    for (let column = 0; column < columns; column += 1) {
      const x = (column - 1.5) * 1.05;
      const z = (row - 0.5) * 0.92;
      const frame = mesh(new THREE.BoxGeometry(0.98, 0.05, 0.84), materials.panelFrame, true);
      frame.position.set(x, 0, z);
      const surface = mesh(new THREE.BoxGeometry(0.91, 0.065, 0.77), materials.panel);
      surface.position.set(x, 0.035, z);
      group.add(frame, surface);
      [-0.22, 0, 0.22].forEach((offset) => {
        const vertical = mesh(new THREE.BoxGeometry(0.012, 0.075, 0.73), materials.panelGrid);
        vertical.position.set(x + offset, 0.075, z);
        group.add(vertical);
      });
      const horizontal = mesh(new THREE.BoxGeometry(0.87, 0.075, 0.012), materials.panelGrid);
      horizontal.position.set(x, 0.075, z);
      group.add(horizontal);
    }
  }

  const signalMaterial = createSignalMaterial(NODE_COLORS.solar);
  const arrayWidth = 4.15;
  const arrayDepth = 1.78;
  [
    [new THREE.BoxGeometry(arrayWidth, 0.04, 0.035), new THREE.Vector3(0, 0.09, arrayDepth / 2)],
    [new THREE.BoxGeometry(arrayWidth, 0.04, 0.035), new THREE.Vector3(0, 0.09, -arrayDepth / 2)],
    [new THREE.BoxGeometry(0.035, 0.04, arrayDepth), new THREE.Vector3(-arrayWidth / 2, 0.09, 0)],
    [new THREE.BoxGeometry(0.035, 0.04, arrayDepth), new THREE.Vector3(arrayWidth / 2, 0.09, 0)],
  ].forEach(([geometry, position]) => {
    const edge = mesh(geometry, signalMaterial);
    edge.position.copy(position);
    group.add(edge);
  });

  return { group, signalMaterial };
}

function createPowerCenter(materials) {
  const group = new THREE.Group();
  const inverter = new THREE.Group();
  inverter.position.set(0.63, -0.12, 1.78);
  const inverterBody = mesh(new THREE.BoxGeometry(0.76, 1.02, 0.34), materials.device, true);
  const inverterFace = mesh(new THREE.BoxGeometry(0.62, 0.8, 0.06), materials.deviceFace);
  inverterFace.position.z = 0.2;
  const inverterScreen = mesh(new THREE.BoxGeometry(0.34, 0.18, 0.07), materials.trim);
  inverterScreen.position.set(0, 0.2, 0.235);
  const inverterVent = mesh(new THREE.BoxGeometry(0.38, 0.035, 0.07), materials.utility);
  inverterVent.position.set(0, -0.28, 0.235);
  const inverterSignalMaterial = createSignalMaterial(NODE_COLORS.inverter);
  const inverterStripe = mesh(new THREE.BoxGeometry(0.055, 0.82, 0.08), inverterSignalMaterial);
  inverterStripe.position.set(-0.31, 0, 0.245);
  inverter.add(inverterBody, inverterFace, inverterScreen, inverterVent, inverterStripe);

  const battery = new THREE.Group();
  battery.position.set(1.63, -0.33, 1.82);
  const batteryBody = mesh(new THREE.BoxGeometry(0.92, 1.5, 0.46), materials.device, true);
  const batteryFace = mesh(new THREE.BoxGeometry(0.76, 1.32, 0.06), materials.deviceFace);
  batteryFace.position.z = 0.27;
  const batterySignalMaterial = createSignalMaterial(FLOW_COLORS.stale);
  const batteryStripe = mesh(new THREE.BoxGeometry(0.065, 1.32, 0.08), batterySignalMaterial);
  batteryStripe.position.set(-0.38, 0, 0.3);
  battery.add(batteryBody, batteryFace, batteryStripe);

  const batteryModules = [];
  [0.42, 0, -0.42].forEach((y) => {
    const moduleFace = mesh(new THREE.BoxGeometry(0.58, 0.31, 0.055), materials.device);
    moduleFace.position.set(0.05, y, 0.32);
    const track = mesh(new THREE.BoxGeometry(0.51, 0.04, 0.055), materials.utility);
    track.position.set(0.02, y - 0.08, 0.36);
    const fillMaterial = new THREE.MeshBasicMaterial({
      color: FLOW_COLORS.stale,
      transparent: true,
      opacity: 0.22,
      depthWrite: false,
    });
    const fill = mesh(new THREE.BoxGeometry(0.51, 0.045, 0.06), fillMaterial);
    fill.position.set(0.02, y - 0.08, 0.39);
    fill.scale.x = 0.5;
    const signalMaterial = createSignalMaterial(FLOW_COLORS.stale);
    const signal = mesh(new THREE.SphereGeometry(0.035, 12, 8), signalMaterial);
    signal.position.set(0.27, y + 0.065, 0.39);
    battery.add(moduleFace, track, fill, signal);
    batteryModules.push({ fill, fillMaterial, signalMaterial });
  });

  const pedestal = mesh(new THREE.BoxGeometry(1.22, 0.12, 0.7), materials.utility, true);
  pedestal.position.set(1.36, -1.12, 1.76);
  group.add(inverter, battery, pedestal);
  return { group, batteryModules, batterySignalMaterial, inverterSignalMaterial };
}

function createUtilityPole(materials) {
  const group = new THREE.Group();
  group.position.set(3.78, 0, 0.15);
  const pole = mesh(new THREE.CylinderGeometry(0.075, 0.11, 3.7, 12), materials.utility, true);
  pole.position.y = 0.42;
  const upperArm = mesh(new THREE.BoxGeometry(1.05, 0.08, 0.1), materials.utility, true);
  upperArm.position.y = 1.75;
  const lowerArm = mesh(new THREE.BoxGeometry(0.82, 0.07, 0.09), materials.utility, true);
  lowerArm.position.y = 1.47;
  group.add(pole, upperArm, lowerArm);
  [-0.4, 0, 0.4].forEach((x) => {
    const insulator = mesh(new THREE.CylinderGeometry(0.04, 0.04, 0.14, 10), materials.trim);
    insulator.position.set(x, 1.86, 0);
    group.add(insulator);
  });
  const signalMaterial = createSignalMaterial(NODE_COLORS.grid);
  const signal = mesh(new THREE.SphereGeometry(0.07, 14, 10), signalMaterial);
  signal.position.set(0, 1.12, 0.04);
  group.add(signal);
  return { group, signalMaterial };
}

function createFlowNetwork(materials) {
  const group = new THREE.Group();
  const inverterHub = new THREE.Vector3(0.66, -0.1, 2.05);
  const grid = createFlowRoute(new THREE.CatmullRomCurve3([
    new THREE.Vector3(3.78, 1.12, 0.2),
    new THREE.Vector3(3.48, 0.75, 0.76),
    new THREE.Vector3(2.55, 0.12, 1.88),
    new THREE.Vector3(1.5, -0.02, 2.05),
    inverterHub,
  ]), materials, 1, 0);
  const battery = createFlowRoute(new THREE.CatmullRomCurve3([
    inverterHub,
    new THREE.Vector3(1.03, -0.08, 2.1),
    new THREE.Vector3(1.38, -0.18, 2.1),
    new THREE.Vector3(1.63, -0.22, 2.08),
  ]), materials, 1, 0.17);
  const load = createFlowRoute(new THREE.CatmullRomCurve3([
    inverterHub,
    new THREE.Vector3(0.15, -0.08, 2.1),
    new THREE.Vector3(-0.55, -0.12, 2.02),
    new THREE.Vector3(-1.15, -0.18, 1.88),
  ]), materials, 1, 0.31);
  const solar = createFlowRoute(new THREE.CatmullRomCurve3([
    new THREE.Vector3(-0.05, 1.5, 0.92),
    new THREE.Vector3(0.15, 1.14, 1.55),
    new THREE.Vector3(0.44, 0.52, 1.92),
    inverterHub,
  ]), materials, 1, 0.43);
  group.add(grid.group, battery.group, load.group, solar.group);
  return { group, grid, battery, load, solar, routes: [grid, battery, load, solar] };
}

function createFlowRoute(curve, materials, particleCount, phaseOffset) {
  const group = new THREE.Group();
  const lineMaterial = materials.flowLine.clone();
  const glowMaterial = materials.flowGlow.clone();
  const particleMaterial = materials.particle.clone();
  const particleGlowMaterial = materials.particleGlow.clone();
  const line = mesh(new THREE.TubeGeometry(curve, 64, 0.027, 6, false), lineMaterial);
  const glow = mesh(new THREE.TubeGeometry(curve, 64, 0.072, 8, false), glowMaterial);
  group.add(glow, line);

  const coreGeometry = new THREE.SphereGeometry(0.085, 16, 12);
  const glowGeometry = new THREE.SphereGeometry(0.125, 16, 12);
  const particles = Array.from({ length: particleCount }, () => {
    const particle = new THREE.Group();
    const halo = mesh(glowGeometry, particleGlowMaterial);
    const core = mesh(coreGeometry, particleMaterial);
    particle.add(halo, core);
    particle.visible = false;
    group.add(particle);
    return particle;
  });

  return {
    group,
    curve,
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
  route.lineMaterial.emissiveIntensity = route.active ? 0.55 : 0.04;
  route.lineMaterial.opacity = route.active ? 0.82 : route.reporting ? 0.16 : 0.1;
  route.glowMaterial.color.setHex(color);
  route.glowMaterial.opacity = route.active ? 0.07 : 0.01;
  route.particleMaterial.color.setHex(color);
  route.particleGlowMaterial.color.setHex(color);
}

function createTubePath(points, material, radius) {
  const curve = new THREE.CatmullRomCurve3(points);
  return mesh(new THREE.TubeGeometry(curve, 48, radius, 6, false), material);
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

function isRouteActive(route) {
  return Boolean(route?.active && route.reporting && isActiveRouteMode(route.mode));
}

function isActiveRouteMode(mode) {
  return mode === "charging" || mode === "discharging";
}

function setSignal(material, color, active) {
  material.color.setHex(color);
  material.emissive.setHex(color);
  material.emissiveIntensity = active ? 1.45 : 0.28;
}

function pulseSignal(material, active, time, phase) {
  material.emissiveIntensity = active
    ? 1.2 + Math.sin(time * 0.004 + phase) * 0.36
    : 0.28;
}

function normalizePackTelemetry(value) {
  let packs = value;
  if (typeof value === "string") {
    try {
      packs = JSON.parse(value);
    } catch {
      packs = [];
    }
  }
  if (!Array.isArray(packs)) return [];
  return packs.slice(0, 3).map((pack) => ({
    id: String(pack?.id || ""),
    mode: validMode(pack?.mode),
    current: finite(pack?.current),
    power: finite(pack?.power),
    soc: optionalFinite(pack?.soc),
    reporting: Boolean(pack?.reporting),
  }));
}

function optionalFinite(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function mesh(geometry, material, castShadow = false, receiveShadow = false) {
  const object = new THREE.Mesh(geometry, material);
  object.castShadow = castShadow;
  object.receiveShadow = receiveShadow;
  return object;
}

function showFallback(section, canvas, error) {
  section.classList.add("is-fallback");
  section.dataset.renderMode = "fallback";
  canvas.hidden = true;
  canvas.dataset.sceneReady = "false";
  if (error) console.warn("Energy-flow WebGL scene unavailable; using the CSS fallback.", error);
}

function finite(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

function booleanValue(value) {
  if (typeof value === "boolean") return value;
  return String(value).trim().toLowerCase() === "true";
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
  startEnergyFlowScene();
} catch (error) {
  const section = document.getElementById("energyFlowSection");
  const canvas = document.getElementById("energyFlowCanvas");
  if (section && canvas) {
    canvas.dataset.sceneError = error instanceof Error ? error.message : String(error);
    showFallback(section, canvas, error);
  }
}
