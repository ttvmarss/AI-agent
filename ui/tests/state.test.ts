import { describe, expect, it } from "vitest";
import { EMPTY_FRAME, type Frame } from "../src/protocol";
import { caption, plural } from "../src/hud/state";

const f = (p: Partial<Frame>): Frame => ({ ...EMPTY_FRAME, ...p });

describe("caption", () => {
  it("shows the spoken sentence while speaking", () => {
    const c = caption(f({ mode: "idle", voice: { ...EMPTY_FRAME.voice, state: "speaking", said: "Done." } }));
    expect(c).toMatchObject({ state: "SPEAKING", line: "Done." });
  });
  it("a pending approval outranks everything", () => {
    const c = caption(f({ mode: "waiting", approvals: [{ ...(({} as unknown) as Frame["approvals"][0]), summary: "Open x" }] }));
    expect(c.state).toBe("AUTHORISATION REQUIRED");
    expect(c.line).toBe("Open x");
  });
  it("reports failure and success", () => {
    expect(caption(f({ mode: "bad", subtitle: "why" })).tone).toBe("bad");
    expect(caption(f({ mode: "ok", subtitle: "fine" })).state).toBe("VERIFIED");
  });
});

describe("plural", () => {
  it("handles one and many", () => {
    expect(plural(1, "call")).toBe("1 call");
    expect(plural(20, "call")).toBe("20 calls");
  });
});
