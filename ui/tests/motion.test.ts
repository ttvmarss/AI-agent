import { describe, expect, it } from "vitest";
import { Motion, clamp, easeOut } from "../src/motion";
import { DEFAULT_THEME } from "../src/theme";
import { EMPTY_FRAME, type Frame } from "../src/protocol";
import { mockFrame } from "../src/mock";

const run = (m: Motion, secs: number, fps = 30) => { for (let i = 0; i < secs * fps; i++) m.advance(1 / fps); };
const frame = (over: Partial<Frame>): Frame => ({ ...structuredClone(EMPTY_FRAME), ...over });

describe("persona: JARVIS converses, FRIDAY executes", () => {
  it("stays one voice: persona eases slightly while working and returns when done", () => {
    const m = new Motion(DEFAULT_THEME);
    m.setMode("idle"); run(m, 4);
    expect(m.persona).toBeLessThan(0.05);
    m.setMode("working"); run(m, 0.25);
    expect(m.persona).toBeGreaterThan(0.05); expect(m.persona).toBeLessThan(DEFAULT_THEME.modes.working.persona);   // a glide, not a snap
    run(m, 5);
    expect(m.persona).toBeGreaterThan(DEFAULT_THEME.modes.working.persona - 0.05);
    const [r, , b] = m.accent();
    expect(b).toBeGreaterThan(r);                                             // always cool: no orange
    m.setMode("ok"); run(m, 5);
    expect(m.persona).toBeLessThan(0.4);
  });
  it("STOP is fast: the spin dies and the layers collapse together", () => {
    const m = new Motion(DEFAULT_THEME);
    m.setMode("working"); run(m, 4);
    const spin = m.v.spin, explode = m.v.explode;
    expect(spin).toBeGreaterThan(0.5);
    m.setMode("stopping"); run(m, 0.6);
    expect(m.v.spin).toBeLessThan(spin * 0.05);
    expect(m.v.explode).toBeLessThan(explode * 0.3);
  });
});

describe("real events become light", () => {
  it("history before the first frame is not an event; new log lines are", () => {
    const m = new Motion(DEFAULT_THEME);
    const old = frame({ log: [{ id: 1, time: "", text: "a", level: "info" }, { id: 2, time: "", text: "b", level: "info" }] });
    m.feed(old); run(m, 1);
    expect(m.flare).toBe(0);
    expect(m.ripples).toHaveLength(0);
    m.feed(frame({ log: [...old.log, { id: 3, time: "", text: "c", level: "ok" }] }));
    expect(m.flare).toBeGreaterThan(0.4);
    expect(m.ripples).toHaveLength(1);
    expect(m.ripples[0]!.kind).toBe("ok");
    m.feed(frame({ log: [...old.log, { id: 3, time: "", text: "c", level: "ok" }] }));       // the same frame again is not a new event
    expect(m.ripples).toHaveLength(1);
  });
  it("a verified goal sends exactly one shockwave", () => {
    const m = new Motion(DEFAULT_THEME);
    m.feed(frame({ shock: 0 }));
    m.feed(frame({ shock: 1 }));
    expect(m.shock).toBe(0);
    let seen = 0;
    for (let i = 0; i < 60; i++) { m.advance(1 / 30); if (m.shock !== null) seen++; m.feed(frame({ shock: 1 })); }
    expect(m.shock).toBeNull();
    expect(seen).toBeGreaterThan(20);
  });
  it("a burst of events is rate limited into readable ripples that expire", () => {
    const m = new Motion(DEFAULT_THEME);
    m.advance(0.01);
    for (let i = 0; i < 30; i++) m.ripple("info");
    expect(m.ripples).toHaveLength(1);
    run(m, 3);
    expect(m.ripples).toHaveLength(0);
  });
});

describe("robustness", () => {
  it("ignores poisoned time steps and clamps a long stall", () => {
    const m = new Motion(DEFAULT_THEME);
    m.advance(0.5); const t = m.t;
    for (const bad of [NaN, Infinity, -1, 0]) m.advance(bad);
    expect(m.t).toBe(t);
    m.advance(60);
    expect(m.t - t).toBeLessThanOrEqual(0.26);
    for (const v of Object.values(m.v)) expect(Number.isFinite(v)).toBe(true);
  });
  it("clamp turns NaN into the lower bound instead of letting it through", () => {
    expect(clamp(NaN)).toBe(0);
    expect(clamp(5, 0, 2)).toBe(2);
    expect(easeOut(2)).toBe(1);
  });
  it("the start-up sequence draws element after element and every index finishes, even past the end", () => {
    const m = new Motion(DEFAULT_THEME);
    expect(m.reveal(0)).toBe(0);
    run(m, 1.2);
    expect(m.reveal(1)).toBeGreaterThan(m.reveal(14));
    run(m, 6);
    for (const k of [0, 5, 14, 40]) expect(m.reveal(k)).toBe(1);
  });
  it("every state in the mock engine maps to a defined motion row", () => {
    for (const s of ["starting", "idle", "listening", "working", "waiting", "approval", "ok", "bad", "stopping", "speaking"] as const) {
      const f = mockFrame(s, 3);
      expect(DEFAULT_THEME.modes[f.mode], s).toBeDefined();
    }
  });
});
