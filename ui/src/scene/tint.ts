import * as THREE from "three";

/** Every glowing thing in the scene takes its colour from the mind in charge (JARVIS ice-blue .. FRIDAY amber). Rather than touching each
 *  material by hand every frame, things register once with a role and a brightness and `apply()` repaints them all. */
export type Role = "accent" | "hot" | "ok" | "bad" | "warn" | "white";

type Painter = (color: THREE.Color, k: number) => void;

export class Tinter {
  private items: { role: Role; k: number; paint: Painter }[] = [];
  readonly accent = new THREE.Color();
  readonly hot = new THREE.Color();
  readonly ok = new THREE.Color("#46f0b0");
  readonly bad = new THREE.Color("#ff4d3f");
  readonly warn = new THREE.Color("#ffc247");
  readonly white = new THREE.Color("#ffffff");
  private tmp = new THREE.Color();

  add(role: Role, k: number, paint: Painter) {
    this.items.push({ role, k, paint });
    paint(this.pick(role), k);
  }

  /** Register a three.js material whose `.color` (and optionally `.opacity`) follows a role. */
  material(m: THREE.Material & { color?: THREE.Color }, role: Role = "accent", k = 1): typeof m {
    this.add(role, k, (c, kk) => {
      if (m.color) m.color.copy(c).multiplyScalar(kk);
    });
    return m;
  }

  private pick(role: Role): THREE.Color {
    return this[role];
  }

  set(accent: [number, number, number], hot: [number, number, number]) {
    this.accent.setRGB(accent[0] / 255, accent[1] / 255, accent[2] / 255, THREE.SRGBColorSpace);
    this.hot.setRGB(hot[0] / 255, hot[1] / 255, hot[2] / 255, THREE.SRGBColorSpace);
  }

  apply() {
    for (const it of this.items) it.paint(this.tmp.copy(this.pick(it.role)), it.k);
  }
}
