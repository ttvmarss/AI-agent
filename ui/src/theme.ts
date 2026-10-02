import base from "./theme.json";
import type { Mode } from "./protocol";

export type ModeParams = { persona: number; spin: number; explode: number; core: number; charge: number; bloom: number; flow: number; embers: number; sweep: number; bolts: number };
export interface Theme {
  name: string;
  description: string;
  colors: Record<string, string>;
  fonts: { display: string; mono: string };
  effects: { bloom: number; particles: number; glitch: number; scanlines: number; parallax: number };
  persona: { rate: number };
  modes: Record<Mode, ModeParams>;
  modeLabels: Record<Mode, string>;
}

export const DEFAULT_THEME = base as unknown as Theme;

function isObj(x: unknown): x is Record<string, unknown> {
  return !!x && typeof x === "object" && !Array.isArray(x);
}

/** Merge a user's `~/.praxis/theme.json` over the shipped theme, key by key, keeping only values of the right type. A broken override can
 *  never break the interface: whatever does not fit is ignored. */
export function mergeTheme(over: unknown, into: Theme = DEFAULT_THEME): Theme {
  const out = structuredClone(into);
  if (!isObj(over)) return out;
  const walk = (dst: Record<string, unknown>, src: Record<string, unknown>) => {
    for (const [k, v] of Object.entries(src)) {
      const cur = dst[k];
      if (isObj(cur) && isObj(v)) walk(cur, v);
      else if (typeof cur === "number" && typeof v === "number" && Number.isFinite(v)) dst[k] = v;
      else if (typeof cur === "string" && typeof v === "string") dst[k] = v;
    }
  };
  walk(out as unknown as Record<string, unknown>, over);
  return out;
}

export function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace("#", "");
  const n = h.length === 3 ? h.split("").map((c) => c + c).join("") : h.slice(0, 6);
  const v = parseInt(n, 16);
  return Number.isFinite(v) ? [(v >> 16) & 255, (v >> 8) & 255, v & 255] : [255, 255, 255];
}

export function mixRgb(a: [number, number, number], b: [number, number, number], t: number): [number, number, number] {
  const k = Math.min(1, Math.max(0, t));
  return [a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k, a[2] + (b[2] - a[2]) * k];
}

/** CSS custom properties for the active theme: the interface is styled only through these. */
export function cssVars(t: Theme): Record<string, string> {
  const v: Record<string, string> = {};
  for (const [k, hex] of Object.entries(t.colors)) {
    v[`--c-${k}`] = hex;
    const [r, g, b] = hexToRgb(hex);
    v[`--c-${k}-rgb`] = `${r} ${g} ${b}`;
  }
  v["--font-display"] = `"${t.fonts.display}", "Segoe UI", system-ui, sans-serif`;
  v["--font-mono"] = `"${t.fonts.mono}", Consolas, "Cascadia Mono", monospace`;
  return v;
}
