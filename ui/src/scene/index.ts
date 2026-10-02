import * as THREE from "three";
import { Motion, clamp, lerp } from "../motion";
import type { Frame } from "../protocol";
import type { Theme } from "../theme";
import { glowTexture } from "./geometry";
import { Gyro } from "./gyro";
import { Particles } from "./particles";
import { Post } from "./post";
import { Reactor } from "./reactor";
import { Stage } from "./stage";
import { Tinter } from "./tint";

export interface Projected { x: number; y: number; visible: boolean }

/** The whole hologram. `update(frame, dt)` moves the real state into the picture; `render()` draws it. Nothing in here invents data. */
export class HoloScene {
  readonly motion: Motion;
  readonly tint = new Tinter();
  private readonly renderer: THREE.WebGLRenderer;
  private readonly scene = new THREE.Scene();
  private readonly camera = new THREE.PerspectiveCamera(32, 1, 0.1, 100);
  private readonly post: Post;
  private readonly reactor: Reactor;
  private readonly gyro: Gyro;
  private readonly stage: Stage;
  private readonly particles: Particles;
  private readonly world = new THREE.Group();
  private pointer = new THREE.Vector2();
  private look = new THREE.Vector2();
  private level = 0;
  private lastMode = "";
  private pipelineSig = "";
  private frameMs: number[] = [];
  quality = 0;
  private w = 1;
  private h = 1;

  constructor(readonly canvas: HTMLCanvasElement, private theme: Theme, private readonly reduced = false) {
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false, powerPreference: "high-performance" });
    this.renderer.setClearColor(new THREE.Color(theme.colors["void"] ?? "#02060b"), 1);
    this.renderer.toneMapping = THREE.NoToneMapping;
    this.motion = new Motion(theme);
    const glow = glowTexture();
    this.reactor = new Reactor(this.tint, glow);
    this.gyro = new Gyro(this.tint, glow);
    this.stage = new Stage(this.tint);
    this.particles = new Particles(this.tint, reduced ? 350 : 900);
    this.world.add(this.stage.group, this.reactor.group, this.gyro.group, this.particles.points);
    this.scene.add(this.world);
    this.camera.position.set(0, 1.2, 8.6);
    this.camera.lookAt(0, -0.55, 0);
    this.post = new Post(this.renderer, this.scene, this.camera, 800, 500);
    this.resize(canvas.clientWidth || 800, canvas.clientHeight || 500, Math.min(window.devicePixelRatio || 1, 2));
    this.motion.restart();
  }

  setTheme(t: Theme) {
    this.theme = t;
  }

  setPointer(nx: number, ny: number) {
    this.pointer.set(nx, ny);
  }

  /** The canvas fills the window; the object sits in the middle with room for the panels either side. */
  resize(w: number, h: number, dpr: number) {
    this.w = Math.max(1, w);
    this.h = Math.max(1, h);
    const pr = this.quality >= 2 ? 1 : dpr;
    this.renderer.setPixelRatio(pr);
    this.renderer.setSize(this.w, this.h, false);
    this.post.setSize(this.w, this.h);
    this.camera.aspect = this.w / this.h;
    // keep the whole object in view on tall or narrow windows
    this.camera.fov = this.camera.aspect < 1.1 ? 32 + (1.1 - this.camera.aspect) * 28 : 32;
    this.camera.updateProjectionMatrix();
    const res = new THREE.Vector2(this.w * pr, this.h * pr);
    this.reactor.setResolution(res.x, res.y);
    this.gyro.setResolution(res.x, res.y);
    this.stage.setResolution(res.x, res.y);
    this.particles.setPixelRatio(pr);
  }

  update(f: Frame, dt: number) {
    const m = this.motion;
    m.feed(f);
    m.advance(this.reduced ? dt * 0.3 : dt);
    if (this.lastMode !== f.mode) {
      if (this.lastMode) this.post.kick(f.mode === "bad" || f.mode === "stopping" ? 1 : 0.7);
      this.lastMode = f.mode;
    }
    const sig = JSON.stringify([f.pipeline.plan, f.pipeline.steps.map((s) => s.state), f.pipeline.checks.map((c) => c.ok), f.pipeline.sealed]);
    if (sig !== this.pipelineSig) {
      this.pipelineSig = sig;
      this.gyro.set(f.pipeline);
    }
    const v = f.voice;
    const target = v.state === "speaking" ? v.speak : v.state === "hearing" || v.state === "listening" ? v.level : 0;
    this.level = lerp(this.level, clamp(target), 1 - Math.exp(-dt * 14));
    if (v.state === "speaking") m.flare = Math.max(m.flare, 0.5 * clamp(v.speak));
    this.tint.set(m.accent(), m.hot());
    this.tint.apply();
    this.reactor.update(m, dt);
    this.gyro.update(m);
    this.stage.update(m, dt, this.level, this.tint);
    this.particles.update(m, this.theme.effects.particles * (this.quality >= 2 ? 0.4 : 1));
    // camera: a slow breath, and a little parallax toward the pointer so the hologram has depth
    this.look.lerp(this.pointer, 1 - Math.exp(-dt * 3));
    const par = this.theme.effects.parallax * (this.reduced ? 0.2 : 1);
    this.camera.position.x = this.look.x * 0.9 * par;
    this.camera.position.y = 1.2 + this.look.y * 0.5 * par + Math.sin(m.t * 0.35) * 0.04;
    this.camera.lookAt(0, -0.55, 0);
    // the object: tilted toward the viewer, a slow swing, and a lift while it is working
    this.reactor.group.rotation.set(-0.95 + Math.sin(m.t * 0.21) * 0.06, Math.sin(m.t * 0.17) * 0.35, 0);
    this.reactor.group.position.y = -0.1 + Math.sin(m.t * 0.6) * 0.03;
    this.reactor.group.scale.setScalar(1.18);
    this.gyro.group.position.copy(this.reactor.group.position);
    this.gyro.group.scale.setScalar(1.18);
    this.post.update(m.t, dt, this.theme.effects.bloom * m.v.bloom * (this.quality >= 3 ? 0 : 1), this.theme.effects);
  }

  render(dtMs: number) {
    const t0 = performance.now();
    if (this.quality >= 3) this.renderer.render(this.scene, this.camera);
    else this.post.render(dtMs / 1000);
    this.frameMs.push(performance.now() - t0 + 0);
    if (this.frameMs.length >= 60) {
      const avg = this.frameMs.reduce((a, b) => a + b, 0) / this.frameMs.length;
      this.frameMs = [];
      if (avg > 30 && this.quality < 3) {
        this.quality++;
        this.resize(this.w, this.h, Math.min(window.devicePixelRatio || 1, 2));
      }
    }
  }

  /** Screen position (CSS pixels) of a point in the scene, for the callout lines. */
  project(name: "core" | "act" | "verify" | "plan"): Projected {
    const v = new THREE.Vector3();
    if (name === "core") this.reactor.corePosition(v);
    else {
      const r = this.gyro.radii[name === "verify" ? 0 : name === "act" ? 1 : 2]!;
      v.set(r * 0.72, r * 0.18, 0).applyMatrix4(this.gyro.group.matrixWorld);
    }
    v.project(this.camera);
    return { x: (v.x * 0.5 + 0.5) * this.w, y: (-v.y * 0.5 + 0.5) * this.h, visible: v.z < 1 };
  }

  dispose() {
    this.renderer.dispose();
  }
}
