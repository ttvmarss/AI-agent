import type { Frame } from "../protocol";

/** What the screen says it is doing, in two lines, from the real state. Pure, so it is unit-tested.
 *  Voice comes first while PRAXIS is idle (you are talking to it); a running goal, a pending approval, a result or a failure take over. */
export interface Caption { state: string; line: string; tone: "accent" | "ok" | "warn" | "bad" | "muted" }

export function caption(f: Frame): Caption {
  const v = f.voice;
  const steps = f.pipeline.steps;
  const done = steps.filter((s) => s.state === "verified" || s.state === "ran").length;
  switch (f.mode) {
    case "starting": return { state: "INITIALISING", line: f.subtitle, tone: "muted" };
    case "working": {
      const cur = steps.find((s) => s.state === "running");
      return { state: steps.length ? `EXECUTING  ${done}/${steps.length}` : "PLANNING", line: cur ? cur.label : f.goal || f.subtitle, tone: "accent" };
    }
    case "waiting": return { state: "AUTHORISATION REQUIRED", line: f.approvals[0]?.summary ?? "waiting for your answer", tone: "warn" };
    case "ok": return { state: "VERIFIED", line: f.subtitle, tone: "ok" };
    case "bad": return { state: "FAILED", line: f.subtitle, tone: "bad" };
    case "stopping": return { state: "STANDING DOWN", line: f.subtitle, tone: "warn" };
    case "stopped": return { state: f.title || "HALTED", line: f.subtitle, tone: "warn" };
    default: break;
  }
  if (v.note && (v.state === "offline" || v.state === "off")) return { state: "STANDING BY", line: v.note, tone: "warn" };
  switch (v.state) {
    case "speaking": return { state: "SPEAKING", line: v.said, tone: "accent" };
    case "hearing": return { state: "LISTENING", line: v.heard, tone: "accent" };
    case "thinking": return { state: "THINKING", line: v.heard, tone: "accent" };
    case "muted": return { state: "MIC OFF", line: "press F4 to listen again", tone: "warn" };
    case "offline": return { state: "NO MICROPHONE", line: "type what you want done", tone: "warn" };
    default: return { state: v.attentive ? "GO AHEAD" : "STANDING BY", line: v.said || (v.state === "listening" ? "say what you want done" : ""), tone: "accent" };
  }
}

/** "1 call", "20 calls". */
export function plural(n: number, one: string, many = one + "s"): string {
  return `${n} ${n === 1 ? one : many}`;
}
