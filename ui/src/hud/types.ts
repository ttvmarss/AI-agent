import type { Projected } from "../scene";

/** What the HUD needs from the 3D scene (so it can be tested with a stand-in). */
export interface Scene {
  project(name: "core" | "act" | "verify" | "plan"): Projected;
}
