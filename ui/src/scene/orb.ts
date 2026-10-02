import * as THREE from "three";
import { Line2 } from "three/examples/jsm/lines/Line2.js";
import { LineGeometry } from "three/examples/jsm/lines/LineGeometry.js";
import { LineMaterial } from "three/examples/jsm/lines/LineMaterial.js";
import { additive, glowTexture, tickPairs, segments, TAU } from "./geometry";
import { Tinter } from "./tint";
import { clamp, type Motion } from "../motion";
import type { Frame, StepState } from "../protocol";

/** The voice, made visible: a luminous orb of concentric rings in the manner of JARVIS's own. Close, glowing, slightly wavering rings ride the real
 *  audio (yours while it listens, its own while it speaks); a ring of ticks turns; a bright arc is the goal's progress with a node per real step.
 *  A calm breath when idle, quick when it thinks, a swell when it speaks. Everything that moves is driven by real state. */
const N = 192;
const STEP_ROLE: Record<StepState, "accent" | "hot" | "ok" | "bad" | "warn"> = { pending: "accent", running: "hot", waiting: "warn", ran: "accent", verified: "ok", denied: "bad", failed: "bad", "rolled back": "warn" };

class WaveRing {
  readonly line: Line2;
  private readonly geo = new LineGeometry();
  private readonly pos = new Float32Array((N + 1) * 3);
  constructor(readonly radius: number, readonly mat: LineMaterial) {
    this.geo.setPositions(this.pos);
    this.line = new Line2(this.geo, mat);
  }
  /** `amp` is how far the ring may wander from a perfect circle; `speed`/`phase` set the character of the waves. */
  update(t: number, amp: number, speed: number, phase: number, hist?: number[]) {
    for (let i = 0; i <= N; i++) {
      const a = (i / N) * TAU;
      let w = Math.sin(a * 3 + t * speed + phase) * 0.5 + Math.sin(a * 5 - t * speed * 1.3 + phase * 2) * 0.3 + Math.sin(a * 8 + t * speed * 0.7 + phase * 3) * 0.2 + Math.sin(a * 13 - t * speed * 2.1) * 0.12;
      if (hist) w = w * 0.55 + (hist[Math.floor((i % N) / N * hist.length)] ?? 0) * 1.6;
      const r = this.radius + w * amp;
      this.pos[i * 3] = Math.cos(a) * r;
      this.pos[i * 3 + 1] = Math.sin(a) * r;
      this.pos[i * 3 + 2] = 0;
    }
    this.geo.setPositions(this.pos);
  }
}

export class Orb {
  readonly group = new THREE.Group();
  private readonly mats: LineMaterial[] = [];
  private readonly waves: WaveRing[];
  private readonly tickRing: THREE.LineSegments;
  private readonly arcs: Line2[] = [];
  private readonly arcGeo: LineGeometry[] = [];
  private readonly core: THREE.Sprite;
  private readonly hot: THREE.Sprite;
  private readonly halo: THREE.Sprite;
  private readonly inner: Line2;
  private readonly outer: Line2;
  private readonly progress: Line2;
  private readonly progressGeo = new LineGeometry();
  private readonly nodes: THREE.Sprite[] = [];
  private readonly ripples: THREE.Line[] = [];
  private readonly shockLine: THREE.Line;
  private hist: number[] = new Array(96).fill(0);
  private histAcc = 0;
  private level = 0;
  private prog = 0;
  private sig = "";
  private glowTex: THREE.Texture;

  constructor(private readonly tint: Tinter, glow: THREE.Texture) {
    this.glowTex = glow;
    const thick = (px: number, role: "accent" | "hot", k: number, op: number) => {
      const m = new LineMaterial({ color: 0xffffff, linewidth: px, transparent: true, opacity: op, blending: THREE.AdditiveBlending, depthWrite: false });
      this.mats.push(m);
      tint.add(role, k, (c, kk) => m.color.copy(c).multiplyScalar(kk));
      return m;
    };
    const circle = (r: number, m: LineMaterial) => {
      const g = new LineGeometry();
      const p: number[] = [];
      for (let i = 0; i <= 160; i++) p.push(Math.cos((i / 160) * TAU) * r, Math.sin((i / 160) * TAU) * r, 0);
      g.setPositions(p);
      return new Line2(g, m);
    };
    // the voice rings: three close, wavering circles, brightest in the middle
    this.waves = [
      new WaveRing(1.15, thick(1.0, "accent", 0.5, 0.55)), new WaveRing(1.2, thick(1.2, "accent", 0.8, 0.7)), new WaveRing(1.25, thick(1.7, "hot", 0.9, 0.9)),
      new WaveRing(1.3, thick(1.2, "accent", 0.8, 0.7)), new WaveRing(1.35, thick(1.0, "accent", 0.5, 0.5)),
    ];
    this.waves.forEach((w) => this.group.add(w.line));
    this.inner = circle(0.78, thick(1.4, "accent", 0.7, 0.8));
    this.outer = circle(1.62, thick(1, "accent", 0.35, 0.55));
    this.group.add(this.inner, this.outer);
    // rotating arcs: bright segments that chase round the orb (they speed up while it works)
    for (let i = 0; i < 3; i++) {
      const g = new LineGeometry();
      const p: number[] = [];
      const span = [70, 40, 28][i]! * (Math.PI / 180);
      const r = [0.98, 1.46, 1.74][i]!;
      for (let k = 0; k <= 24; k++) p.push(Math.cos((k / 24) * span) * r, Math.sin((k / 24) * span) * r, 0);
      g.setPositions(p);
      const l = new Line2(g, thick([2.2, 1.8, 1.4][i]!, "hot", [0.8, 0.6, 0.5][i]!, [0.9, 0.8, 0.7][i]!));
      this.arcs.push(l);
      this.arcGeo.push(g);
      this.group.add(l);
    }
    this.tickRing = segments(tickPairs(1.52, 1.57, 96, 8, 0.05), additive(new THREE.LineBasicMaterial({ color: 0xffffff, opacity: 0.6 })));
    tint.material(this.tickRing.material as THREE.LineBasicMaterial, "accent", 0.8);
    this.group.add(this.tickRing);
    // core and halo
    this.halo = new THREE.Sprite(additive(new THREE.SpriteMaterial({ map: glow, color: 0xffffff, opacity: 0.45 })));
    this.core = new THREE.Sprite(additive(new THREE.SpriteMaterial({ map: glow, color: 0xffffff, opacity: 0.9 })));
    this.hot = new THREE.Sprite(additive(new THREE.SpriteMaterial({ map: glow, color: 0xffffff, opacity: 1 })));
    tint.material(this.halo.material as THREE.SpriteMaterial, "accent", 1);
    tint.material(this.core.material as THREE.SpriteMaterial, "accent", 1);
    tint.material(this.hot.material as THREE.SpriteMaterial, "white", 1);
    this.group.add(this.halo, this.core, this.hot);
    // the goal's progress: a bright arc and a node per real step (built when the pipeline changes)
    this.progress = new Line2(this.progressGeo, thick(3.4, "hot", 1, 1));
    this.progressGeo.setPositions([0, 0, 0, 0.001, 0, 0]);
    this.progress.visible = false;
    this.group.add(this.progress);
    // ripples + shockwave
    for (let i = 0; i < 6; i++) {
      const l = new THREE.Line(new THREE.BufferGeometry().setFromPoints(Array.from({ length: 97 }, (_, k) => new THREE.Vector3(Math.cos((k / 96) * TAU), Math.sin((k / 96) * TAU), 0))),
        additive(new THREE.LineBasicMaterial({ color: 0xffffff, opacity: 0 })));
      l.visible = false;
      this.ripples.push(l);
      this.group.add(l);
    }
    this.shockLine = new THREE.Line(this.ripples[0]!.geometry.clone(), additive(new THREE.LineBasicMaterial({ color: 0xffffff, opacity: 0 })));
    this.shockLine.visible = false;
    this.group.add(this.shockLine);
  }

  setResolution(w: number, h: number) {
    for (const m of this.mats) m.resolution.set(w, h);
  }

  private buildSteps(f: Frame) {
    const steps = f.pipeline.steps;
    const sig = JSON.stringify([steps.map((s) => s.state), f.pipeline.sealed]);
    if (sig === this.sig) return;
    this.sig = sig;
    for (const n of this.nodes) n.removeFromParent();
    this.nodes.length = 0;
    steps.forEach((s, i) => {
      const a = Math.PI / 2 - ((i + 0.5) / steps.length) * TAU;
      const sp = new THREE.Sprite(additive(new THREE.SpriteMaterial({ map: this.glowTex, color: 0xffffff, opacity: 1 })));
      sp.position.set(Math.cos(a) * 1.62, Math.sin(a) * 1.62, 0.02);
      sp.userData = { state: s.state };
      this.tint.material(sp.material as THREE.SpriteMaterial, STEP_ROLE[s.state] ?? "accent", s.state === "pending" ? 0.45 : 1);
      this.nodes.push(sp);
      this.group.add(sp);
    });
  }

  update(f: Frame, m: Motion, dt: number, tint: Tinter) {
    const v = f.voice;
    const target = v.state === "speaking" ? v.speak : v.state === "hearing" ? v.level : 0;
    this.level += (clamp(target) - this.level) * (1 - Math.exp(-dt * 16));
    this.histAcc += dt;
    while (this.histAcc >= 1 / 30) {
      this.histAcc -= 1 / 30;
      this.hist.shift();
      this.hist.push((this.hist[this.hist.length - 1] ?? 0) * 0.5 + this.level * 0.5);
    }
    const thinking = v.state === "thinking" || m.mode === "working";
    const t = m.t;
    const lvl = m.coreLevel();
    const breath = 0.5 + 0.5 * Math.sin(t * (thinking ? 2.4 : 0.9));
    // the rings: a quiet breath, a ripple that follows the voice
    const base = 0.008 + 0.012 * breath + (thinking ? 0.018 : 0);
    const swell = 0.11 * this.level;
    const mid = Math.floor(this.waves.length / 2);
    this.waves.forEach((w, i) => {
      const k = 1 - Math.abs(i - mid) * 0.18;                                              // the middle ring wanders furthest
      w.update(t, (base + swell * (0.7 + 0.3 * k)) * k, 1.1 + i * 0.22 + this.level * 2.4, i * 1.3, i === mid + 1 && this.level > 0.02 ? this.hist : undefined);
    });
    const op = 0.6 + 0.4 * clamp(lvl / 1.2);
    this.waves.forEach((w, i) => (w.mat.opacity = clamp((i === mid ? 0.95 : 0.55) * op + this.level * 0.25)));
    // arcs chase round; the faster the state, the faster they run
    const sp = 0.25 + m.v.spin * 1.4;
    this.arcs[0]!.rotation.z = m.t * sp;
    this.arcs[1]!.rotation.z = -m.t * sp * 0.7 + 1.2;
    this.arcs[2]!.rotation.z = m.t * sp * 0.45 + 3.4;
    this.tickRing.rotation.z = -m.t * (0.04 + m.v.spin * 0.12);
    this.inner.scale.setScalar(1 + 0.02 * breath + 0.05 * this.level);
    // core + halo breathe with the state and swell with sound
    const c = 0.5 + 0.3 * lvl + 0.35 * this.level + 0.3 * m.flare;
    this.core.scale.setScalar(0.55 * c);
    this.hot.scale.setScalar(0.2 + 0.12 * c);
    this.halo.scale.setScalar(2.1 + 0.8 * c);
    (this.halo.material as THREE.SpriteMaterial).opacity = clamp(0.14 + 0.16 * lvl + 0.2 * this.level);
    // progress arc and step nodes: only while there is a goal
    const has = f.pipeline.plan !== "none" || f.pipeline.steps.length > 0;
    this.outer.visible = has;
    this.progress.visible = has && f.progress > 0.005;
    this.buildSteps(f);
    this.nodes.forEach((n) => (n.visible = has));
    this.prog += (f.progress - this.prog) * (1 - Math.exp(-dt * 4));
    if (this.progress.visible) {
      const pts: number[] = [];
      const end = clamp(this.prog) * TAU;
      const nn = Math.max(4, Math.ceil(end * 20));
      for (let k = 0; k <= nn; k++) {
        const a = Math.PI / 2 - (k / nn) * end;
        pts.push(Math.cos(a) * 1.62, Math.sin(a) * 1.62, 0.01);
      }
      this.progressGeo.setPositions(pts);
    }
    for (const n of this.nodes) {
      const st = n.userData["state"] as StepState;
      n.scale.setScalar(st === "running" ? 0.16 + 0.05 * Math.sin(t * 6) : 0.1);
    }
    // ripples (one per real event) and the verified shockwave
    this.ripples.forEach((l, i) => {
      const r = m.ripples[i];
      l.visible = !!r;
      if (!r) return;
      const u = clamp((t - r.t0) / 1.6);
      l.scale.setScalar(1.35 + 1.5 * (1 - (1 - u) ** 2));
      const mat = l.material as THREE.LineBasicMaterial;
      mat.color.copy(r.kind === "ok" ? tint.ok : r.kind === "bad" ? tint.bad : r.kind === "warn" ? tint.warn : tint.accent);
      mat.opacity = 0.55 * (1 - u) ** 1.6;
    });
    if (m.shock !== null) {
      this.shockLine.visible = true;
      this.shockLine.scale.setScalar(1.3 + 2.4 * (1 - (1 - clamp(m.shock)) ** 3));
      const mat = this.shockLine.material as THREE.LineBasicMaterial;
      mat.color.copy(tint.ok);
      mat.opacity = 0.7 * (1 - m.shock) ** 1.4;
    } else this.shockLine.visible = false;
    // the whole orb: a small tilt that sways, so the light has depth
    this.group.rotation.set(-0.12 + Math.sin(t * 0.23) * 0.04, Math.sin(t * 0.17) * 0.1, 0);
    this.group.scale.setScalar(1 - 0.06 * (m.mode === "stopping" ? 1 : 0));
  }
}
