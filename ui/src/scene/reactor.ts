import * as THREE from "three";
import { Line2 } from "three/examples/jsm/lines/Line2.js";
import { LineGeometry } from "three/examples/jsm/lines/LineGeometry.js";
import { LineMaterial } from "three/examples/jsm/lines/LineMaterial.js";
import { additive, circlePoints, glowTexture, lineLoop, lineMat, segments, tickPairs, TAU } from "./geometry";
import { Tinter } from "./tint";
import { clamp, type Motion } from "../motion";

/** PRAXIS's heart, drawn the way Tony would show it: an arc reactor in EXPLODED VIEW. Its layers float apart along the axis (more when it
 *  works, together when it stops), each a thin glowing wireframe: housing, ten coils, scale ring, triangle, core and a front glass disc, joined by
 *  dashed leaders. The coils light in a chase while it works; the core brightness is the state. */
export const COILS = 10;
const Z = { back: -1.15, coil: -0.62, mid: -0.2, tri: 0.2, core: 0.62, glass: 1.1 };

export class Reactor {
  readonly group = new THREE.Group();
  private readonly layers: Record<keyof typeof Z, THREE.Group> = { back: new THREE.Group(), coil: new THREE.Group(), mid: new THREE.Group(), tri: new THREE.Group(), core: new THREE.Group(), glass: new THREE.Group() };
  private readonly coils: { line: THREE.LineSegments; mat: THREE.LineBasicMaterial; fill: THREE.Mesh; fillMat: THREE.MeshBasicMaterial }[] = [];
  private readonly coreWire: THREE.LineSegments;
  private readonly coreGlow: THREE.Sprite;
  private readonly coreHot: THREE.Sprite;
  private readonly triangle: THREE.Group;
  private readonly leaders: THREE.LineSegments;
  private readonly bolts: THREE.Line[] = [];
  private readonly boltMat = lineMat(1);
  private readonly lineMats: LineMaterial[] = [];

  constructor(private readonly tint: Tinter, glow: THREE.Texture) {
    for (const [k, g] of Object.entries(this.layers)) {
      g.name = k;
      this.group.add(g);
    }
    const thick = (px: number, role: "accent" | "hot", k = 1, op = 1) => {
      const m = new LineMaterial({ color: 0xffffff, linewidth: px, transparent: true, opacity: op, blending: THREE.AdditiveBlending, depthWrite: false, worldUnits: false });
      this.lineMats.push(m);
      tint.add(role, k, (c, kk) => m.color.copy(c).multiplyScalar(kk));
      return m;
    };
    const fat = (pts: THREE.Vector3[], m: LineMaterial) => {
      const g = new LineGeometry();
      g.setPositions(pts.flatMap((p) => [p.x, p.y, p.z]));
      const l = new Line2(g, m);
      l.computeLineDistances();
      return l;
    };
    const basic = (role: "accent" | "hot", k: number, op: number) => tint.material(lineMat(op), role, k) as THREE.LineBasicMaterial;

    // ---- back: the housing -------------------------------------------------------------------------------------------
    const housing = new THREE.TorusGeometry(1.0, 0.045, 6, 72);
    this.layers.back.add(new THREE.LineSegments(new THREE.WireframeGeometry(housing), basic("accent", 0.55, 0.55)));
    this.layers.back.add(fat(circlePoints(1.06, 128), thick(1.6, "accent", 0.9)));
    this.layers.back.add(fat(circlePoints(1.16, 128), thick(1, "accent", 0.45, 0.8)));
    this.layers.back.add(segments(tickPairs(1.2, 1.26, 120, 10, 0.05), basic("accent", 0.8, 0.8)));
    const bolts = new THREE.Points(new THREE.BufferGeometry().setFromPoints(circlePoints(0.93, 12).slice(0, 12)), additive(new THREE.PointsMaterial({ size: 5, sizeAttenuation: false, map: glow, color: 0xffffff })));
    tint.material(bolts.material as THREE.PointsMaterial, "hot", 0.8);
    this.layers.back.add(bolts);

    // ---- coils: ten trapezoid prisms between r 0.52 and 0.82 -----------------------------------------------------------
    const span = TAU / COILS - 0.1;
    for (let i = 0; i < COILS; i++) {
      const a0 = (i / COILS) * TAU;
      const a1 = a0 + span;
      const P = (a: number, r: number, z: number) => new THREE.Vector3(Math.cos(a) * r, Math.sin(a) * r, z);
      const zt = 0.09;
      const pairs: [THREE.Vector3, THREE.Vector3][] = [];
      const quad = (z: number) => [P(a0, 0.52, z), P(a1, 0.52, z), P(a1, 0.82, z), P(a0, 0.82, z)];
      const front = quad(zt), back = quad(-zt);
      for (let k = 0; k < 4; k++) {
        pairs.push([front[k]!, front[(k + 1) % 4]!], [back[k]!, back[(k + 1) % 4]!], [front[k]!, back[k]!]);
      }
      const mat = basic("accent", 1, 0.9);
      const line = segments(pairs, mat);
      const shape = new THREE.Shape([new THREE.Vector2(front[0]!.x, front[0]!.y), new THREE.Vector2(front[1]!.x, front[1]!.y), new THREE.Vector2(front[2]!.x, front[2]!.y), new THREE.Vector2(front[3]!.x, front[3]!.y)]);
      const fillMat = additive(new THREE.MeshBasicMaterial({ color: 0xffffff, opacity: 0.1, side: THREE.DoubleSide }));
      tint.material(fillMat, "accent", 0.5);
      const fill = new THREE.Mesh(new THREE.ShapeGeometry(shape), fillMat);
      fill.position.z = zt;
      this.layers.coil.add(line, fill);
      this.coils.push({ line, mat, fill, fillMat });
    }
    this.layers.coil.add(fat(circlePoints(0.84, 128), thick(1.2, "accent", 0.6, 0.9)));
    this.layers.coil.add(fat(circlePoints(0.5, 128), thick(1.2, "accent", 0.6, 0.9)));

    // ---- mid: scale ring ---------------------------------------------------------------------------------------------------
    this.layers.mid.add(fat(circlePoints(0.44, 96), thick(1.4, "hot", 0.7, 0.9)));
    this.layers.mid.add(segments(tickPairs(0.4, 0.44, 90, 5, 0.025), basic("hot", 0.8, 0.8)));

    // ---- triangle ----------------------------------------------------------------------------------------------------------
    this.triangle = new THREE.Group();
    const tri = (r: number) => [0, 1, 2, 0].map((k) => new THREE.Vector3(Math.cos((k / 3) * TAU + Math.PI / 2) * r, Math.sin((k / 3) * TAU + Math.PI / 2) * r, 0));
    this.triangle.add(fat(tri(0.33), thick(1.8, "hot", 1)), fat(tri(0.24), thick(1, "accent", 0.6, 0.8)));
    this.layers.tri.add(this.triangle);

    // ---- core --------------------------------------------------------------------------------------------------------------
    this.coreWire = new THREE.LineSegments(new THREE.WireframeGeometry(new THREE.IcosahedronGeometry(0.17, 1)), basic("hot", 1, 0.9));
    this.coreGlow = new THREE.Sprite(additive(new THREE.SpriteMaterial({ map: glow, color: 0xffffff, opacity: 0.8 })));
    this.coreHot = new THREE.Sprite(additive(new THREE.SpriteMaterial({ map: glow, color: 0xffffff, opacity: 1 })));
    tint.material(this.coreGlow.material as THREE.SpriteMaterial, "accent", 1);
    tint.material(this.coreHot.material as THREE.SpriteMaterial, "white", 1);
    this.layers.core.add(this.coreWire, this.coreGlow, this.coreHot);

    // ---- glass disc ---------------------------------------------------------------------------------------------------------
    this.layers.glass.add(fat(circlePoints(0.96, 128), thick(1, "accent", 0.55, 0.7)));
    this.layers.glass.add(segments(tickPairs(0.9, 0.96, 48, 4, 0.04), basic("accent", 0.6, 0.6)));
    const dots = new THREE.Points(new THREE.BufferGeometry().setFromPoints(circlePoints(0.7, 36)), additive(new THREE.PointsMaterial({ size: 2.5, sizeAttenuation: false, map: glow, color: 0xffffff })));
    tint.material(dots.material as THREE.PointsMaterial, "accent", 0.7);
    this.layers.glass.add(dots);

    // ---- dashed leaders joining the layers (the exploded-view cue) --------------------------------------------------------
    const lp: [THREE.Vector3, THREE.Vector3][] = [];
    for (let i = 0; i < 6; i++) {
      const a = (i / 6) * TAU + 0.3;
      lp.push([new THREE.Vector3(Math.cos(a) * 1.0, Math.sin(a) * 1.0, Z.back), new THREE.Vector3(Math.cos(a) * 1.0, Math.sin(a) * 1.0, Z.glass)]);
    }
    this.leaders = segments(lp, additive(new THREE.LineDashedMaterial({ color: 0xffffff, dashSize: 0.05, gapSize: 0.06, opacity: 0.3 })));
    tint.material(this.leaders.material as THREE.LineDashedMaterial, "accent", 0.7);
    this.leaders.computeLineDistances();
    this.group.add(this.leaders);

    // ---- bolts: energy arcs from the core to the coils (a pool, drawn on events) -----------------------------------------------
    tint.material(this.boltMat, "hot", 1);
    for (let i = 0; i < 5; i++) {
      const l = new THREE.Line(new THREE.BufferGeometry().setFromPoints(Array.from({ length: 10 }, () => new THREE.Vector3())), this.boltMat);
      l.visible = false;
      this.bolts.push(l);
      this.group.add(l);
    }
  }

  setResolution(w: number, h: number) {
    for (const m of this.lineMats) m.resolution.set(w, h);
  }

  update(m: Motion, dt: number) {
    const e = m.v.explode;
    for (const [k, g] of Object.entries(this.layers)) g.position.z = Z[k as keyof typeof Z] * e * 1.25;
    this.layers.coil.rotation.z = m.rotA * 0.9;
    this.layers.back.rotation.z = -m.rotB * 0.25;
    this.layers.mid.rotation.z = m.rotC * 0.8;
    this.layers.glass.rotation.z = m.rotB * 0.4;
    this.triangle.rotation.z = m.rotC * 1.3;
    this.coreWire.rotation.set(m.t * 0.4, m.t * 0.6, 0);
    const lvl = m.coreLevel();
    const s = 0.55 + 0.45 * lvl;
    this.coreWire.scale.setScalar(s * 1.05);
    this.coreGlow.scale.setScalar(0.9 * s + 0.35 * m.flare);
    this.coreHot.scale.setScalar(0.34 * s + 0.15 * m.flare);
    (this.coreGlow.material as THREE.SpriteMaterial).opacity = clamp(0.35 + 0.5 * lvl, 0, 1);
    // coils: power-up lights them one by one; working chases a bright run round the ring; waiting pulses them together
    for (let i = 0; i < this.coils.length; i++) {
      const c = this.coils[i]!;
      const lit = clamp(m.power * COILS - i + 0.5);
      let charge = m.v.charge;
      if (m.mode === "working") charge = clamp(charge * (0.45 + 0.55 * (1 - (((m.t * 1.3 - i / COILS) % 1) + 1) % 1) ** 2) + 0.12);
      else if (m.mode === "waiting") charge = clamp(charge * (0.55 + 0.45 * Math.sin(m.t * 3.2)));
      else charge = clamp(charge * (0.85 + 0.15 * Math.sin(m.t * 1.1 + i * 0.7)));
      const k = lit * charge;
      c.mat.opacity = 0.25 + 0.75 * k;
      c.fillMat.opacity = 0.02 + 0.28 * k * k;
    }
    // bolts
    for (let i = 0; i < this.bolts.length; i++) {
      const l = this.bolts[i]!;
      const b = m.bolts[i];
      l.visible = !!b;
      if (!b) continue;
      const pos = l.geometry.getAttribute("position") as THREE.BufferAttribute;
      const ca = Math.cos(b.a), sa = Math.sin(b.a);
      b.offs.forEach((off, j) => {
        const rad = 0.17 + (0.82 - 0.17) * (j / 9);
        pos.setXYZ(j, ca * rad - sa * off, sa * rad + ca * off, Z.core * 0.2 * e * 1.25 * (1 - j / 9) + Z.coil * e * 1.25 * (j / 9));
      });
      pos.needsUpdate = true;
    }
    this.boltMat.opacity = 0.9;
    void dt;
  }

  /** World position of the core (for callouts). */
  corePosition(out = new THREE.Vector3()): THREE.Vector3 {
    return this.layers.core.getWorldPosition(out);
  }
}
