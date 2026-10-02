import { describe, expect, it } from "vitest";
import { DEFAULT_THEME, cssVars, hexToRgb, mergeTheme, mixRgb } from "../src/theme";
import { clock, decode, escapeHtml, mmss, money, ms } from "../src/util/format";

describe("theme.json", () => {
  it("defines every state with every number, and both minds", () => {
    for (const m of ["starting", "idle", "working", "waiting", "ok", "bad", "stopping", "stopped"] as const) {
      const row = DEFAULT_THEME.modes[m];
      for (const k of ["persona", "spin", "explode", "core", "charge", "bloom", "flow", "embers", "sweep", "bolts"] as const) expect(typeof row[k], `${m}.${k}`).toBe("number");
      expect(DEFAULT_THEME.modeLabels[m]).toBeTruthy();
    }
    expect(DEFAULT_THEME.modes.idle.persona).toBe(0);      // JARVIS converses
    expect(DEFAULT_THEME.modes.working.persona).toBeGreaterThan(0);   // a little more intent while executing
  });
  it("a user override changes what it names and ignores everything that does not fit", () => {
    const t = mergeTheme({ colors: { jarvis: "#ff00ff", nonsense: "#000" }, effects: { bloom: 0.2, glitch: "lots" }, modes: { idle: { spin: 0.5, bogus: 9 } }, fonts: 7, extra: { a: 1 } });
    expect(t.colors["jarvis"]).toBe("#ff00ff");
    expect(t.colors["nonsense"]).toBeUndefined();
    expect(t.effects.bloom).toBe(0.2);
    expect(t.effects.glitch).toBe(DEFAULT_THEME.effects.glitch);
    expect(t.modes.idle.spin).toBe(0.5);
    expect((t.modes.idle as unknown as Record<string, number>)["bogus"]).toBeUndefined();
    expect(t.fonts).toEqual(DEFAULT_THEME.fonts);
    expect((t as unknown as Record<string, unknown>)["extra"]).toBeUndefined();
    for (const bad of [null, undefined, 5, "x", [], [{}]]) expect(mergeTheme(bad)).toEqual(DEFAULT_THEME);
    expect(DEFAULT_THEME.colors["jarvis"]).not.toBe("#ff00ff");        // the shipped theme is never mutated
  });
  it("turns the theme into CSS custom properties", () => {
    const v = cssVars(DEFAULT_THEME);
    expect(v["--c-jarvis"]).toBe("#5fd0ff");
    expect(v["--c-jarvis-rgb"]).toBe("95 208 255");
    expect(v["--font-display"]).toContain("Rajdhani");
  });
  it("colour helpers", () => {
    expect(hexToRgb("#fff")).toEqual([255, 255, 255]);
    expect(hexToRgb("#102030")).toEqual([16, 32, 48]);
    expect(hexToRgb("garbage").every((c) => c >= 0 && c <= 255)).toBe(true);
    expect(mixRgb([0, 0, 0], [100, 200, 50], 0.5)).toEqual([50, 100, 25]);
    expect(mixRgb([0, 0, 0], [100, 100, 100], 9)).toEqual([100, 100, 100]);
  });
});

describe("format", () => {
  it("clock, durations, money and latency read the way people expect", () => {
    expect(clock(new Date(2026, 0, 1, 9, 5, 7))).toBe("09:05:07");
    expect(mmss(27)).toBe("00:27"); expect(mmss(125)).toBe("02:05"); expect(mmss(-4)).toBe("00:00");
    expect(money(0.024)).toBe("$0.024"); expect(money(3.456)).toBe("$3.46");
    expect(ms(null)).toBe("—"); expect(ms(420)).toBe("420 ms"); expect(ms(4210)).toBe("4.2 s"); expect(ms(NaN)).toBe("—");
  });
  it("the text-decode effect is scrambled ahead of the cursor and exact when finished", () => {
    const fixed = () => 0;
    expect(decode("VERIFIED", 1, fixed)).toBe("VERIFIED");
    expect(decode("VERIFIED", 0, fixed)).toHaveLength(4);
    expect(decode("VERIFIED", 0.5, fixed).startsWith("VERI")).toBe(true);
    expect(decode("A B", 0, fixed)).toContain(" ");
  });
  it("escapes everything that could become markup", () => {
    expect(escapeHtml(`<img src=x onerror="alert('x')">&`)).toBe("&lt;img src=x onerror=&quot;alert(&#39;x&#39;)&quot;&gt;&amp;");
  });
});
