/**
 * Procedural scenario effects for the Three.js terrain viewer: fire, water-dropping drone, explosion,
 * aircraft landing. Everything is built from primitives and canvas-generated soft sprites (no assets),
 * driven by the viewer's shared frame loop through `update(dt, elapsed)`.
 *
 * All sizes are given in mesh units; callers pass `unit` (mesh units per real metre) so effects keep a
 * believable scale next to the buildings, and pass a minimum visible size for things that would otherwise
 * vanish in a wide scene (a 1 m drone over a 500 m terrain).
 */

import * as THREE from "three";

export interface Fx {
  group: THREE.Group;
  update: (dt: number, elapsed: number) => void;
  dispose: () => void;
}

// ------------------------------------------------------------------ helpers

const clamp01 = (v: number) => Math.min(1, Math.max(0, v));
const easeOutCubic = (t: number) => 1 - Math.pow(1 - t, 3);
const easeInOut = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
const easeOutBack = (t: number) => {
  const c1 = 1.70158;
  const c3 = c1 + 1;
  return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2);
};
const lerp = (a: number, b: number, t: number) => a + (b - a) * t;

/** Small deterministic PRNG so an effect looks the same every time it is replayed. */
function rng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const textures = new Map<string, THREE.CanvasTexture>();

function canvasTexture(key: string, w: number, h: number, draw: (ctx: CanvasRenderingContext2D) => void): THREE.CanvasTexture {
  const cached = textures.get(key);
  if (cached) return cached;
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d")!;
  draw(ctx);
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  textures.set(key, tex);
  return tex;
}

function radialTexture(key: string, stops: [number, string][]): THREE.CanvasTexture {
  return canvasTexture(key, 128, 128, (ctx) => {
    const g = ctx.createRadialGradient(64, 64, 0, 64, 64, 64);
    for (const [at, color] of stops) g.addColorStop(at, color);
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, 128, 128);
  });
}

const glowTex = () => radialTexture("glow", [[0, "rgba(255,255,255,1)"], [0.25, "rgba(255,255,255,0.65)"], [1, "rgba(255,255,255,0)"]]);
const smokeTex = () => radialTexture("smoke", [[0, "rgba(255,255,255,0.95)"], [0.55, "rgba(255,255,255,0.4)"], [1, "rgba(255,255,255,0)"]]);
const flameTex = () =>
  canvasTexture("flame", 64, 128, (ctx) => {
    const g = ctx.createLinearGradient(0, 128, 0, 0);
    g.addColorStop(0, "rgba(255,255,230,1)");
    g.addColorStop(0.35, "rgba(255,255,255,0.95)");
    g.addColorStop(0.75, "rgba(255,255,255,0.55)");
    g.addColorStop(1, "rgba(255,255,255,0)");
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.moveTo(32, 2);
    ctx.bezierCurveTo(46, 40, 62, 62, 58, 92);
    ctx.bezierCurveTo(55, 118, 42, 126, 32, 126);
    ctx.bezierCurveTo(22, 126, 9, 118, 6, 92);
    ctx.bezierCurveTo(2, 62, 18, 40, 32, 2);
    ctx.closePath();
    ctx.fill();
  });

function makeSprite(tex: THREE.Texture, color: number, opacity: number, additive: boolean): THREE.Sprite {
  const material = new THREE.SpriteMaterial({
    map: tex,
    color,
    transparent: true,
    opacity,
    depthWrite: false,
    blending: additive ? THREE.AdditiveBlending : THREE.NormalBlending,
  });
  const sprite = new THREE.Sprite(material);
  sprite.renderOrder = 20;
  return sprite;
}

function spriteMat(s: THREE.Sprite): THREE.SpriteMaterial {
  return s.material as THREE.SpriteMaterial;
}

/** Frees geometries and materials under `group` (the shared canvas textures stay cached). */
export function disposeGroup(group: THREE.Object3D): void {
  group.traverse((child) => {
    const mesh = child as THREE.Mesh;
    if (mesh.geometry) mesh.geometry.dispose();
    const material = (mesh as { material?: THREE.Material | THREE.Material[] }).material;
    if (Array.isArray(material)) material.forEach((m) => m.dispose());
    else material?.dispose();
  });
}

function flatDisc(radius: number, color: number, opacity: number, tex?: THREE.Texture): THREE.Mesh {
  const mesh = new THREE.Mesh(
    new THREE.CircleGeometry(radius, 48),
    new THREE.MeshBasicMaterial({ color, map: tex ?? null, transparent: true, opacity, depthWrite: false, side: THREE.DoubleSide, blending: tex ? THREE.AdditiveBlending : THREE.NormalBlending }),
  );
  mesh.rotation.x = -Math.PI / 2;
  mesh.renderOrder = 5;
  return mesh;
}

function ringLine(radius: number, color: number, segments = 72): THREE.LineLoop {
  const pts: THREE.Vector3[] = [];
  for (let i = 0; i < segments; i++) {
    const a = (i / segments) * Math.PI * 2;
    pts.push(new THREE.Vector3(Math.cos(a) * radius, 0, Math.sin(a) * radius));
  }
  return new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineBasicMaterial({ color, transparent: true }));
}

// ------------------------------------------------------------------ vehicle models (all face +X)

const std = (color: number, extra: Partial<THREE.MeshStandardMaterialParameters> = {}) =>
  new THREE.MeshStandardMaterial({ color, roughness: 0.55, metalness: 0.25, ...extra });

function spinningBlades(span: number, thickness: number, color: number): THREE.Group {
  const g = new THREE.Group();
  const a = new THREE.Mesh(new THREE.BoxGeometry(span, thickness, span * 0.08), std(color));
  const b = a.clone();
  b.rotation.y = Math.PI / 2;
  g.add(a, b);
  const blur = new THREE.Mesh(
    new THREE.CircleGeometry(span * 0.5, 24),
    new THREE.MeshBasicMaterial({ color: 0xcbd5e1, transparent: true, opacity: 0.16, side: THREE.DoubleSide, depthWrite: false }),
  );
  blur.rotation.x = -Math.PI / 2;
  g.add(blur);
  return g;
}

/** Quadcopter firefighting drone. `s` = mesh units per model metre (body is ~1 m wide). */
export function createDroneModel(s: number): THREE.Group {
  const g = new THREE.Group();
  const rotors: THREE.Object3D[] = [];
  g.add(new THREE.Mesh(new THREE.BoxGeometry(0.75 * s, 0.22 * s, 0.75 * s), std(0x27313f)));
  const dome = new THREE.Mesh(new THREE.SphereGeometry(0.24 * s, 16, 8, 0, Math.PI * 2, 0, Math.PI / 2), std(0x94a3b8));
  dome.position.y = 0.11 * s;
  g.add(dome);
  const tank = new THREE.Mesh(new THREE.CylinderGeometry(0.22 * s, 0.22 * s, 0.42 * s, 20), std(0x1d8fe0, { metalness: 0.1 }));
  tank.position.y = -0.31 * s;
  g.add(tank);
  const nozzle = new THREE.Mesh(new THREE.CylinderGeometry(0.05 * s, 0.09 * s, 0.32 * s, 10), std(0xe11d48));
  nozzle.rotation.z = -Math.PI / 2.6;
  nozzle.position.set(0.28 * s, -0.36 * s, 0);
  g.add(nozzle);
  const led = new THREE.Mesh(new THREE.SphereGeometry(0.06 * s, 8, 8), new THREE.MeshBasicMaterial({ color: 0xff3b30 }));
  led.position.set(-0.34 * s, 0.02 * s, 0);
  led.userData.blink = true;
  g.add(led);
  for (const sx of [1, -1]) {
    for (const sz of [1, -1]) {
      const arm = new THREE.Mesh(new THREE.BoxGeometry(0.95 * s, 0.07 * s, 0.09 * s), std(0x374151));
      arm.position.set(sx * 0.5 * s, 0.02 * s, sz * 0.5 * s);
      arm.rotation.y = sx * sz * -Math.PI / 4;
      g.add(arm);
      const motor = new THREE.Mesh(new THREE.CylinderGeometry(0.1 * s, 0.1 * s, 0.14 * s, 12), std(0x111827));
      motor.position.set(sx * 0.82 * s, 0.05 * s, sz * 0.82 * s);
      g.add(motor);
      const blades = spinningBlades(0.95 * s, 0.018 * s, 0x0f172a);
      blades.position.set(sx * 0.82 * s, 0.15 * s, sz * 0.82 * s);
      rotors.push(blades);
      g.add(blades);
    }
  }
  for (const sz of [1, -1]) {
    const skid = new THREE.Mesh(new THREE.BoxGeometry(0.8 * s, 0.04 * s, 0.05 * s), std(0x475569));
    skid.position.set(0, -0.56 * s, sz * 0.32 * s);
    g.add(skid);
  }
  g.userData.rotors = rotors;
  g.userData.rotorAxis = "y";
  return g;
}

/** Light emergency helicopter; ~13 m long, rotor ~11 m. */
export function createHelicopterModel(s: number): THREE.Group {
  const g = new THREE.Group();
  const white = std(0xf1f5f9);
  const red = std(0xdc2626);
  const body = new THREE.Mesh(new THREE.CapsuleGeometry(0.95 * s, 3.2 * s, 6, 12), white);
  body.rotation.z = Math.PI / 2;
  g.add(body);
  const stripe = new THREE.Mesh(new THREE.CylinderGeometry(0.97 * s, 0.97 * s, 0.5 * s, 16), red);
  stripe.rotation.z = Math.PI / 2;
  stripe.position.x = 0.1 * s;
  g.add(stripe);
  const glass = new THREE.Mesh(new THREE.SphereGeometry(0.85 * s, 16, 12, 0, Math.PI * 2, 0, Math.PI / 2), std(0x1e3a5f, { metalness: 0.6, roughness: 0.15 }));
  glass.rotation.z = -Math.PI / 2;
  glass.position.x = 1.6 * s;
  g.add(glass);
  const boom = new THREE.Mesh(new THREE.CylinderGeometry(0.16 * s, 0.32 * s, 5.4 * s, 10), white);
  boom.rotation.z = Math.PI / 2;
  boom.position.x = -4.3 * s;
  g.add(boom);
  const fin = new THREE.Mesh(new THREE.BoxGeometry(0.9 * s, 1.5 * s, 0.1 * s), red);
  fin.position.set(-6.7 * s, 0.7 * s, 0);
  g.add(fin);
  const mast = new THREE.Mesh(new THREE.CylinderGeometry(0.1 * s, 0.14 * s, 0.7 * s, 8), std(0x334155));
  mast.position.y = 1.15 * s;
  g.add(mast);
  const main = spinningBlades(11 * s, 0.05 * s, 0x111827);
  main.position.y = 1.55 * s;
  g.add(main);
  const tail = spinningBlades(1.5 * s, 0.03 * s, 0x111827);
  const tailPivot = new THREE.Group(); // stands the tail rotor upright; the blades spin inside it
  tailPivot.rotation.x = Math.PI / 2;
  tailPivot.position.set(-6.9 * s, 0.7 * s, 0.25 * s);
  tailPivot.add(tail);
  g.add(tailPivot);
  for (const sz of [1, -1]) {
    const skid = new THREE.Mesh(new THREE.BoxGeometry(3.6 * s, 0.09 * s, 0.09 * s), std(0x475569));
    skid.position.set(0.2 * s, -1.25 * s, sz * 0.8 * s);
    g.add(skid);
    for (const dx of [-0.9, 0.9]) {
      const strut = new THREE.Mesh(new THREE.BoxGeometry(0.08 * s, 0.7 * s, 0.08 * s), std(0x475569));
      strut.position.set(dx * s, -0.9 * s, sz * 0.8 * s);
      g.add(strut);
    }
  }
  const light = new THREE.Mesh(new THREE.SphereGeometry(0.12 * s, 8, 8), new THREE.MeshBasicMaterial({ color: 0xff3b30 }));
  light.position.set(-0.2 * s, 0.98 * s, 0);
  light.userData.blink = true;
  g.add(light);
  g.userData.rotors = [main, tail];
  g.userData.rotorAxis = "y";
  return g;
}

/** Light single-engine plane; ~8 m long, 11 m wingspan. */
export function createPlaneModel(s: number): THREE.Group {
  const g = new THREE.Group();
  const white = std(0xe5e7eb);
  const red = std(0xdc2626);
  const fus = new THREE.Mesh(new THREE.CapsuleGeometry(0.6 * s, 5.4 * s, 6, 12), white);
  fus.rotation.z = Math.PI / 2;
  g.add(fus);
  const wing = new THREE.Mesh(new THREE.BoxGeometry(1.7 * s, 0.14 * s, 11 * s), white);
  wing.position.set(0.5 * s, 0.35 * s, 0);
  g.add(wing);
  const tailWing = new THREE.Mesh(new THREE.BoxGeometry(1 * s, 0.1 * s, 3.6 * s), white);
  tailWing.position.set(-3.4 * s, 0.25 * s, 0);
  g.add(tailWing);
  const fin = new THREE.Mesh(new THREE.BoxGeometry(1.2 * s, 1.3 * s, 0.1 * s), red);
  fin.position.set(-3.5 * s, 0.9 * s, 0);
  g.add(fin);
  const canopy = new THREE.Mesh(new THREE.SphereGeometry(0.55 * s, 12, 8, 0, Math.PI * 2, 0, Math.PI / 2), std(0x1e3a5f, { metalness: 0.6, roughness: 0.15 }));
  canopy.position.set(0.7 * s, 0.4 * s, 0);
  g.add(canopy);
  const prop = spinningBlades(1.9 * s, 0.05 * s, 0x111827);
  prop.rotation.z = Math.PI / 2;
  prop.position.x = 3.3 * s;
  g.add(prop);
  for (const sz of [1, -1]) {
    const gear = new THREE.Mesh(new THREE.CylinderGeometry(0.22 * s, 0.22 * s, 0.14 * s, 12), std(0x111827));
    gear.rotation.x = Math.PI / 2;
    gear.position.set(0.9 * s, -0.75 * s, sz * 0.9 * s);
    g.add(gear);
  }
  g.userData.rotors = [prop];
  g.userData.rotorAxis = "x";
  return g;
}

/** Spins a model's rotors at `speed` rad/s and blinks its beacon. */
function spinRotors(model: THREE.Group, dt: number, elapsed: number, speed: number): void {
  const rotors = (model.userData.rotors as THREE.Object3D[] | undefined) ?? [];
  const axis = model.userData.rotorAxis as "x" | "y";
  rotors.forEach((rotor, i) => {
    rotor.rotation[axis] += dt * speed * (i % 2 === 0 ? 1 : -1);
  });
  model.traverse((child) => {
    if (child.userData.blink) child.visible = Math.sin(elapsed * 7) > -0.2;
  });
}

// ------------------------------------------------------------------ fire

export interface FireFx extends Fx {
  /** Start (or restart) the ignition sequence on the next frame. */
  ignite: () => void;
  /** Start putting the fire out `delay` seconds from now, over `duration` seconds. */
  douse: (delay: number, duration: number) => void;
}

export function createFireFx(o: { radius: number; unit: number; seed?: number }): FireFx {
  const { radius, unit } = o;
  const rand = rng(o.seed ?? 7);
  const group = new THREE.Group();

  const scorch = flatDisc(radius * 0.95, 0x140c07, 0, undefined);
  scorch.position.y = 0.02 * unit;
  const glow = flatDisc(radius * 1.35, 0xff5a12, 0, glowTex());
  glow.position.y = 0.04 * unit;
  group.add(scorch, glow);

  const tongues = Array.from({ length: 26 }, (_, i) => {
    const r = Math.sqrt(rand()) * radius * 0.85;
    const a = rand() * Math.PI * 2;
    const closeness = 1 - r / radius;
    const w = unit * (2.4 + 2.6 * closeness) * (0.7 + 0.6 * rand());
    const outer = makeSprite(flameTex(), 0xff5a12, 0.9, true);
    const inner = makeSprite(flameTex(), 0xffd24a, 0.95, true);
    outer.center.set(0.5, 0.04);
    inner.center.set(0.5, 0.04);
    group.add(outer, inner);
    return { outer, inner, x: Math.cos(a) * r, z: Math.sin(a) * r, w, h: w * 2.1, delay: (r / radius) * 2.1 + rand() * 0.4, phase: rand() * 10 + i, dist: r / radius };
  });

  const embers = Array.from({ length: 34 }, () => {
    const s = makeSprite(glowTex(), 0xffb347, 0, true);
    group.add(s);
    const a = rand() * Math.PI * 2;
    const r = Math.sqrt(rand()) * radius * 0.75;
    return { s, x: Math.cos(a) * r, z: Math.sin(a) * r, phase: rand(), drift: (rand() - 0.5) * radius * 0.8 };
  });

  const smoke = Array.from({ length: 9 }, (_, i) => {
    const s = makeSprite(smokeTex(), 0x2b2b2b, 0, false);
    group.add(s);
    return { s, phase: i / 9, x: (rand() - 0.5) * radius * 0.5, z: (rand() - 0.5) * radius * 0.5 };
  });

  const light = new THREE.PointLight(0xff7a2a, 0, radius * 12, 0);
  light.position.y = radius * 0.5;
  group.add(light);

  let igniteAt: number | null = null; // null = set on next frame
  let ignitePending = true;
  let douseAt = Infinity;
  let douseDelay: number | null = null;
  let douseDur = 3;

  const fx: FireFx = {
    group,
    ignite() {
      ignitePending = true;
      douseAt = Infinity;
      douseDelay = null;
    },
    douse(delay, duration) {
      douseDelay = delay;
      douseDur = Math.max(duration, 0.5);
    },
    update(dt, elapsed) {
      if (ignitePending) {
        igniteAt = elapsed;
        ignitePending = false;
      }
      if (douseDelay !== null) {
        douseAt = elapsed + douseDelay;
        douseDelay = null;
      }
      const t0 = igniteAt ?? elapsed;
      const burn = clamp01((elapsed - t0) / 2.6);
      const dGlobal = easeInOut(clamp01((elapsed - douseAt) / douseDur));
      const intensity = burn * (1 - dGlobal);

      for (const f of tongues) {
        const grow = easeOutBack(clamp01((elapsed - t0 - f.delay) / 0.7));
        const outDelay = f.dist * douseDur * 0.35;
        const out = easeInOut(clamp01((elapsed - douseAt - outDelay) / (douseDur * 0.65)));
        const vis = Math.max(grow, 0) * (1 - out);
        const flick = 1 + 0.13 * Math.sin(elapsed * 9 + f.phase) + 0.07 * Math.sin(elapsed * 17 + f.phase * 2);
        const sway = Math.sin(elapsed * 3 + f.phase) * 0.09 * f.w;
        for (const [sprite, k] of [[f.outer, 1], [f.inner, 0.55]] as const) {
          sprite.position.set(f.x + sway * k, 0.03 * unit, f.z);
          sprite.scale.set(f.w * k * vis * flick * (1 + 0.05 * Math.sin(elapsed * 13 + f.phase)), f.h * k * vis * flick, 1);
          spriteMat(sprite).opacity = 0.9 * Math.min(1, vis * 2);
        }
      }

      const scorchGrow = clamp01((elapsed - t0) / 6);
      (scorch.material as THREE.MeshBasicMaterial).opacity = 0.55 * scorchGrow;
      (glow.material as THREE.MeshBasicMaterial).opacity = 0.6 * intensity * (0.85 + 0.15 * Math.sin(elapsed * 8));
      glow.scale.setScalar(0.4 + 0.6 * easeOutCubic(burn));
      light.intensity = intensity * (1.5 + 0.4 * Math.sin(elapsed * 11) + 0.2 * Math.sin(elapsed * 23));

      for (const e of embers) {
        const age = (elapsed * 0.32 + e.phase) % 1;
        e.s.position.set(e.x + Math.sin(elapsed * 2 + e.phase * 9) * e.drift * age, unit * 1.5 + age * radius * 2.4, e.z);
        e.s.scale.setScalar(unit * 0.55 * (1 - age * 0.6));
        spriteMat(e.s).opacity = (1 - age) * intensity * 0.95;
      }

      const steam = dGlobal;
      const smokeLinger = burn * (1 - clamp01((elapsed - douseAt - douseDur) / (douseDur * 1.8)));
      for (const p of smoke) {
        const age = (elapsed * 0.15 + p.phase) % 1;
        p.s.position.set(p.x + age * radius * 0.5, unit * 2.5 + age * radius * 3.4, p.z);
        p.s.scale.setScalar(radius * (0.7 + age * 1.7));
        const m = spriteMat(p.s);
        m.color.setHex(0x2b2b2b).lerp(new THREE.Color(0xe5e7eb), Math.max(steam, age * 0.35));
        m.opacity = 0.34 * Math.sin(Math.PI * age) * smokeLinger * (0.6 + 0.4 * (1 - steam));
      }
      void dt;
    },
    dispose() {
      disposeGroup(group);
    },
  };
  return fx;
}

// ------------------------------------------------------------------ drone + water arc

export interface DroneDropFx extends Fx {
  /** Seconds after the effect starts when the first water reaches the fire. */
  firstHitAfter: number;
  /** Seconds after the effect starts when the spray stops. */
  sprayEnds: number;
}

/**
 * A drone flies in from the sky to the stand-off point and pours water on the fire along the true
 * projectile arc (horizontal release: x = v t, y drop = g t^2 / 2), so the distance it stands off is
 * exactly the reach the calculation reports.
 */
export function createDroneDropFx(o: {
  fire: THREE.Vector3; // ground point of the fire
  standoff: THREE.Vector3; // hover point (already at drone altitude)
  spawn: THREE.Vector3;
  droneScale: number;
  unit: number;
}): DroneDropFx {
  const { fire, standoff, spawn, droneScale, unit } = o;
  const group = new THREE.Group();

  const drone = createDroneModel(droneScale);
  group.add(drone);
  const toFire = new THREE.Vector3(fire.x - standoff.x, 0, fire.z - standoff.z);
  const yaw = Math.atan2(-toFire.z, toFire.x);
  drone.rotation.y = yaw;
  drone.position.copy(spawn);

  const FLY = 3.4;
  const SETTLE = 0.7;
  const FALL = 1.9; // visual fall time of a droplet
  const SPRAY = 6.5;
  const start = FLY + SETTLE;

  // droplets
  const N = 220;
  const positions = new Float32Array(N * 3);
  const geom = new THREE.BufferGeometry();
  geom.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  const dropMat = new THREE.PointsMaterial({ map: glowTex(), color: 0x8fd3ff, size: droneScale * 0.5, transparent: true, opacity: 0.95, depthWrite: false, blending: THREE.AdditiveBlending, sizeAttenuation: true });
  const drops = new THREE.Points(geom, dropMat);
  drops.frustumCulled = false;
  drops.renderOrder = 25;
  group.add(drops);
  const rand = rng(11);
  const jitter = Array.from({ length: N }, () => [(rand() - 0.5) * droneScale * 0.5, (rand() - 0.5) * droneScale * 0.5]);

  // the guide line from the drone to the ground below it, and the stand-off ring around the fire
  const guideGeom = new THREE.BufferGeometry().setFromPoints([standoff.clone(), new THREE.Vector3(standoff.x, fire.y, standoff.z)]);
  const guide = new THREE.Line(guideGeom, new THREE.LineDashedMaterial({ color: 0xfbbf24, dashSize: unit * 1.2, gapSize: unit * 0.8, transparent: true, opacity: 0 }));
  guide.computeLineDistances();
  group.add(guide);
  const standoffDist = Math.hypot(toFire.x, toFire.z);
  const ring = ringLine(Math.max(standoffDist, unit), 0xfbbf24);
  ring.position.set(fire.x, fire.y + 0.06 * unit, fire.z);
  (ring.material as THREE.LineBasicMaterial).opacity = 0;
  group.add(ring);

  const splash = Array.from({ length: 6 }, () => {
    const s = makeSprite(smokeTex(), 0xdbeafe, 0, false);
    group.add(s);
    return s;
  });

  let t0: number | null = null;
  const dir = new THREE.Vector3(toFire.x, 0, toFire.z).normalize();

  const fx: DroneDropFx = {
    group,
    firstHitAfter: start + FALL,
    sprayEnds: start + SPRAY + FALL,
    update(dt, elapsed) {
      if (t0 === null) t0 = elapsed;
      const t = elapsed - t0;

      // flight
      const u = clamp01(t / FLY);
      const e = easeInOut(u);
      drone.position.set(lerp(spawn.x, standoff.x, e), lerp(spawn.y, standoff.y, e) + Math.sin(elapsed * 2.2) * 0.12 * droneScale * (u >= 1 ? 1 : 0), lerp(spawn.z, standoff.z, e));
      drone.rotation.z = -0.22 * (1 - u) * (u < 1 ? 1 : 0) + (u >= 1 ? Math.sin(elapsed * 1.7) * 0.03 : 0);
      drone.rotation.x = u >= 1 ? Math.sin(elapsed * 1.3) * 0.03 : 0;
      spinRotors(drone, dt, elapsed, 55);

      // guide + ring appear when the drone arrives
      const arrive = clamp01((t - FLY * 0.8) / 0.8);
      (guide.material as THREE.LineDashedMaterial).opacity = 0.75 * arrive;
      (ring.material as THREE.LineBasicMaterial).opacity = 0.85 * arrive;
      const gp = guideGeom.getAttribute("position") as THREE.BufferAttribute;
      gp.setXYZ(0, drone.position.x, drone.position.y, drone.position.z);
      gp.setXYZ(1, drone.position.x, fire.y, drone.position.z);
      gp.needsUpdate = true;
      guide.computeLineDistances();

      // droplets along the arc
      const pos = geom.getAttribute("position") as THREE.BufferAttribute;
      const nozzle = new THREE.Vector3(standoff.x + dir.x * droneScale * 0.4, standoff.y - droneScale * 0.4, standoff.z + dir.z * droneScale * 0.4);
      for (let i = 0; i < N; i++) {
        const birth = start + (i / N) * SPRAY;
        const age = t - birth;
        const k = age / FALL;
        if (k < 0 || k > 1) {
          pos.setXYZ(i, 0, -1e5, 0);
          continue;
        }
        const along = k;
        const px = nozzle.x + (fire.x - nozzle.x) * along + jitter[i][0] * (0.3 + k);
        const pz = nozzle.z + (fire.z - nozzle.z) * along + jitter[i][1] * (0.3 + k);
        const py = nozzle.y - (nozzle.y - fire.y) * k * k;
        pos.setXYZ(i, px, py, pz);
      }
      pos.needsUpdate = true;
      dropMat.opacity = 0.95 * (1 - clamp01((t - (start + SPRAY + FALL)) / 0.8));

      // splash at the fire while water is arriving
      const arriving = t > start + FALL && t < start + SPRAY + FALL;
      splash.forEach((s, i) => {
        const age = ((t * 0.9 + i / splash.length) % 1);
        s.position.set(fire.x + (i - 2.5) * unit * 0.6, fire.y + unit * 1.2 + age * unit * 5, fire.z + Math.sin(i * 2) * unit);
        s.scale.setScalar(unit * (3 + age * 6));
        spriteMat(s).opacity = arriving ? 0.5 * Math.sin(Math.PI * age) : 0;
      });
    },
    dispose() {
      disposeGroup(group);
    },
  };
  return fx;
}

// ------------------------------------------------------------------ explosion

export interface ExplosionFx extends Fx {
  duration: number;
}

/** Fireball, shock dome, expanding ground ring, debris and a rising smoke column. */
export function createExplosionFx(o: { radii: number[]; unit: number }): ExplosionFx {
  const outer = Math.max(...o.radii);
  const core = Math.min(...o.radii); // severe band
  const group = new THREE.Group();
  const rand = rng(5);

  const flash = makeSprite(glowTex(), 0xfff4d6, 0, true);
  group.add(flash);

  const fireballs = Array.from({ length: 7 }, (_, i) => {
    const s = makeSprite(glowTex(), i % 2 ? 0xffb020 : 0xff6a10, 0, true);
    group.add(s);
    return { s, ox: (rand() - 0.5) * core * 0.5, oz: (rand() - 0.5) * core * 0.5, size: core * (0.9 + rand() * 0.9), delay: rand() * 0.25 };
  });

  const dome = new THREE.Mesh(
    new THREE.SphereGeometry(1, 40, 20, 0, Math.PI * 2, 0, Math.PI / 2),
    new THREE.MeshBasicMaterial({ color: 0xffd9a0, transparent: true, opacity: 0, side: THREE.DoubleSide, depthWrite: false, blending: THREE.AdditiveBlending }),
  );
  dome.renderOrder = 15;
  group.add(dome);

  const groundRing = new THREE.Mesh(
    new THREE.RingGeometry(0.9, 1, 96),
    new THREE.MeshBasicMaterial({ color: 0xffe08a, transparent: true, opacity: 0, side: THREE.DoubleSide, depthWrite: false, blending: THREE.AdditiveBlending }),
  );
  groundRing.rotation.x = -Math.PI / 2;
  groundRing.position.y = 0.05 * o.unit;
  groundRing.renderOrder = 15;
  group.add(groundRing);

  const scorch = flatDisc(core * 0.9, 0x120b07, 0);
  scorch.position.y = 0.03 * o.unit;
  group.add(scorch);

  // debris
  const D = 140;
  const dPos = new Float32Array(D * 3);
  const dGeom = new THREE.BufferGeometry();
  dGeom.setAttribute("position", new THREE.BufferAttribute(dPos, 3));
  const dMat = new THREE.PointsMaterial({ map: glowTex(), color: 0xffa040, size: Math.max(core * 0.05, o.unit * 0.6), transparent: true, opacity: 1, depthWrite: false, blending: THREE.AdditiveBlending });
  const debris = new THREE.Points(dGeom, dMat);
  debris.frustumCulled = false;
  group.add(debris);
  const vel = Array.from({ length: D }, () => {
    const a = rand() * Math.PI * 2;
    const sp = core * (0.6 + rand() * 1.5);
    return { vx: Math.cos(a) * sp, vz: Math.sin(a) * sp, vy: core * (1.4 + rand() * 2.4), delay: rand() * 0.15 };
  });

  // smoke column + mushroom cap
  const smoke = Array.from({ length: 18 }, (_, i) => {
    const s = makeSprite(smokeTex(), 0x2a2622, 0, false);
    group.add(s);
    const cap = i >= 11;
    return { s, cap, delay: 0.4 + i * 0.13, ox: (rand() - 0.5) * core * 0.35, oz: (rand() - 0.5) * core * 0.35, size: core * (cap ? 1.6 + rand() * 0.9 : 0.8 + rand() * 0.5) };
  });

  const light = new THREE.PointLight(0xffa040, 0, outer * 3, 0);
  light.position.y = core * 0.6;
  group.add(light);

  let t0: number | null = null;
  const DURATION = 9;
  const fx: ExplosionFx = {
    group,
    duration: DURATION,
    update(dt, elapsed) {
      if (t0 === null) t0 = elapsed;
      const t = elapsed - t0;
      void dt;

      spriteMat(flash).opacity = 1 * (1 - clamp01(t / 0.45)) * (t >= 0 ? 1 : 0);
      flash.scale.setScalar(core * (3 + 5 * easeOutCubic(clamp01(t / 0.45))));
      flash.position.y = core * 0.3;
      light.intensity = 6 * (1 - clamp01(t / 1.6));

      for (const f of fireballs) {
        const u = clamp01((t - f.delay) / 1.7);
        const grow = easeOutCubic(u);
        f.s.position.set(f.ox * grow, core * (0.25 + 0.9 * u), f.oz * grow);
        f.s.scale.setScalar(f.size * (0.3 + 1.2 * grow));
        const c = spriteMat(f.s).color;
        c.setHex(0xffe08a).lerp(new THREE.Color(0xd9430a), clamp01(u * 1.3));
        spriteMat(f.s).opacity = t < f.delay ? 0 : 0.95 * (1 - clamp01((u - 0.45) / 0.55));
      }

      const shock = easeOutCubic(clamp01(t / 2.0));
      dome.scale.set(outer * shock, outer * shock * 0.55, outer * shock);
      (dome.material as THREE.MeshBasicMaterial).opacity = 0.22 * (1 - shock) * (t < 2 ? 1 : 0);
      groundRing.scale.setScalar(Math.max(outer * shock, 0.001));
      (groundRing.material as THREE.MeshBasicMaterial).opacity = 0.9 * (1 - shock);

      (scorch.material as THREE.MeshBasicMaterial).opacity = 0.6 * clamp01((t - 0.3) / 1.5);

      const p = dGeom.getAttribute("position") as THREE.BufferAttribute;
      const g = core * 3.4;
      for (let i = 0; i < D; i++) {
        const v = vel[i];
        const a = t - v.delay;
        if (a < 0 || a > 3.2) {
          p.setXYZ(i, 0, -1e5, 0);
          continue;
        }
        const y = v.vy * a - 0.5 * g * a * a;
        p.setXYZ(i, v.vx * a * 0.7, Math.max(y, 0), v.vz * a * 0.7);
      }
      p.needsUpdate = true;
      dMat.opacity = 1 - clamp01((t - 1.8) / 1.4);

      for (const s of smoke) {
        const u = clamp01((t - s.delay) / 6);
        const rise = easeOutCubic(u);
        const height = s.cap ? core * (3.2 + 0.5 * u) : core * (0.4 + 2.8 * (0.35 + 0.65 * rise) * ((s.delay - 0.4) / 2.4 + 0.2));
        const spread = s.cap ? core * 1.2 * rise : core * 0.25 * rise;
        s.s.position.set(s.ox + (s.cap ? Math.cos(s.delay * 9) * spread : 0), height * (s.cap ? rise : 0.4 + 0.6 * rise), s.oz + (s.cap ? Math.sin(s.delay * 9) * spread : 0));
        s.s.scale.setScalar(s.size * (0.5 + 1.3 * rise));
        spriteMat(s.s).opacity = t < s.delay ? 0 : 0.55 * Math.sin(Math.PI * Math.pow(u, 0.7));
        spriteMat(s.s).color.setHex(0x3a332d).lerp(new THREE.Color(0x8a8378), u);
      }
    },
    dispose() {
      disposeGroup(group);
    },
  };
  return fx;
}

// ------------------------------------------------------------------ landing

export type AircraftKind = "helicopter" | "drone" | "plane";

export interface LandingFx extends Fx {
  duration: number;
}

/**
 * An aircraft flies the approach, lands on the pad (or, for a fixed-wing plane on a pad that is too short,
 * flies the approach and goes around), with rotor spool-down, dust and a pulsing pad marking.
 */
export function createLandingFx(o: {
  kind: AircraftKind;
  radius: number; // pad radius, mesh units
  heading: number; // approach direction in the XZ plane, radians (direction of travel)
  fits: boolean | null;
  unit: number; // mesh units per real metre
  minVisible: number; // smallest size (mesh units) the aircraft may be drawn at
}): LandingFx {
  const { kind, radius, heading, unit } = o;
  const group = new THREE.Group();
  const fitColor = o.fits === false ? 0xef4444 : o.fits === true ? 0x22c55e : 0x38bdf8;

  const realLength = kind === "helicopter" ? 13 : kind === "plane" ? 8 : 1.6;
  const scale = Math.max(unit, o.minVisible / realLength);
  const model = kind === "helicopter" ? createHelicopterModel(scale) : kind === "plane" ? createPlaneModel(scale) : createDroneModel(scale);
  group.add(model);

  // pad
  const padFill = flatDisc(radius, fitColor, 0.16);
  padFill.position.y = 0.05 * unit;
  const pad = new THREE.Mesh(new THREE.RingGeometry(radius * 0.93, radius, 64), new THREE.MeshBasicMaterial({ color: fitColor, transparent: true, opacity: 0.8, side: THREE.DoubleSide, depthWrite: false }));
  pad.rotation.x = -Math.PI / 2;
  pad.position.y = 0.07 * unit;
  group.add(padFill, pad);
  const mark = new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.85, depthWrite: false, side: THREE.DoubleSide });
  const bar = (w: number, l: number, x: number, z: number) => {
    const m = new THREE.Mesh(new THREE.PlaneGeometry(w, l), mark);
    m.rotation.x = -Math.PI / 2;
    m.position.set(x, 0.09 * unit, z);
    group.add(m);
  };
  if (kind !== "plane") {
    const h = radius * 0.5;
    bar(h * 0.18, h * 1.5, -h * 0.4, 0);
    bar(h * 0.18, h * 1.5, h * 0.4, 0);
    bar(h * 0.9, h * 0.18, 0, 0);
  } else {
    bar(radius * 1.6, radius * 0.08, 0, 0);
  }

  const dust = Array.from({ length: 14 }, () => {
    const s = makeSprite(smokeTex(), 0xb59b7a, 0, false);
    group.add(s);
    return s;
  });

  const hv = new THREE.Vector3(Math.cos(heading), 0, Math.sin(heading));
  const approach = Math.max(radius * 5, 60 * unit);
  const startH = Math.max(40 * unit, scale * 6);
  const hoverH = kind === "plane" ? scale * 1.2 : Math.max(3.5 * unit, scale * 1.6);
  const restY = kind === "helicopter" ? 1.28 * scale : kind === "drone" ? 0.6 * scale : 0.8 * scale;
  const yaw = Math.atan2(-hv.z, hv.x);
  model.rotation.y = yaw;

  const T_APP = kind === "plane" ? 5.2 : 4.4;
  const T_DOWN = 2.4;
  const goAround = kind === "plane" && o.fits !== true;
  const DURATION = goAround ? T_APP + 4.5 : T_APP + T_DOWN + 3.6;
  let t0: number | null = null;

  const fx: LandingFx = {
    group,
    duration: DURATION,
    update(dt, elapsed) {
      if (t0 === null) t0 = elapsed;
      const t = elapsed - t0;

      (pad.material as THREE.MeshBasicMaterial).opacity = 0.65 + 0.25 * Math.sin(elapsed * 4);
      (padFill.material as THREE.MeshBasicMaterial).opacity = 0.14 + 0.06 * Math.sin(elapsed * 4);

      let spin = 60;
      let pitch = 0;
      let touch = -1;
      if (goAround) {
        const u = clamp01(t / T_APP);
        const e = 1 - Math.pow(1 - u, 1.4);
        const along = lerp(-approach, 0, e);
        const y = lerp(startH, hoverH, easeOutCubic(u));
        if (t <= T_APP) {
          model.position.set(hv.x * along, y, hv.z * along);
          pitch = -0.12;
        } else {
          const c = t - T_APP;
          model.position.set(hv.x * (c * radius * 1.6), hoverH + c * c * scale * 1.4, hv.z * (c * radius * 1.6));
          pitch = 0.32;
        }
        spin = 90;
      } else {
        const u = clamp01(t / T_APP);
        if (t <= T_APP) {
          const e = easeOutCubic(u);
          const along = lerp(-approach, 0, e);
          const y = hoverH + (startH - hoverH) * Math.pow(1 - u, 1.7);
          model.position.set(hv.x * along, y, hv.z * along);
          pitch = -0.2 * (1 - u);
        } else if (t <= T_APP + T_DOWN) {
          const d = easeInOut((t - T_APP) / T_DOWN);
          model.position.set(0, lerp(hoverH, restY, d), 0);
          pitch = 0;
          touch = 0;
        } else {
          model.position.set(0, restY, 0);
          touch = t - (T_APP + T_DOWN);
          spin = 60 * (1 - clamp01(touch / 3.2));
        }
        if (kind === "plane") pitch = 0;
      }
      model.rotation.z = pitch;
      if (kind !== "plane") model.rotation.x = Math.sin(elapsed * 1.6) * 0.02 * (touch >= 0 ? 0 : 1);
      spinRotors(model, dt, elapsed, spin);

      // dust while the rotor wash meets the ground
      const washing = t > T_APP - 0.8 && t < T_APP + T_DOWN + 2.2 && kind !== "plane";
      dust.forEach((s, i) => {
        const cycle = ((t * 0.7 + i / dust.length) % 1);
        const a = (i / dust.length) * Math.PI * 2;
        const r = radius * (0.25 + cycle * 0.9);
        s.position.set(Math.cos(a) * r, unit * (0.6 + cycle * 1.6), Math.sin(a) * r);
        s.scale.setScalar(unit * (2.5 + cycle * 6));
        spriteMat(s).opacity = washing ? 0.32 * Math.sin(Math.PI * cycle) : 0;
      });
    },
    dispose() {
      disposeGroup(group);
    },
  };
  return fx;
}

// ------------------------------------------------------------------ marker pin

/** A pulsing pin to show where a point was picked on the terrain. */
export function createPinFx(o: { unit: number; color: number; size: number }): Fx {
  const group = new THREE.Group();
  const { unit, size } = o;
  const mat = new THREE.MeshBasicMaterial({ color: o.color, transparent: true, opacity: 0.95 });
  const cone = new THREE.Mesh(new THREE.ConeGeometry(size * 0.35, size * 1.1, 16), mat);
  cone.rotation.x = Math.PI;
  cone.position.y = size * 1.15;
  const head = new THREE.Mesh(new THREE.SphereGeometry(size * 0.3, 16, 12), mat);
  head.position.y = size * 1.9;
  const ring = new THREE.Mesh(new THREE.RingGeometry(size * 0.8, size, 40), new THREE.MeshBasicMaterial({ color: o.color, transparent: true, opacity: 0.6, side: THREE.DoubleSide, depthWrite: false }));
  ring.rotation.x = -Math.PI / 2;
  ring.position.y = 0.1 * unit;
  group.add(cone, head, ring);
  return {
    group,
    update(_dt, elapsed) {
      const p = (elapsed * 0.9) % 1;
      ring.scale.setScalar(1 + p * 1.8);
      (ring.material as THREE.MeshBasicMaterial).opacity = 0.6 * (1 - p);
      group.position.y = Math.sin(elapsed * 3) * size * 0.08;
    },
    dispose() {
      disposeGroup(group);
    },
  };
}
