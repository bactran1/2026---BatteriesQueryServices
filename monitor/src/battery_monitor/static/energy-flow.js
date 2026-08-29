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
  const conduit = createConduit(materials);
  root.add(source.group, rack.group, conduit.group);

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
  scene.add(ambient, keyLight, rimLight);

  const flowState = {
    mode: "stale",
    current: 0,
    power: 0,
    soc: 0,
    batteryCount: 0,
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
    };
  }

  function applyFlowState(detail = {}) {
    Object.assign(flowState, readSectionState(detail));
    const color = FLOW_COLORS[flowState.mode];
    materials.conduit.emissive.setHex(color);
    materials.conduit.emissiveIntensity = isActiveMode() ? 0.48 : 0.08;
    materials.conduit.color.setHex(flowState.mode === "stale" ? 0x73737a : color);
    materials.particle.color.setHex(color);
    materials.particle.emissive.setHex(color);
    materials.sourceSignal.color.setHex(color);
    materials.sourceSignal.emissive.setHex(color);
    materials.sourceSignal.emissiveIntensity = isActiveMode() ? 1.8 : 0.35;

    const normalizedSoc = flowState.soc / 100;
    rack.modules.forEach((module, index) => {
      const isReporting = index < flowState.batteryCount;
      module.signal.color.setHex(isReporting ? color : 0x8e8e93);
      module.signal.emissive.setHex(isReporting ? color : 0x8e8e93);
      module.signal.emissiveIntensity = isReporting && isActiveMode() ? 1.35 : 0.18;
      module.fill.scale.x = Math.max(0.025, normalizedSoc);
      module.fill.position.x = -0.6 + (1.2 * module.fill.scale.x) / 2;
      module.fillMaterial.color.setHex(isReporting ? color : 0x8e8e93);
      module.fillMaterial.emissive.setHex(isReporting ? color : 0x8e8e93);
      module.fillMaterial.opacity = isReporting ? 0.95 : 0.32;
    });

    canvas.dataset.energyDirection = flowState.mode === "charging"
      ? "forward"
      : flowState.mode === "discharging"
        ? "reverse"
        : "paused";
    canvas.dataset.energyMode = flowState.mode;
    if (disposed) return;
    renderOnce(performance.now());
    scheduleFrame();
  }

  function isActiveMode() {
    return flowState.mode === "charging" || flowState.mode === "discharging";
  }

  function shouldAnimate() {
    return !disposed
      && !motionQuery.matches
      && isIntersecting
      && isDocumentVisible
      && isActiveMode();
  }

  function updateParticles(time) {
    const active = isActiveMode();
    const magnitude = Math.max(Math.abs(flowState.current), Math.abs(flowState.power) / 54);
    const activeCount = active ? Math.round(clamp(7 + magnitude * 0.6, 7, conduit.particles.length)) : 0;
    const speed = clamp(0.09 + magnitude * 0.006, 0.09, 0.34);
    const direction = flowState.mode === "discharging" ? -1 : 1;
    const tangent = new THREE.Vector3();
    const position = new THREE.Vector3();

    conduit.particles.forEach((particle, index) => {
      particle.visible = index < activeCount;
      if (!particle.visible) return;
      const phase = index / activeCount;
      const progress = wrap01(phase + direction * time * 0.001 * speed);
      conduit.curve.getPointAt(progress, position);
      conduit.curve.getTangentAt(progress, tangent).multiplyScalar(direction).normalize();
      particle.position.copy(position);
      particle.quaternion.setFromUnitVectors(conduit.forwardAxis, tangent);
      const pulse = motionQuery.matches ? 1 : 0.84 + Math.sin(time * 0.006 + index) * 0.16;
      particle.scale.setScalar(pulse);
    });

    const pulse = active && !motionQuery.matches ? 1.15 + Math.sin(time * 0.004) * 0.35 : 0.7;
    materials.particle.emissiveIntensity = pulse * 2.2;
    rack.modules.forEach((module, index) => {
      if (index < flowState.batteryCount && active) {
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
      ? { body: 0x24252a, face: 0x101114, trim: 0x777982, rail: 0x4b4c52, floor: 0x000000 }
      : { body: 0xc8c9ce, face: 0x2c2d32, trim: 0xf1f1f3, rail: 0x85868d, floor: 0x000000 };
    materials.body.color.setHex(palette.body);
    materials.face.color.setHex(palette.face);
    materials.trim.color.setHex(palette.trim);
    materials.rail.color.setHex(palette.rail);
    floor.material.color.setHex(palette.floor);
    floor.material.opacity = dark ? 0.3 : 0.13;
    ambient.intensity = dark ? 1.25 : 1.75;
    keyLight.intensity = dark ? 2.6 : 3.4;
    rimLight.intensity = dark ? 1.55 : 0.9;
    renderer.toneMappingExposure = dark ? 1.12 : 1.02;
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
      emissiveIntensity: 0.08,
      metalness: 0.55,
      roughness: 0.38,
      transparent: true,
      opacity: 0.66,
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

function createConduit(materials) {
  const group = new THREE.Group();
  const curve = new THREE.CatmullRomCurve3([
    new THREE.Vector3(-2.13, -0.02, 0.1),
    new THREE.Vector3(-1.35, 0.15, 0.28),
    new THREE.Vector3(0, 0.42, 0.54),
    new THREE.Vector3(1.28, 0.16, 0.3),
    new THREE.Vector3(1.7, -0.02, 0.1),
  ]);
  const tube = mesh(new THREE.TubeGeometry(curve, 72, 0.035, 8, false), materials.conduit);
  group.add(tube);

  const particleGeometry = new THREE.BoxGeometry(0.075, 0.075, 0.26);
  const particles = Array.from({ length: 20 }, () => {
    const particle = mesh(particleGeometry, materials.particle);
    particle.visible = false;
    group.add(particle);
    return particle;
  });

  return { group, curve, particles, forwardAxis: new THREE.Vector3(0, 0, 1) };
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
