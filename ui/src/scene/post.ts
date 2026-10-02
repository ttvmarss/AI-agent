import * as THREE from "three";
import { EffectComposer } from "three/examples/jsm/postprocessing/EffectComposer.js";
import { RenderPass } from "three/examples/jsm/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/examples/jsm/postprocessing/UnrealBloomPass.js";
import { ShaderPass } from "three/examples/jsm/postprocessing/ShaderPass.js";
import { OutputPass } from "three/examples/jsm/postprocessing/OutputPass.js";

/** Post-processing: bloom (the light that spills from bright lines), then the projector's imperfections: a hair of chromatic aberration at the
 *  edges, scanlines, a vignette, film grain, and a horizontal-slice glitch that fires on state changes. */
const FilmShader = {
  uniforms: { tDiffuse: { value: null as THREE.Texture | null }, uTime: { value: 0 }, uRes: { value: new THREE.Vector2(1, 1) }, uAberr: { value: 0.0016 }, uScan: { value: 1 },
              uVignette: { value: 1 }, uGrain: { value: 0.012 }, uGlitch: { value: 0 } },
  vertexShader: `varying vec2 vUv; void main(){ vUv=uv; gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0); }`,
  fragmentShader: `
    varying vec2 vUv; uniform sampler2D tDiffuse; uniform float uTime; uniform vec2 uRes; uniform float uAberr; uniform float uScan; uniform float uVignette; uniform float uGrain; uniform float uGlitch;
    float h(float n){ return fract(sin(n*127.1)*43758.5453); }
    void main(){
      vec2 uv = vUv;
      float band = floor(uv.y * 28.0) + floor(uTime * 14.0);
      float slice = step(0.82, h(band)) * uGlitch;
      uv.x += slice * (h(band + 3.0) - 0.5) * 0.06;
      vec2 d = uv - 0.5;
      float k = uAberr * (0.35 + dot(d, d) * 2.2) + slice * 0.006;
      vec3 col;
      col.r = texture2D(tDiffuse, uv + d * k).r;
      col.g = texture2D(tDiffuse, uv).g;
      col.b = texture2D(tDiffuse, uv - d * k).b;
      float sl = 0.5 + 0.5 * sin(uv.y * uRes.y * 1.6);
      col *= 1.0 - uScan * 0.10 * sl;
      col *= mix(1.0, smoothstep(0.95, 0.12, length(d * vec2(1.0, 1.1))), uVignette);
      col += (h(dot(uv, vec2(12.9898, 78.233)) + uTime) - 0.5) * uGrain;
      gl_FragColor = vec4(col, 1.0);
    }`,
};

export class Post {
  readonly composer: EffectComposer;
  readonly bloom: UnrealBloomPass;
  readonly film: ShaderPass;
  private glitch = 0;
  constructor(renderer: THREE.WebGLRenderer, scene: THREE.Scene, camera: THREE.Camera, w: number, h: number) {
    this.composer = new EffectComposer(renderer);
    this.composer.addPass(new RenderPass(scene, camera));
    this.bloom = new UnrealBloomPass(new THREE.Vector2(w, h), 0.7, 0.6, 0.22);
    this.composer.addPass(this.bloom);
    this.film = new ShaderPass(FilmShader);
    this.composer.addPass(this.film);
    this.composer.addPass(new OutputPass());
    this.setSize(w, h);
  }
  setSize(w: number, h: number) {
    this.composer.setSize(w, h);
    this.film.uniforms["uRes"]!.value.set(w, h);
  }
  kick(amount = 1) {
    this.glitch = Math.max(this.glitch, amount);
  }
  update(t: number, dt: number, bloom: number, effects: { glitch: number; scanlines: number }) {
    this.glitch = Math.max(0, this.glitch - dt * 3.2);
    this.film.uniforms["uTime"]!.value = t;
    this.film.uniforms["uGlitch"]!.value = this.glitch * effects.glitch;
    this.film.uniforms["uScan"]!.value = effects.scanlines;
    this.bloom.strength = 0.7 * bloom;
  }
  render(dt: number) {
    this.composer.render(dt);
  }
}
