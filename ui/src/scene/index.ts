import * as THREE from "three";
import { Motion, clamp } from "../motion";
import type { Frame } from "../protocol";
import type { Theme } from "../theme";
import { glowTexture } from "./geometry";
import { Orb } from "./orb";
import { Particles } from "./particles";
import { Post } from "./post";
import { Tinter } from "./tint";

/** The whole picture: the voice orb on a dark field with a little dust. `update(frame, dt)` moves the real state into it; `render()` draws it. */
export class HoloScene {
  readonly motion: Motion;
  readonly tint = new Tinter();
  private readonly renderer: THREE.WebGLRenderer;
  private readonly scene = new THREE.Scene();
  private readonly camera = new THREE.PerspectiveCamera(30, 1, 0.1, 100);
  private readonly post: Post;
  private readonly orb: Orb;
  private readonly particles: Particles;
  private pointer = new THREE.Vector2();
  private look = new THREE.Vector2();
  private lastMode = "";
  private frameMs: number[] = [];
  quality = 0;
  private w = 1;
  private h = 1;

  constructor(readonly canvas: HTMLCanvasElement, private theme: Theme, private readonly reduced = false) {
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false, powerPreference: "high-performance" });
    this.renderer.setClearColor(new THREE.Color(theme.colors["void"] ?? "#02060c"), 1);
    this.renderer.toneMapping = THREE.NoToneMapping;
    this.motion = new Motion(theme);
    const glow = glowTexture();
    this.orb = new Orb(this.tint, glow);
    this.particles = new Particles(this.tint, reduced ? 120 : 260);
    this.scene.add(this.orb.group, this.particles.points);
    this.camera.position.set(0, 0, 11.2);
    this.camera.lookAt(0, 0, 0);
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

  resize(w: number, h: number, dpr: number) {
    this.w = Math.max(1, w);
    this.h = Math.max(1, h);
    const pr = this.quality >= 2 ? 1 : dpr;
    this.renderer.setPixelRatio(pr);
    this.renderer.setSize(this.w, this.h, false);
    this.post.setSize(this.w, this.h);
    this.camera.aspect = this.w / this.h;
    // the orb is about 4 units across: keep all of it in view on tall or narrow windows
    this.camera.fov = this.camera.aspect < 1.2 ? 30 + (1.2 - this.camera.aspect) * 30 : 30;
    this.camera.updateProjectionMatrix();
    this.orb.setResolution(this.w * pr, this.h * pr);
    this.particles.setPixelRatio(pr);
  }

  update(f: Frame, dt: number) {
    const m = this.motion;
    m.feed(f);
    m.advance(this.reduced ? dt * 0.3 : dt);
    if (this.lastMode !== f.mode) {
      if (this.lastMode) this.post.kick(f.mode === "bad" ? 1 : 0.5);
      this.lastMode = f.mode;
    }
    if (f.voice.state === "speaking") m.flare = Math.max(m.flare, 0.35 * clamp(f.voice.speak));
    this.tint.set(m.accent(), m.hot());
    this.tint.apply();
    // a state that needs attention is tinted for it; nothing else changes hue
    if (f.mode === "waiting") this.tint.accent.lerp(this.tint.warn, 0.55);
    if (f.mode === "bad") this.tint.accent.lerp(this.tint.bad, 0.7);
    if (f.mode === "ok") this.tint.accent.lerp(this.tint.ok, 0.45);
    this.tint.apply();
    this.orb.update(f, m, dt, this.tint);
    this.particles.update(m, this.theme.effects.particles);
    this.look.lerp(this.pointer, 1 - Math.exp(-dt * 3));
    const par = this.theme.effects.parallax * (this.reduced ? 0.2 : 1);
    this.camera.position.x = this.look.x * 0.5 * par;
    this.camera.position.y = this.look.y * 0.3 * par;
    this.camera.lookAt(0, 0, 0);
    this.post.update(m.t, dt, this.theme.effects.bloom * m.v.bloom * (this.quality >= 3 ? 0 : 1), this.theme.effects);
  }

  render(dtMs: number) {
    const t0 = performance.now();
    if (this.quality >= 3) this.renderer.render(this.scene, this.camera);
    else this.post.render(dtMs / 1000);
    this.frameMs.push(performance.now() - t0);
    if (this.frameMs.length >= 60) {
      const avg = this.frameMs.reduce((a, b) => a + b, 0) / this.frameMs.length;
      this.frameMs = [];
      if (avg > 30 && this.quality < 3) {
        this.quality++;
        this.resize(this.w, this.h, Math.min(window.devicePixelRatio || 1, 2));
      }
    }
  }

  dispose() {
    this.renderer.dispose();
  }
}
