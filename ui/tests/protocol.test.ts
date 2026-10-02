import { describe, expect, it } from "vitest";
import { EMPTY_FRAME, parseFrame } from "../src/protocol";
import { mockFrame } from "../src/mock";

describe("parseFrame", () => {
  it("accepts a real frame unchanged", () => {
    const f = mockFrame("working", 1);
    const p = parseFrame(JSON.parse(JSON.stringify(f)))!;
    expect(p.mode).toBe("working");
    expect(p.pipeline.steps).toHaveLength(4);
    expect(p.brains[1]!.name).toBe("CLAUDE  X3");
  });
  it("rejects what is not a frame", () => {
    for (const bad of [null, undefined, 5, "x", [], {}, { v: 2 }]) expect(parseFrame(bad)).toBeNull();
  });
  it("survives hostile or half-broken engine messages", () => {
    const p = parseFrame({ v: 1, mode: "banana", title: 42, progress: "NaN", pipeline: { steps: [null, 7, { label: 3 }], checks: "no" },
                           brains: [{ pressure: 9, cost_class: 7 }, null], voice: { level: Infinity, state: "x" }, log: [{ id: "a" }], approvals: [null],
                           settings: 5, info: [], stats: null })!;
    expect(p.mode).toBe("idle");
    expect(p.title).toBe("");
    expect(p.progress).toBe(0);
    expect(p.pipeline.steps).toHaveLength(3);
    expect(p.brains[0]!.pressure).toBe(1);
    expect(p.brains[0]!.cost_class).toBe(1);
    expect(p.voice.level).toBe(0);
    expect(p.voice.state).toBe("off");
    expect(p.log[0]!.id).toBe(0);
    expect(p.settings).toEqual(EMPTY_FRAME.settings);
  });
  it("bounds everything so a huge message cannot flood the screen", () => {
    const many = Array.from({ length: 500 }, (_, i) => ({ id: i, time: "", text: "x".repeat(5000), level: "info" }));
    const p = parseFrame({ v: 1, log: many, goal: "g".repeat(9000), pipeline: { steps: Array.from({ length: 900 }, () => ({ label: "s", state: "pending" })) } })!;
    expect(p.log.length).toBeLessThanOrEqual(40);
    expect(p.log[0]!.text.length).toBeLessThanOrEqual(160);
    expect(p.goal.length).toBeLessThanOrEqual(400);
    expect(p.pipeline.steps.length).toBeLessThanOrEqual(40);
  });
});
