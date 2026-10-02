import * as THREE from "three";
import { Line2 } from "three/examples/jsm/lines/Line2.js";
import { LineGeometry } from "three/examples/jsm/lines/LineGeometry.js";
import { LineMaterial } from "three/examples/jsm/lines/LineMaterial.js";
import { additive, circlePoints, lineLoop, lineMat, segments, tickPairs, TAU } from "./geometry";
import { Tinter } from "./tint";
import { clamp, type Motion } from "../motion";

/** The workshop around the object: the holo table (floor rings and radar arcs), the projector beam, a scanning plane, the voice ring, the ripples
 *  that every real event sends out, and the verified shockwave. */
const FLOOR_Y = -2.45;

const BEAM_V = `varying vec3 vP; varying vec3 vN; void main(){ vP=position; vN=normalize(normalMatrix*normal); vec4 mv=modelViewMatrix*vec4(position,1.0); gl_Position=projectionMatrix*mv; }`;
const BEAM_F = `varying vec3 vP; varying vec3 vN; uniform vec3 uColor; uniform float uAlpha; uniform float uH;
void main(){ float h=clamp((vP.y+uH*0.5)/uH,0.0,1.0); float edge=pow(1.0-abs(normalize(vN).z),1.6); float a=uAlpha*pow(1.0-h,1.6)*smoothstep(0.0,0.06,h)*(0.15+0.85*edge); gl_FragColor=vec4(uColor,a); }`;
const DISC_F = `varying vec2 vUv; uniform vec3 uColor; uniform float uAlpha; void main(){ float d=length(vUv-0.5)*2.0; float a=uAlpha*smoothstep(1.0,0.0,d)*(0.35+0.65*smoothstep(0.2,0.0,abs(d-0.6))); gl_FragColor=vec4(uColor,a); }`;
const DISC_V = `varying vec2 vUv; void main(){ vUv=uv; gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0); }`;
const SCAN_F = `varying vec2 vUv; uniform vec3 uColor; uniform float uAlpha; void main(){ float d=length(vUv-0.5)*2.0; float ring=smoothstep(1.0,0.93,d)*(0.25+0.75*smoothstep(0.85,1.0,d)); gl_FragColor=vec4(uColor,uAlpha*ring*(1.0-0.5*d)); }`;

export class Stage {
  readonly group = new THREE.Group();
  private readonly floor = new THREE.Group();
  private readonly arcs: Line2[] = [];
  private readonly beamMat: THREE.ShaderMaterial;
  private readonly discMat: THREE.ShaderMaterial;
  private readonly scan: THREE.Mesh;
  private readonly scanMat: THREE.ShaderMaterial;
  private readonly voice: Line2;
  private readonly voiceMat: LineMaterial;
  private readonly voiceGeo: LineGeometry;
  private readonly ripples: Line[] = [];
  private readonly shockMesh: THREE.LineSegments;
  private readonly shockMat: THREE.LineBasicMaterial;
  private readonly mats: LineMaterial[] = [];
  private voiceHist: number[] = new Array(128).fill(0);
  private voiceAcc = 0;

  constructor(private readonly tint: Tinter) {
    // ---- the table -------------------------------------------------------------------------------------------------------
    this.floor.position.y = FLOOR_Y;
    this.floor.rotation.x = -Math.PI / 2;
    const ringMat = (k: number, op: number) => tint.material(lineMat(op), "accent", k) as THREE.LineBasicMaterial;
    [1.1, 1.8, 2.6, 3.4, 4.2].forEach((r, i) => this.floor.add(lineLoop(circlePoints(r, 160), ringMat(0.9 - i * 0.12, 0.7 - i * 0.08))));
    this.floor.add(segments(tickPairs(4.0, 4.3, 144, 12, 0.14), ringMat(0.8, 0.7)));
    this.floor.add(segments(tickPairs(2.6, 2.72, 72, 6, 0.08), ringMat(0.7, 0.6)));
    const dashed = lineLoop(circlePoints(3.0, 160), additive(new THREE.LineDashedMaterial({ color: 0xffffff, dashSize: 0.08, gapSize: 0.08, opacity: 0.5 })));
    tint.material(dashed.material as THREE.LineDashedMaterial, "accent", 0.6);
    (dashed as THREE.Line).computeLineDistances();
    this.floor.add(dashed);
    const thick = (px: number, k: number, op = 1) => {
      const m = new LineMaterial({ color: 0xffffff, linewidth: px, transparent: true, opacity: op, blending: THREE.AdditiveBlending, depthWrite: false });
      this.mats.push(m);
      tint.add("accent", k, (c, kk) => m.color.copy(c).multiplyScalar(kk));
      return m;
    };
    const arcMat = thick(2.2, 1, 0.9);
    for (let i = 0; i < 3; i++) {
      const pts: number[] = [];
      for (let k = 0; k <= 30; k++) {
        const a = ((i * 120 + (50 * k) / 30) * Math.PI) / 180;
        pts.push(Math.cos(a) * 2.6, Math.sin(a) * 2.6, 0);
      }
      const g = new LineGeometry();
      g.setPositions(pts);
      const l = new Line2(g, arcMat);
      this.arcs.push(l);
      this.floor.add(l);
    }
    this.discMat = additive(new THREE.ShaderMaterial({ uniforms: { uColor: { value: new THREE.Color() }, uAlpha: { value: 0.2 } }, vertexShader: DISC_V, fragmentShader: DISC_F }));
    tint.add("accent", 1, (c) => this.discMat.uniforms["uColor"]!.value.copy(c));
    this.floor.add(new THREE.Mesh(new THREE.CircleGeometry(4.3, 64), this.discMat));
    this.group.add(this.floor);

    // ---- projector beam --------------------------------------------------------------------------------------------------
    this.beamMat = additive(new THREE.ShaderMaterial({ uniforms: { uColor: { value: new THREE.Color() }, uAlpha: { value: 0.16 }, uH: { value: 5.4 } }, vertexShader: BEAM_V, fragmentShader: BEAM_F, side: THREE.DoubleSide }));
    tint.add("accent", 1, (c) => this.beamMat.uniforms["uColor"]!.value.copy(c));
    const beam = new THREE.Mesh(new THREE.CylinderGeometry(1.9, 0.55, 5.4, 64, 1, true), this.beamMat);
    beam.position.y = FLOOR_Y + 2.7;
    this.group.add(beam);

    // ---- a scanning plane that sweeps up through the object ----------------------------------------------------------------
    this.scanMat = additive(new THREE.ShaderMaterial({ uniforms: { uColor: { value: new THREE.Color() }, uAlpha: { value: 0.0 } }, vertexShader: DISC_V, fragmentShader: SCAN_F, side: THREE.DoubleSide }));
    tint.add("hot", 1, (c) => this.scanMat.uniforms["uColor"]!.value.copy(c));
    this.scan = new THREE.Mesh(new THREE.PlaneGeometry(5.6, 5.6), this.scanMat);
    this.scan.rotation.x = -Math.PI / 2;
    this.group.add(this.scan);

    // ---- the voice ring: a radial equaliser of the REAL audio -------------------------------------------------------------------
    this.voiceMat = thick(2.4, 1, 0.95);
    this.voiceGeo = new LineGeometry();
    this.voiceGeo.setPositions(new Array(129 * 3).fill(0));
    this.voice = new Line2(this.voiceGeo, this.voiceMat);
    this.group.add(this.voice);

    // ---- ripples (one per real event) and the shockwave -----------------------------------------------------------------------
    for (let i = 0; i < 6; i++) {
      const m = additive(new THREE.LineBasicMaterial({ color: 0xffffff, opacity: 0 }));
      const l = lineLoop(circlePoints(1, 96), m) as Line;
      l.visible = false;
      this.ripples.push(l);
      this.group.add(l);
    }
    this.shockMat = lineMat(0);
    tint.material(this.shockMat, "hot", 1);
    const ico = new THREE.WireframeGeometry(new THREE.IcosahedronGeometry(1, 2));
    this.shockMesh = new THREE.LineSegments(ico, this.shockMat);
    this.shockMesh.visible = false;
    this.group.add(this.shockMesh);
  }

  setResolution(w: number, h: number) {
    for (const m of this.mats) m.resolution.set(w, h);
  }

  /** `level` is the real audio level 0..1 (the mic while it listens, its own voice while it speaks). */
  update(m: Motion, dt: number, level: number, tint: Tinter) {
    this.voiceAcc += dt;
    while (this.voiceAcc >= 1 / 30) {
      this.voiceAcc -= 1 / 30;
      this.voiceHist.shift();
      this.voiceHist.push((this.voiceHist[this.voiceHist.length - 1] ?? 0) * 0.55 + level * 0.45);
    }
    const pos: number[] = [];
    const n = this.voiceHist.length;
    for (let i = 0; i <= n; i++) {
      const v = this.voiceHist[i % n] ?? 0;
      const a = (i / n) * TAU;
      const wob = level > 0.02 ? 0.05 * Math.sin(i * 1.7 + m.t * 9) : 0;
      const r = 1.28 + 0.34 * clamp(v + wob * v) + 0.012 * Math.sin(i * 0.5 + m.t);
      pos.push(Math.cos(a) * r, Math.sin(a) * r, 0.0);
    }
    this.voiceGeo.setPositions(pos);
    this.voiceMat.opacity = 0.35 + 0.6 * clamp(level * 1.6 + 0.12);

    this.arcs.forEach((a, i) => (a.rotation.z = m.rotB * (i % 2 ? -1.2 : 1.4) + i));
    this.discMat.uniforms["uAlpha"]!.value = 0.045 + 0.04 * m.v.core + 0.06 * m.flare;
    this.beamMat.uniforms["uAlpha"]!.value = 0.05 + 0.035 * m.v.core + 0.05 * m.flare;
    // the scan plane: one slow sweep every few seconds, quicker while it works
    const period = m.mode === "working" ? 3.2 : 8;
    const u = (m.t % period) / period;
    this.scan.position.y = FLOOR_Y + 0.3 + u * 3.3;
    this.scanMat.uniforms["uAlpha"]!.value = 0.22 * Math.sin(Math.PI * u) ** 1.5 * clamp(m.boot * 1.5);
    // ripples: expanding rings on the table and round the object
    this.ripples.forEach((l, i) => {
      const r = m.ripples[i];
      l.visible = !!r;
      if (!r) return;
      const u2 = clamp((m.t - r.t0) / 1.6);
      const radius = 1.1 + 3.2 * (1 - (1 - u2) ** 2);
      l.scale.setScalar(radius);
      l.position.y = FLOOR_Y + 0.02;
      l.rotation.x = -Math.PI / 2;
      const mat = l.material as THREE.LineBasicMaterial;
      const c = r.kind === "ok" ? tint.ok : r.kind === "bad" ? tint.bad : r.kind === "warn" ? tint.warn : tint.accent;
      mat.color.copy(c);
      mat.opacity = 0.85 * (1 - u2) ** 1.6;
    });
    if (m.shock !== null) {
      this.shockMesh.visible = true;
      const s = 1.3 + 1.7 * (1 - (1 - clamp(m.shock)) ** 3);
      this.shockMesh.scale.setScalar(s);
      this.shockMat.opacity = 0.5 * (1 - m.shock) ** 1.6;
    } else this.shockMesh.visible = false;
  }
}

type Line = THREE.Line;
