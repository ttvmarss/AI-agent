import type { Frame, Mode } from "./protocol";
import { mixRgb, hexToRgb, type Theme, type ModeParams } from "./theme";

const TAU = Math.PI * 2;
export const clamp = (x: number, lo = 0, hi = 1) => (x !== x ? lo : x < lo ? lo : x > hi ? hi : x);
export const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
export const easeOut = (x: number) => 1 - (1 - clamp(x)) ** 3;
export const smooth = (x: number) => {
  const k = clamp(x);
  return k * k * (3 - 2 * k);
};

export interface Bolt { a: number; age: number; life: number; offs: number[] }
export interface Ripple { t0: number; kind: "info" | "ok" | "warn" | "bad" }

/** The animation state behind the scene. Pure maths, no browser: every behaviour is unit-tested.
 *  State changes glide (STOP excepted: a kill switch must look like one). Real events flare the core and send ripples; a verified goal
 *  sends a shockwave. */
export class Motion {
  readonly keys: (keyof ModeParams)[];
  mode: Mode = "starting";
  v: ModeParams;
  persona: number;
  t = 0;
  rotA = 0; // slow spin, radians
  rotB = 0; // scale spin
  rotC = 0; // counter spin
  sweep = 0;
  flare = 0;
  shock: number | null = null;
  power = 0;
  boot = 0;
  bootSeconds = 3.8;
  ripples: Ripple[] = [];
  bolts: Bolt[] = [];
  private boltAcc = 0;
  private lastLogId = -1;
  private lastShock = 0;
  private seeded = false;

  constructor(readonly theme: Theme) {
    this.keys = Object.keys(theme.modes.idle) as (keyof ModeParams)[];
    this.v = { ...theme.modes.starting };
    this.persona = theme.modes.starting.persona;
  }

  setMode(mode: Mode) {
    if (mode !== this.mode) {
      if (mode === "starting") this.restart();
      if (mode === "bad" || mode === "stopping") this.ripple(mode === "bad" ? "bad" : "warn", true);
      this.mode = mode;
    }
  }

  restart() {
    this.power = 0;
    this.boot = 0;
  }

  pulse(amount = 1) {
    this.flare = Math.min(1.5, this.flare + 0.7 * amount);
    for (let i = 0; i < (amount >= 0.8 ? 2 : 1); i++) this.spawnBolt();
  }

  ripple(kind: Ripple["kind"] = "info", force = false) {
    const last = this.ripples[this.ripples.length - 1];
    if (!force && last && this.t - last.t0 < 0.14) return;
    this.ripples = [...this.ripples, { t0: this.t, kind }].slice(-6);
  }

  trigger() {
    this.shock = 0;
    this.ripple("ok", true);
    this.pulse(1.4);
  }

  /** Feed the newest frame: set the mode and turn REAL events (new log lines, a verified goal) into flares, ripples and a shockwave. */
  feed(f: Frame) {
    this.setMode(f.mode);
    const newest = f.log.length ? f.log[f.log.length - 1]!.id : -1;
    if (!this.seeded) {
      this.seeded = true;                         // history that existed before we connected is not an event
      this.lastLogId = newest;
      this.lastShock = f.shock;
    } else {
      for (const l of f.log) {
        if (l.id > this.lastLogId) {
          this.pulse(0.8);
          this.ripple(l.level === "ok" ? "ok" : l.level === "warn" ? "warn" : l.level === "bad" ? "bad" : "info");
        }
      }
      this.lastLogId = Math.max(this.lastLogId, newest);
      if (f.shock > this.lastShock) this.trigger();
      this.lastShock = f.shock;
    }
  }

  private spawnBolt() {
    if (this.bolts.length >= 5) return;
    const offs: number[] = [];
    for (let i = 0; i <= 9; i++) offs.push(i === 0 || i === 9 ? 0 : (Math.random() - 0.5) * 0.1);
    this.bolts.push({ a: Math.random() * TAU, age: 0, life: 0.18 + Math.random() * 0.18, offs });
  }

  advance(dt: number) {
    if (!Number.isFinite(dt)) return;
    dt = clamp(dt, 0, 0.25);
    if (dt <= 0) return;
    this.t += dt;
    const tgt = this.theme.modes[this.mode];
    const fast = this.mode === "stopping";
    const k = 1 - Math.exp(-dt * (fast ? 12 : 3.5));
    for (const key of this.keys) {
      if (key === "persona") continue;
      this.v[key] += (tgt[key] - this.v[key]) * k;
    }
    this.persona += (tgt.persona - this.persona) * (1 - Math.exp(-dt * (fast ? 12 : this.theme.persona.rate)));
    this.power = Math.min(1, this.power + dt / 2.2);
    this.boot = Math.min(1, this.boot + dt / this.bootSeconds);
    this.rotA = (this.rotA + this.v.spin * dt) % TAU;
    this.rotB = (this.rotB + this.v.spin * 0.35 * dt) % TAU;
    this.rotC = (this.rotC - (this.v.spin * 0.6 + 0.05) * dt) % TAU;
    this.sweep = (this.sweep + this.v.sweep * dt) % TAU;
    this.flare = Math.max(0, this.flare - dt * 1.8);
    if (this.shock !== null) {
      this.shock += dt / 1.4;
      if (this.shock >= 1) this.shock = null;
    }
    this.ripples = this.ripples.filter((r) => this.t - r.t0 < 1.6);
    this.boltAcc += dt * this.v.bolts * (1 + 2 * this.flare);
    while (this.boltAcc >= 1) {
      this.boltAcc -= 1;
      this.spawnBolt();
    }
    this.boltAcc = Math.min(this.boltAcc, 2);
    for (const b of this.bolts) b.age += dt;
    this.bolts = this.bolts.filter((b) => b.age < b.life);
  }

  /** Core brightness 0..~1.6: the state's level, a slow pulse, a flicker when failing, and the flare from real events. */
  coreLevel(): number {
    const base = this.v.core * (1 + 0.05 * Math.sin(this.t * TAU * (this.mode === "working" ? 1 : 0.3)));
    const flick = this.mode === "bad" ? 1 - 0.06 * (0.5 + 0.5 * Math.sin(this.t * 47) * Math.sin(this.t * 13)) : 1;
    return base * flick * (0.25 + 0.75 * easeOut(this.power)) + 0.45 * this.flare;
  }

  /** How far element k of the boot sequence has drawn in, 0..1. Indices past the end arrive with the last one, never never. */
  reveal(k: number, delay = 0.055, span = 0.32): number {
    return easeOut((this.boot - Math.min(k * delay, Math.max(0, 1 - span))) / span);
  }

  /** The accent colour of the mind in charge (RGB 0..255): JARVIS ice-blue ... FRIDAY amber. */
  accent(): [number, number, number] {
    return mixRgb(hexToRgb(this.theme.colors["jarvis"] ?? "#59d8ff"), hexToRgb(this.theme.colors["friday"] ?? "#ffa52e"), this.persona);
  }

  hot(): [number, number, number] {
    return mixRgb(hexToRgb(this.theme.colors["jarvisHot"] ?? "#d6f6ff"), hexToRgb(this.theme.colors["fridayHot"] ?? "#ffe2b0"), this.persona);
  }
}
