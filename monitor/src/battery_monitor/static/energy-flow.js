import * as THREE from "three";

const FLOW_COLORS = {
  charging: 0x30d158,
  discharging: 0xff453a,
  idle: 0xff9f0a,
  stale: 0x8e8e93,
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
  const source = createPowerSource(materials);
  const rack = createBatteryRack(materials);
  const network = createFlowNetwork(materials);
  root.add(source.group, rack.group, network.group);

  const floor = new THREE.Mesh(
    new THREE.PlaneGeometry(8.4, 3.6),
    new THREE.ShadowMaterial({ color: 0x000000, opacity: 0.16 }),
  );
  floor.position.set(0, -1.35, 0.1);
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
    materials.sourceSignal.color.setHex(color);
    materials.sourceSignal.emissive.setHex(color);
    materials.sourceSignal.emissiveIntensity = isActiveMode() ? 1.8 : 0.35;
    network.hubMaterial.color.setHex(color);
    network.hubMaterial.emissive.setHex(color);
    network.hubMaterial.emissiveIntensity = isActiveMode() ? 1.55 : 0.24;

    const rackMagnitude = Math.max(Math.abs(flowState.current), Math.abs(flowState.power) / 54);
    configureRoute(network.trunk, flowState.mode, rackMagnitude, flowState.batteryCount > 0);

    rack.modules.forEach((module, index) => {
      const pack = flowState.packs[index];
      const isReporting = pack ? pack.reporting : index < flowState.batteryCount;
      const packMode = isReporting ? validMode(pack?.mode ?? flowState.mode) : "stale";
      const packColor = FLOW_COLORS[packMode];
      const packMagnitude = pack
        ? Math.max(Math.abs(pack.current), Math.abs(pack.power) / 54)
        : rackMagnitude / Math.max(flowState.batteryCount, 1);
      const normalizedSoc = clamp(pack?.soc ?? flowState.soc, 0, 100) / 100;
      configureRoute(network.branches[index], packMode, packMagnitude, isReporting);
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
      ? "forward"
      : flowState.mode === "discharging"
        ? "reverse"
        : "paused";
    canvas.dataset.energyMode = flowState.mode;
    canvas.dataset.activeRoutes = String(network.routes.filter((route) => isActiveMode(route.mode)).length);
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
      && network.routes.some((route) => isActiveMode(route.mode));
  }

  function updateParticles(time) {
    const tangent = new THREE.Vector3();
    const position = new THREE.Vector3();

    network.routes.forEach((route, routeIndex) => {
      const active = route.reporting && isActiveMode(route.mode);
      const activeCount = active
        ? Math.round(clamp(2 + route.magnitude * 0.65, 2, route.particles.length))
        : 0;
      const speed = clamp(0.12 + route.magnitude * 0.008, 0.12, 0.38);
      const direction = route.mode === "discharging" ? -1 : 1;

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
        particle.scale.setScalar(motionPulse * endpointFade);
      });

      route.particleMaterial.emissiveIntensity = active
        ? 1.65 + Math.sin(time * 0.005 + routeIndex) * 0.4
        : 0.2;
    });

    const systemActive = isActiveMode();
    materials.sourceSignal.emissiveIntensity = systemActive && !motionQuery.matches
      ? 1.45 + Math.sin(time * 0.004) * 0.35
      : 0.35;
    network.hubMaterial.emissiveIntensity = systemActive && !motionQuery.matches
      ? 1.2 + Math.sin(time * 0.004 + 0.7) * 0.3
      : 0.24;
    rack.modules.forEach((module, index) => {
      const route = network.branches[index];
      if (route.reporting && isActiveMode(route.mode)) {
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
    const fitWidthDistance = 7.4 / (2 * Math.tan(halfFov) * aspect);
    camera.aspect = aspect;
    camera.position.z = Math.max(6.9, fitWidthDistance);
    baseCameraY = width <= 600 ? 1.85 : 2.05;
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
      ? { body: 0x555861, face: 0x292b31, trim: 0xc8cad1, rail: 0x797c85, floor: 0x000000 }
      : { body: 0xc8c9ce, face: 0x2c2d32, trim: 0xf1f1f3, rail: 0x85868d, floor: 0x000000 };
    materials.body.color.setHex(palette.body);
    materials.face.color.setHex(palette.face);
    materials.trim.color.setHex(palette.trim);
    materials.rail.color.setHex(palette.rail);
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
    particle: new THREE.MeshStandardMaterial({
      color: FLOW_COLORS.stale,
      emissive: FLOW_COLORS.stale,
      emissiveIntensity: 2.2,
      metalness: 0.05,
      roughness: 0.16,
    }),
  };
}

function createPowerSource(materials) {
  const group = new THREE.Group();
  group.position.set(-2.75, -0.18, 0);

  const housing = mesh(new THREE.BoxGeometry(1.12, 2.05, 0.78), materials.body, true);
  const face = mesh(new THREE.BoxGeometry(0.88, 1.55, 0.055), materials.face);
  face.position.z = 0.42;
  const trim = mesh(new THREE.BoxGeometry(0.94, 0.06, 0.07), materials.trim);
  trim.position.set(0, 0.62, 0.465);
  const signal = mesh(new THREE.BoxGeometry(0.08, 0.82, 0.08), materials.sourceSignal);
  signal.position.set(-0.31, -0.05, 0.48);
  const meter = mesh(new THREE.BoxGeometry(0.42, 0.08, 0.08), materials.trim);
  meter.position.set(0.14, 0.33, 0.48);
  const base = mesh(new THREE.BoxGeometry(1.32, 0.12, 0.98), materials.rail, true);
  base.position.y = -1.08;

  group.add(housing, face, trim, signal, meter, base);
  return { group };
}

function createBatteryRack(materials) {
  const group = new THREE.Group();
  group.position.set(2.55, -0.17, 0);
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

function createFlowNetwork(materials) {
  const group = new THREE.Group();
  const junction = new THREE.Vector3(0.08, -0.14, 0.58);
  const trunk = createRoute(new THREE.CatmullRomCurve3([
    new THREE.Vector3(-2.13, -0.18, 0.5),
    new THREE.Vector3(-1.42, -0.03, 0.57),
    new THREE.Vector3(-0.62, 0.05, 0.62),
    junction,
  ]), materials, 9, 0);
  group.add(trunk.group);

  const branches = [-0.89, -0.22, 0.45].map((targetY, index) => {
    const route = createRoute(new THREE.CatmullRomCurve3([
      junction,
      new THREE.Vector3(0.55, -0.14 + (targetY + 0.14) * 0.32, 0.65),
      new THREE.Vector3(1.1, -0.14 + (targetY + 0.14) * 0.74, 0.62),
      new THREE.Vector3(1.7, targetY, 0.54),
    ]), materials, 6, 0.08 + index * 0.11);
    group.add(route.group);
    return route;
  });

  const hubMaterial = materials.sourceSignal.clone();
  const hubBack = mesh(new THREE.BoxGeometry(0.42, 0.42, 0.08), materials.face);
  hubBack.position.copy(junction).add(new THREE.Vector3(0, 0, -0.05));
  const hub = mesh(new THREE.BoxGeometry(0.2, 0.2, 0.12), hubMaterial);
  hub.position.copy(junction).add(new THREE.Vector3(0, 0, 0.04));
  group.add(hubBack, hub);

  return { group, trunk, branches, routes: [trunk, ...branches], hubMaterial };
}

function createRoute(curve, materials, particleCount, phaseOffset) {
  const group = new THREE.Group();
  const lineMaterial = materials.conduit.clone();
  const particleMaterial = materials.particle.clone();
  const tube = mesh(new THREE.TubeGeometry(curve, 56, 0.018, 6, false), lineMaterial);
  group.add(tube);

  const particleGeometry = new THREE.BoxGeometry(0.065, 0.065, 0.18);
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
  };
}

function configureRoute(route, mode, magnitude, reporting) {
  route.mode = reporting ? validMode(mode) : "stale";
  route.magnitude = Math.max(0, finite(magnitude));
  route.reporting = Boolean(reporting);
  const active = route.reporting && (route.mode === "charging" || route.mode === "discharging");
  const color = FLOW_COLORS[route.mode];
  route.lineMaterial.color.setHex(color);
  route.lineMaterial.emissive.setHex(color);
  route.lineMaterial.emissiveIntensity = active ? 0.3 : 0.04;
  route.lineMaterial.opacity = active ? 0.36 : route.reporting ? 0.2 : 0.11;
  route.particleMaterial.color.setHex(color);
  route.particleMaterial.emissive.setHex(color);
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

startEnergyFlowScene();
