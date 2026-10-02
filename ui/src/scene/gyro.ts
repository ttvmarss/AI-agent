import * as THREE from "three";
import { Line2 } from "three/examples/jsm/lines/Line2.js";
import { LineGeometry } from "three/examples/jsm/lines/LineGeometry.js";
import { LineMaterial } from "three/examples/jsm/lines/LineMaterial.js";
import { additive, glowTexture, TAU } from "./geometry";
import { Tinter } from "./tint";
import type { Motion } from "../motion";
import type { Pipeline, StepState } from "../protocol";

/** The kernel's real pipeline as three tilted gyro rings: PLAN (outer), ACT (one arc per real step) and VERIFY (one arc per real check).
 *  A running step has a comet; a verified goal seals the VERIFY ring shut. Arc colour is the step's real state. */
const STATE_ROLE: Record<StepState | "idle", { role: "accent" | "hot" | "ok" | "bad" | "warn" | "white"; k: number; w: number }> = {
  idle: { role: "accent", k: 0.25, w: 1 }, pending: { role: "accent", k: 0.35, w: 1.6 }, running: { role: "hot", k: 1, w: 3 }, waiting: { role: "warn", k: 1, w: 3 },
  ran: { role: "accent", k: 0.85, w: 2.4 }, verified: { role: "ok", k: 1, w: 2.8 }, denied: { role: "bad", k: 1, w: 3 }, failed: { role: "bad", k: 1, w: 3 }, "rolled back": { role: "warn", k: 0.7, w: 2 },
};

class Ring {
  readonly group = new THREE.Group();
  private readonly arcs: Line2[] = [];
  private readonly comet: THREE.Sprite[] = [];
  private sig = "";
  private running: { start: number; span: number }[] = [];
  constructor(private readonly radius: number, private readonly mats: Map<string, LineMaterial>, private readonly tint: Tinter, glow: THREE.Texture, base: LineMaterial) {
    const pts: number[] = [];
    for (let i = 0; i <= 160; i++) pts.push(Math.cos((i / 160) * TAU) * radius, Math.sin((i / 160) * TAU) * radius, 0);
    const g = new LineGeometry();
    g.setPositions(pts);
    const track = new Line2(g, base);
    track.computeLineDistances();
    this.group.add(track);
    for (let i = 0; i < 4; i++) {
      const s = new THREE.Sprite(additive(new THREE.SpriteMaterial({ map: glow, color: 0xffffff, opacity: 1 - i * 0.22 })));
      tint.material(s.material as THREE.SpriteMaterial, "white", 1);
      s.visible = false;
      this.comet.push(s);
      this.group.add(s);
    }
  }

  set(states: (StepState | "idle")[], sealed = false) {
    const sig = states.join("|") + (sealed ? "!" : "");
    if (sig === this.sig) return;
    this.sig = sig;
    for (const a of this.arcs) {
      a.removeFromParent();
      a.geometry.dispose();
    }
    this.arcs.length = 0;
    this.running = [];
    const n = states.length;
    states.forEach((st, i) => {
      const full = n === 1;
      const span = full ? 360 : 360 / n - 7;
      const start = full ? 0 : (360 / n) * i;
      const pts: number[] = [];
      const steps = Math.max(8, Math.round(span / 3));
      for (let k = 0; k <= steps; k++) {
        const a = ((start + (span * k) / steps) * Math.PI) / 180;
        pts.push(Math.sin(a) * this.radius, Math.cos(a) * this.radius, 0);
      }
      const g = new LineGeometry();
      g.setPositions(pts);
      const m = this.mats.get(st) ?? this.mats.get("idle")!;
      const line = new Line2(g, m);
      line.computeLineDistances();
      this.arcs.push(line);
      this.group.add(line);
      if (st === "running") this.running.push({ start, span });
    });
  }

  update(t: number) {
    const r = this.running[0];
    for (let i = 0; i < this.comet.length; i++) {
      const s = this.comet[i]!;
      s.visible = !!r;
      if (!r) continue;
      const u = ((t * 0.55) % 1 + 1) % 1;
      const a = ((r.start + r.span * u - i * 5) * Math.PI) / 180;
      s.position.set(Math.sin(a) * this.radius, Math.cos(a) * this.radius, 0);
      s.scale.setScalar(0.16 * (1 - i * 0.2));
    }
  }
}

export class Gyro {
  readonly group = new THREE.Group();
  private readonly rings: Ring[];
  private readonly mats = new Map<string, LineMaterial>();
  private readonly all: LineMaterial[] = [];
  readonly radii = [1.6, 1.85, 2.1];

  constructor(tint: Tinter, glow: THREE.Texture) {
    for (const [state, spec] of Object.entries(STATE_ROLE)) {
      const m = new LineMaterial({ color: 0xffffff, linewidth: spec.w, transparent: true, opacity: 1, blending: THREE.AdditiveBlending, depthWrite: false });
      tint.add(spec.role, spec.k, (c, k) => m.color.copy(c).multiplyScalar(k));
      this.mats.set(state, m);
      this.all.push(m);
    }
    const base = new LineMaterial({ color: 0xffffff, linewidth: 1, transparent: true, opacity: 0.5, blending: THREE.AdditiveBlending, depthWrite: false, dashed: true, dashSize: 0.06, gapSize: 0.05 });
    tint.add("accent", 0.4, (c, k) => base.color.copy(c).multiplyScalar(k));
    this.all.push(base);
    this.rings = this.radii.map((r) => new Ring(r, this.mats, tint, glow, base));
    this.rings.forEach((r) => this.group.add(r.group));
    this.set({ plan: "none", steps: [], checks: [], sealed: false });
  }

  setResolution(w: number, h: number) {
    for (const m of this.all) m.resolution.set(w, h);
  }

  set(p: Pipeline) {
    const planStates: (StepState | "idle")[] = p.plan === "planning" ? ["running"] : p.plan === "ready" ? ["ran"] : p.plan === "failed" ? ["failed"] : ["idle"];
    this.rings[2]!.set(planStates);
    this.rings[1]!.set(p.steps.length ? p.steps.map((s) => s.state) : ["idle"]);
    this.rings[0]!.set(p.sealed ? ["verified"] : p.checks.length ? p.checks.map((c) => (c.ok ? "verified" : "failed")) : ["idle"]);
  }

  update(m: Motion) {
    // three gimbals on different axes, turning at different rates: the gyroscope of a workshop hologram
    const [verify, act, plan] = [this.rings[0]!, this.rings[1]!, this.rings[2]!];
    verify.group.rotation.set(1.05 + 0.08 * Math.sin(m.t * 0.3), 0.2, m.rotC * 0.5);
    act.group.rotation.set(0.65, -0.55 + 0.1 * Math.sin(m.t * 0.25 + 1), -m.rotA * 0.35 - 0.4);
    plan.group.rotation.set(1.35, 0.7, m.rotB * 0.9 + 0.8);
    for (const r of this.rings) r.update(m.t);
  }
}
