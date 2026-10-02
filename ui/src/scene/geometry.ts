import * as THREE from "three";

export const TAU = Math.PI * 2;

/** Points of a circle in the XY plane. */
export function circlePoints(r: number, n = 96, z = 0): THREE.Vector3[] {
  const out: THREE.Vector3[] = [];
  for (let i = 0; i <= n; i++) {
    const a = (i / n) * TAU;
    out.push(new THREE.Vector3(Math.cos(a) * r, Math.sin(a) * r, z));
  }
  return out;
}

export function lineLoop(points: THREE.Vector3[], material: THREE.Material): THREE.Line {
  return new THREE.Line(new THREE.BufferGeometry().setFromPoints(points), material as THREE.LineBasicMaterial);
}

export function segments(pairs: [THREE.Vector3, THREE.Vector3][], material: THREE.Material): THREE.LineSegments {
  const pts: THREE.Vector3[] = [];
  for (const [a, b] of pairs) pts.push(a, b);
  return new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(pts), material as THREE.LineBasicMaterial);
}

/** Radial tick marks between two radii. */
export function tickPairs(r0: number, r1: number, n: number, major = 0, majorExtra = 0, z = 0): [THREE.Vector3, THREE.Vector3][] {
  const out: [THREE.Vector3, THREE.Vector3][] = [];
  for (let i = 0; i < n; i++) {
    const a = (i / n) * TAU;
    const ex = major && i % major === 0 ? majorExtra : 0;
    out.push([new THREE.Vector3(Math.cos(a) * (r0 - ex), Math.sin(a) * (r0 - ex), z), new THREE.Vector3(Math.cos(a) * r1, Math.sin(a) * r1, z)]);
  }
  return out;
}

/** A soft round glow sprite texture (white centre fading to transparent), drawn once. */
export function glowTexture(size = 128, stops: [number, string][] = [[0, "rgba(255,255,255,1)"], [0.25, "rgba(255,255,255,0.55)"], [0.6, "rgba(255,255,255,0.12)"], [1, "rgba(255,255,255,0)"]]): THREE.Texture {
  const c = document.createElement("canvas");
  c.width = c.height = size;
  const g = c.getContext("2d")!;
  const grad = g.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  for (const [p, col] of stops) grad.addColorStop(p, col);
  g.fillStyle = grad;
  g.fillRect(0, 0, size, size);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

export const additive = <T extends THREE.Material>(m: T): T => {
  m.transparent = true;
  m.blending = THREE.AdditiveBlending;
  m.depthWrite = false;
  return m;
};

export function lineMat(opacity = 1): THREE.LineBasicMaterial {
  return additive(new THREE.LineBasicMaterial({ color: 0xffffff, opacity }));
}
