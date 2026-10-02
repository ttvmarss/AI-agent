import * as THREE from "three";
import { Tinter } from "./tint";
import type { Motion } from "../motion";

/** Dust in the projector light. All motion happens on the GPU (a seed per point; time and the state's flow in uniforms), so a thousand of
 *  them cost almost nothing. While it works they spiral inward (taking the goal in); otherwise they drift. */
const V = `
attribute vec4 seed; uniform float uTime; uniform float uFlow; uniform float uSpin; uniform float uSize; uniform float uPixel;
varying float vA;
void main(){
  float ph = fract(seed.w + uTime * (0.03 + 0.05 * seed.z));
  float r = seed.x * mix(1.0, ph, uFlow);
  float a = seed.y + uTime * (0.05 + 0.25 * uSpin) * (0.4 + seed.z) + (1.0 - r / 3.4) * uFlow * 2.5;
  float h = (seed.z - 0.5) * 4.6 * mix(1.0, 0.45 + 0.55 * ph, uFlow) + sin(uTime * 0.5 + seed.y * 7.0) * 0.08;
  vec4 mv = modelViewMatrix * vec4(cos(a) * r, h, sin(a) * r, 1.0);
  gl_Position = projectionMatrix * mv;
  gl_PointSize = uSize * uPixel * (0.6 + seed.z) * (6.0 / -mv.z);
  float edge = smoothstep(0.0, 0.12, ph) * smoothstep(1.0, 0.8, ph);
  vA = mix(0.55, edge, uFlow) * (0.35 + 0.65 * seed.z) * smoothstep(0.2, 1.0, r);
}`;
const F = `varying float vA; uniform vec3 uColor; uniform float uAlpha; void main(){ float d = length(gl_PointCoord - 0.5) * 2.0; float a = smoothstep(1.0, 0.0, d); gl_FragColor = vec4(uColor, a * a * vA * uAlpha); }`;

export class Particles {
  readonly points: THREE.Points;
  private readonly mat: THREE.ShaderMaterial;
  constructor(tint: Tinter, count = 900) {
    const seed = new Float32Array(count * 4);
    for (let i = 0; i < count; i++) {
      seed[i * 4] = 0.9 + Math.pow(Math.random(), 0.7) * 2.5;
      seed[i * 4 + 1] = Math.random() * Math.PI * 2;
      seed[i * 4 + 2] = Math.random();
      seed[i * 4 + 3] = Math.random();
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(count * 3), 3));
    g.setAttribute("seed", new THREE.BufferAttribute(seed, 4));
    this.mat = new THREE.ShaderMaterial({ uniforms: { uTime: { value: 0 }, uFlow: { value: 0 }, uSpin: { value: 0 }, uSize: { value: 5 }, uPixel: { value: 1 }, uColor: { value: new THREE.Color() }, uAlpha: { value: 1 } },
      vertexShader: V, fragmentShader: F, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending });
    tint.add("hot", 1, (c) => this.mat.uniforms["uColor"]!.value.copy(c));
    this.points = new THREE.Points(g, this.mat);
    this.points.frustumCulled = false;
  }
  setPixelRatio(pr: number) {
    this.mat.uniforms["uPixel"]!.value = pr;
  }
  update(m: Motion, amount: number) {
    this.mat.uniforms["uTime"]!.value = m.t;
    this.mat.uniforms["uFlow"]!.value = Math.min(0.5, m.v.flow * 0.5);
    this.mat.uniforms["uSpin"]!.value = m.v.spin;
    this.mat.uniforms["uAlpha"]!.value = (0.35 + 0.65 * Math.min(1, m.v.embers + 0.2)) * amount;
  }
}
