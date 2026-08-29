import * as THREE from "three";

const FLOW_COLORS = {
  charging: 0x30d158,
  discharging: 0xff453a,
  idle: 0xff9f0a,
  stale: 0x8e8e93,
};

const NODE_COLORS = {
  grid: 0x64d2ff,
  inverter: 0xff9f0a,
  load: 0xffd60a,
};

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
  renderer.toneMappingExposure = 1.05;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(32, 1, 0.1, 60);
  const root = new THREE.Group();
  root.rotation.y = -0.08;
  scene.add(root);

  const materials = createMaterials();
  const utilityGrid = createUtilityGrid(materials);
  const inverter = createInverter(materials);
  const rack = createBatteryRack(materials);
  const home = createHomeLoad(materials);
  const network = createHomeFlowNetwork(materials);
  root.add(utilityGrid.group, inverter.group, rack.group, home.group, network.group);

  const floor = new THREE.Mesh(
    new THREE.PlaneGeometry(9.4, 4.3),
    new THREE.ShadowMaterial({ color: 0x000000, opacity: 0.16 }),
  );
  floor.position.set(0, -1.48, 0.1);
  floor.rotation.x = -Math.PI / 2;
  floor.receiveShadow = true;
  root.add(floor);

  const ambient = new THREE.HemisphereLight(0xffffff, 0x202124, 1.6);
  const keyLight = new THREE.DirectionalLight(0xffffff, 3.2);
  keyLight.position.set(-3.5, 5, 6);
  keyLight.castShadow = true;
  keyLight.shadow.mapSize.set(1024, 1024);
  keyLight.shadow.camera.left = -6;
  keyLight.shadow.camera.right = 6;
  keyLight.shadow.camera.top = 4;
  keyLight.shadow.camera.bottom = -4;
  const rimLight = new THREE.DirectionalLight(0xff9f0a, 1.25);
  rimLight.position.set(5, 2, -4);
  const fillLight = new THREE.DirectionalLight(0xf4f6ff, 1.1);
  fillLight.position.set(0.5, 1.8, 7);
  scene.add(ambient, keyLight, rimLight, fillLight);

  const flowState = {
    mode: "stale",
    current: 0,
    power: 0,
    soc: 0,
    batteryCount: 0,
    packs: [],
  };
  const motionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
  const finePointerQuery = window.matchMedia("(hover: hover) and (pointer: fine)");
  const pointer = new THREE.Vector2();
  const cameraTarget = new THREE.Vector2();
  let baseCameraY = 2.05;
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
    };
  }

  function applyFlowState(detail = {}) {
    Object.assign(flowState, readSectionState(detail));
    const color = FLOW_COLORS[flowState.mode];
    const rackMagnitude = Math.max(Math.abs(flowState.current), Math.abs(flowState.power) / 54);
    const hasLiveBattery = flowState.mode !== "stale" && flowState.batteryCount > 0;
    const charging = flowState.mode === "charging";
    const discharging = flowState.mode === "discharging";
    configureRoute(network.grid, flowState.mode, rackMagnitude, charging, 1, hasLiveBattery);
    configureRoute(network.battery, flowState.mode, rackMagnitude, charging || discharging, charging ? 1 : -1, hasLiveBattery);
    configureRoute(network.load, flowState.mode, rackMagnitude, discharging, 1, hasLiveBattery);
    setSignal(utilityGrid.signalMaterial, charging ? color : NODE_COLORS.grid, charging);
    setSignal(inverter.signalMaterial, isActiveMode() ? color : NODE_COLORS.inverter, isActiveMode());
    setSignal(home.signalMaterial, discharging ? color : NODE_COLORS.load, discharging);

    rack.modules.forEach((module, index) => {
      const pack = flowState.packs[index];
      const isReporting = pack ? pack.reporting : index < flowState.batteryCount;
      const packMode = isReporting ? validMode(pack?.mode ?? flowState.mode) : "stale";
      const packColor = FLOW_COLORS[packMode];
      const packMagnitude = pack
        ? Math.max(Math.abs(pack.current), Math.abs(pack.power) / 54)
        : rackMagnitude / Math.max(flowState.batteryCount, 1);
      const normalizedSoc = clamp(pack?.soc ?? flowState.soc, 0, 100) / 100;
      module.signal.color.setHex(packColor);
      module.signal.emissive.setHex(packColor);
      module.signal.emissiveIntensity = isReporting && isActiveMode(packMode) ? 1.35 : 0.18;
      module.fill.scale.x = Math.max(0.025, normalizedSoc);
      module.fill.position.x = -0.6 + (1.2 * module.fill.scale.x) / 2;
      module.fillMaterial.color.setHex(packColor);
      module.fillMaterial.emissive.setHex(packColor);
      module.fillMaterial.opacity = isReporting ? 0.95 : 0.32;
    });

    canvas.dataset.energyDirection = flowState.mode === "charging"
      ? "grid-to-battery"
      : flowState.mode === "discharging"
        ? "battery-to-load"
        : "paused";
    canvas.dataset.energyMode = flowState.mode;
    canvas.dataset.activeRoutes = String(network.routes.filter(isRouteActive).length);
    canvas.dataset.topology = "grid-inverter-battery-load";
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

    network.routes.forEach((route, routeIndex) => {
      const active = isRouteActive(route);
      const activeCount = active
        ? Math.round(clamp(2 + route.magnitude * 0.65, 2, route.particles.length))
        : 0;
      const speed = clamp(0.12 + route.magnitude * 0.008, 0.12, 0.38);
      const direction = route.direction;

      route.particles.forEach((particle, index) => {
        particle.visible = index < activeCount;
        if (!particle.visible) return;
        const phase = index / activeCount + route.phaseOffset;
        const progress = wrap01(phase + direction * time * 0.001 * speed);
        route.curve.getPointAt(progress, position);
        route.curve.getTangentAt(progress, tangent).multiplyScalar(direction).normalize();
        particle.position.copy(position);
        particle.quaternion.setFromUnitVectors(route.forwardAxis, tangent);
        const motionPulse = motionQuery.matches
          ? 1
          : 0.9 + Math.sin(time * 0.006 + index + routeIndex) * 0.1;
        const endpointFade = clamp(Math.sin(Math.PI * progress) * 1.45, 0.42, 1);
        const particleScale = motionPulse * endpointFade;
        particle.scale.set(particleScale, particleScale, particleScale * 1.7);
      });

      route.particleMaterial.opacity = active
        ? 0.82 + Math.sin(time * 0.005 + routeIndex) * 0.16
        : 0.25;
    });

    const systemActive = isActiveMode();
    pulseSignal(utilityGrid.signalMaterial, network.grid.active, time, 0);
    pulseSignal(inverter.signalMaterial, systemActive, time, 0.7);
    pulseSignal(home.signalMaterial, network.load.active, time, 1.4);
    home.windowMaterial.emissiveIntensity = network.load.active && !motionQuery.matches
      ? 0.65 + Math.sin(time * 0.0035 + 1.1) * 0.18
      : 0.22;
    rack.modules.forEach((module, index) => {
      const pack = flowState.packs[index];
      const reporting = pack ? pack.reporting : index < flowState.batteryCount;
      if (reporting && isActiveMode(pack?.mode ?? flowState.mode)) {
        module.signal.emissiveIntensity = 1.1 + Math.sin(time * 0.004 + index * 0.75) * 0.35;
      }
    });
  }

  function renderOnce(time) {
    if (disposed) return;
    updateParticles(time);
    cameraTarget.x += (pointer.x - cameraTarget.x) * 0.055;
    cameraTarget.y += (pointer.y - cameraTarget.y) * 0.055;
    camera.position.x = cameraTarget.x * 0.32;
    camera.position.y = baseCameraY + cameraTarget.y * 0.18;
    camera.lookAt(cameraTarget.x * 0.08, -0.12 + cameraTarget.y * 0.04, 0);
    root.rotation.y = -0.08 + cameraTarget.x * 0.035;
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
    const halfFov = THREE.MathUtils.degToRad(camera.fov / 2);
    const fitWidthDistance = 8.05 / (2 * Math.tan(halfFov) * aspect);
    camera.aspect = aspect;
    camera.position.z = Math.max(7.3, fitWidthDistance);
    baseCameraY = width <= 600 ? 1.72 : 2.0;
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
      ? { body: 0x555861, face: 0x292b31, trim: 0xc8cad1, rail: 0x797c85, utility: 0xaeb4bf, wall: 0x656871, roof: 0x30323a, floor: 0x000000 }
      : { body: 0xc8c9ce, face: 0x2c2d32, trim: 0xf1f1f3, rail: 0x85868d, utility: 0x777b84, wall: 0xe7e8eb, roof: 0x4b4d54, floor: 0x000000 };
    materials.body.color.setHex(palette.body);
    materials.face.color.setHex(palette.face);
    materials.trim.color.setHex(palette.trim);
    materials.rail.color.setHex(palette.rail);
    materials.utility.color.setHex(palette.utility);
    materials.homeWall.color.setHex(palette.wall);
    materials.homeRoof.color.setHex(palette.roof);
    floor.material.color.setHex(palette.floor);
    floor.material.opacity = dark ? 0.18 : 0.13;
    ambient.intensity = dark ? 1.8 : 1.75;
    keyLight.intensity = dark ? 3.25 : 3.4;
    rimLight.intensity = dark ? 1.7 : 0.9;
    fillLight.intensity = dark ? 2.35 : 1.1;
    renderer.toneMappingExposure = dark ? 1.18 : 1.02;
    needsPixelAudit = true;
    renderOnce(performance.now());
  }

  const resizeObserver = "ResizeObserver" in window
    ? new ResizeObserver(resize)
    : null;
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
    if (!shouldAnimate()) {
      cameraTarget.copy(pointer);
      renderOnce(performance.now());
    }
  }, { passive: true });
  stage.addEventListener("pointerleave", () => {
    pointer.set(0, 0);
    if (!shouldAnimate()) {
      cameraTarget.set(0, 0);
      renderOnce(performance.now());
    }
  });
  canvas.addEventListener("webglcontextlost", (event) => {
    event.preventDefault();
    disposed = true;
    if (frameRequest) window.cancelAnimationFrame(frameRequest);
    showFallback(section, canvas, new Error("WebGL context lost"));
  });

  canvas.dataset.renderer = "webgl";
  canvas.dataset.sceneReady = "true";
  section.dataset.renderMode = "webgl";
  resize();
  updateTheme();
  applyFlowState();
}

function createMaterials() {
  return {
    body: new THREE.MeshStandardMaterial({ color: 0xc8c9ce, metalness: 0.72, roughness: 0.27 }),
    face: new THREE.MeshStandardMaterial({ color: 0x2c2d32, metalness: 0.48, roughness: 0.32 }),
    trim: new THREE.MeshStandardMaterial({ color: 0xf1f1f3, metalness: 0.82, roughness: 0.2 }),
    rail: new THREE.MeshStandardMaterial({ color: 0x85868d, metalness: 0.86, roughness: 0.26 }),
    utility: new THREE.MeshStandardMaterial({ color: 0x777b84, metalness: 0.74, roughness: 0.32 }),
    homeWall: new THREE.MeshStandardMaterial({ color: 0xe7e8eb, metalness: 0.08, roughness: 0.58 }),
    homeRoof: new THREE.MeshStandardMaterial({ color: 0x4b4d54, metalness: 0.35, roughness: 0.42 }),
    sourceSignal: new THREE.MeshStandardMaterial({
      color: FLOW_COLORS.stale,
      emissive: FLOW_COLORS.stale,
      emissiveIntensity: 0.35,
      metalness: 0.15,
      roughness: 0.24,
    }),
    conduit: new THREE.MeshStandardMaterial({
      color: FLOW_COLORS.stale,
      emissive: FLOW_COLORS.stale,
      emissiveIntensity: 0.04,
      metalness: 0.55,
      roughness: 0.38,
      transparent: true,
      opacity: 0.2,
      depthWrite: false,
    }),
    particle: new THREE.MeshBasicMaterial({
      color: FLOW_COLORS.stale,
      transparent: true,
      opacity: 0.92,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    }),
  };
}

function createUtilityGrid(materials) {
  const group = new THREE.Group();
  group.position.set(-3.15, -0.27, 0);

  const pole = mesh(new THREE.CylinderGeometry(0.075, 0.105, 2.05, 12), materials.utility, true);
  const base = mesh(new THREE.CylinderGeometry(0.25, 0.34, 0.15, 12), materials.rail, true);
  base.position.y = -1.03;
  const upperArm = mesh(new THREE.BoxGeometry(1.08, 0.09, 0.11), materials.utility, true);
  upperArm.position.y = 0.72;
  const lowerArm = mesh(new THREE.BoxGeometry(0.78, 0.075, 0.1), materials.utility, true);
  lowerArm.position.y = 0.43;
  group.add(pole, base, upperArm, lowerArm);

  [-0.4, 0, 0.4].forEach((x) => {
    const insulator = mesh(new THREE.CylinderGeometry(0.035, 0.035, 0.18, 8), materials.trim);
    insulator.position.set(x, 0.84, 0);
    group.add(insulator);
  });

  const signalMaterial = materials.sourceSignal.clone();
  const signal = mesh(new THREE.SphereGeometry(0.095, 14, 10), signalMaterial);
  signal.position.set(0.34, 0.2, 0.48);
  group.add(signal);
  return { group, signalMaterial };
}

function createInverter(materials) {
  const group = new THREE.Group();
  group.position.set(0, 0.54, 0.02);

  const housing = mesh(new THREE.BoxGeometry(1.08, 1.34, 0.58), materials.body, true);
  const face = mesh(new THREE.BoxGeometry(0.88, 1.08, 0.055), materials.face);
  face.position.z = 0.32;
  const screen = mesh(new THREE.BoxGeometry(0.5, 0.24, 0.07), materials.trim);
  screen.position.set(0, 0.25, 0.37);
  const vent = mesh(new THREE.BoxGeometry(0.54, 0.045, 0.07), materials.rail);
  vent.position.set(0, -0.36, 0.37);
  const signalMaterial = materials.sourceSignal.clone();
  const signal = mesh(new THREE.SphereGeometry(0.07, 14, 10), signalMaterial);
  signal.position.set(0.31, 0.25, 0.42);
  const lowerTrim = mesh(new THREE.BoxGeometry(0.92, 0.07, 0.68), materials.rail, true);
  lowerTrim.position.y = -0.71;
  group.add(housing, face, screen, vent, signal, lowerTrim);
  return { group, signalMaterial };
}

function createBatteryRack(materials) {
  const group = new THREE.Group();
  group.position.set(0.75, -0.82, 0);
  group.scale.setScalar(0.54);
  const modules = [];

  const base = mesh(new THREE.BoxGeometry(1.92, 0.14, 1.08), materials.rail, true);
  base.position.y = -1.1;
  const top = mesh(new THREE.BoxGeometry(1.92, 0.12, 1.08), materials.rail, true);
  top.position.y = 1.04;
  const leftRail = mesh(new THREE.BoxGeometry(0.11, 2.12, 1.02), materials.rail, true);
  leftRail.position.x = -0.9;
  const rightRail = leftRail.clone();
  rightRail.position.x = 0.9;
  group.add(base, top, leftRail, rightRail);

  [-0.72, -0.05, 0.62].forEach((y) => {
    const moduleGroup = new THREE.Group();
    moduleGroup.position.y = y;
    const moduleBody = mesh(new THREE.BoxGeometry(1.62, 0.52, 0.88), materials.body, true);
    const moduleFace = mesh(new THREE.BoxGeometry(1.4, 0.34, 0.055), materials.face);
    moduleFace.position.z = 0.47;
    const signalMaterial = materials.sourceSignal.clone();
    const signal = mesh(new THREE.BoxGeometry(0.08, 0.12, 0.075), signalMaterial);
    signal.position.set(0.56, 0, 0.51);
    const track = mesh(new THREE.BoxGeometry(1.2, 0.055, 0.04), materials.rail);
    track.position.set(0, -0.095, 0.505);
    const fillMaterial = materials.sourceSignal.clone();
    fillMaterial.transparent = true;
    const fill = mesh(new THREE.BoxGeometry(1.2, 0.06, 0.05), fillMaterial);
    fill.position.set(-0.3, -0.095, 0.53);
    fill.scale.x = 0.5;
    moduleGroup.add(moduleBody, moduleFace, track, fill, signal);
    group.add(moduleGroup);
    modules.push({ group: moduleGroup, fill, fillMaterial, signal: signalMaterial });
  });

  return { group, modules };
}

function createHomeLoad(materials) {
  const group = new THREE.Group();
  group.position.set(3.05, -0.28, 0);

  const body = mesh(new THREE.BoxGeometry(1.7, 1.1, 1.05), materials.homeWall, true);
  body.position.y = -0.42;
  const roof = mesh(new THREE.ConeGeometry(1.28, 0.78, 4), materials.homeRoof, true);
  roof.position.y = 0.43;
  roof.rotation.y = Math.PI / 4;
  const door = mesh(new THREE.BoxGeometry(0.36, 0.72, 0.055), materials.face);
  door.position.set(0.38, -0.58, 0.56);
  const windowMaterial = new THREE.MeshStandardMaterial({
    color: NODE_COLORS.load,
    emissive: NODE_COLORS.load,
    emissiveIntensity: 0.22,
    metalness: 0.04,
    roughness: 0.2,
  });
  [-0.48, 0].forEach((x) => {
    const window = mesh(new THREE.BoxGeometry(0.3, 0.3, 0.06), windowMaterial);
    window.position.set(x, -0.34, 0.57);
    group.add(window);
  });
  const chimney = mesh(new THREE.BoxGeometry(0.22, 0.62, 0.24), materials.homeRoof, true);
  chimney.position.set(0.49, 0.65, -0.12);
  const signalMaterial = materials.sourceSignal.clone();
  const signal = mesh(new THREE.SphereGeometry(0.08, 14, 10), signalMaterial);
  signal.position.set(-0.88, -0.16, 0.5);
  group.add(body, roof, door, chimney, signal);
  return { group, signalMaterial, windowMaterial };
}

function createHomeFlowNetwork(materials) {
  const group = new THREE.Group();
  const grid = createRoute(new THREE.CatmullRomCurve3([
    new THREE.Vector3(-2.8, -0.07, 0.51),
    new THREE.Vector3(-2.05, 0.38, 0.65),
    new THREE.Vector3(-1.25, 0.62, 0.68),
    new THREE.Vector3(-0.57, 0.54, 0.43),
  ]), materials, 10, 0);
  const battery = createRoute(new THREE.CatmullRomCurve3([
    new THREE.Vector3(0.18, -0.12, 0.43),
    new THREE.Vector3(0.36, -0.34, 0.66),
    new THREE.Vector3(0.62, -0.43, 0.64),
    new THREE.Vector3(0.75, -0.25, 0.43),
  ]), materials, 5, 0.14);
  const load = createRoute(new THREE.CatmullRomCurve3([
    new THREE.Vector3(0.57, 0.54, 0.43),
    new THREE.Vector3(1.25, 0.64, 0.68),
    new THREE.Vector3(2.0, 0.38, 0.66),
    new THREE.Vector3(2.17, -0.44, 0.51),
  ]), materials, 10, 0.28);
  group.add(grid.group, battery.group, load.group);

  return { group, grid, battery, load, routes: [grid, battery, load] };
}

function createRoute(curve, materials, particleCount, phaseOffset) {
  const group = new THREE.Group();
  const lineMaterial = materials.conduit.clone();
  const particleMaterial = materials.particle.clone();
  const tube = mesh(new THREE.TubeGeometry(curve, 56, 0.018, 6, false), lineMaterial);
  group.add(tube);

  const particleGeometry = new THREE.SphereGeometry(0.05, 12, 8);
  const particles = Array.from({ length: particleCount }, () => {
    const particle = mesh(particleGeometry, particleMaterial);
    particle.visible = false;
    group.add(particle);
    return particle;
  });

  return {
    group,
    curve,
    particles,
    lineMaterial,
    particleMaterial,
    phaseOffset,
    forwardAxis: new THREE.Vector3(0, 0, 1),
    mode: "stale",
    magnitude: 0,
    reporting: false,
    active: false,
    direction: 1,
  };
}

function configureRoute(route, mode, magnitude, active, direction, reporting) {
  route.mode = reporting ? validMode(mode) : "stale";
  route.magnitude = Math.max(0, finite(magnitude));
  route.reporting = Boolean(reporting);
  route.active = Boolean(active) && route.reporting && isActiveRouteMode(route.mode);
  route.direction = direction < 0 ? -1 : 1;
  const color = route.active ? FLOW_COLORS[route.mode] : FLOW_COLORS.stale;
  route.lineMaterial.color.setHex(color);
  route.lineMaterial.emissive.setHex(color);
  route.lineMaterial.emissiveIntensity = route.active ? 0.34 : 0.03;
  route.lineMaterial.opacity = route.active ? 0.4 : route.reporting ? 0.15 : 0.09;
  route.particleMaterial.color.setHex(color);
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
  material.emissiveIntensity = active ? 1.45 : 0.32;
}

function pulseSignal(material, active, time, phase) {
  material.emissiveIntensity = active
    ? 1.25 + Math.sin(time * 0.004 + phase) * 0.32
    : 0.32;
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

function mesh(geometry, material, castShadow = false) {
  const object = new THREE.Mesh(geometry, material);
  object.castShadow = castShadow;
  object.receiveShadow = castShadow;
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
  } else {
    console.warn("Energy-flow scene could not start.", error);
  }
}
