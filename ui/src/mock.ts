import { EMPTY_FRAME, type Approval, type Brain, type Frame, type LogLine, type Mode, type StepState } from "./protocol";

/** A scripted stand-in for the engine, for developing and screenshot-testing the interface with no Python running (`?mock=working`).
 *  It speaks the same Frame contract as the real server. */

const model = (name: string, tier = "balanced") => ({ name, tier, score: 0.9, cooling_s: 0 });
export const MOCK_BRAINS: Brain[] = [
  { family: "ollama", name: "OLLAMA", cost_class: 0, privacy: "local", pressure: 0, cooling_s: 0, blocked: false, models: [model("ollama/qwen3:8b", "fast")], calls_24h: 4, cost_24h: 0 },
  { family: "claude", name: "CLAUDE  X3", cost_class: 2, privacy: "cloud", pressure: 0.12, cooling_s: 0, blocked: false,
    models: [model("claude/sonnet", "fast"), model("claude/opus"), model("claude/fable", "best")], calls_24h: 9, cost_24h: 0.176 },
  { family: "codex", name: "CODEX  X2", cost_class: 2, privacy: "cloud", pressure: 0.72, cooling_s: 0, blocked: false, models: [model("codex/gpt-5.5"), model("codex/mini", "fast")], calls_24h: 6, cost_24h: 0.05 },
  { family: "droid", name: "DROID · FACTORY  X2", cost_class: 2, privacy: "cloud", pressure: 0.2, cooling_s: 0, blocked: false, models: [model("droid/claude-fable-5.1"), model("droid/opus")], calls_24h: 2, cost_24h: 0 },
  { family: "devin", name: "DEVIN", cost_class: 2, privacy: "cloud", pressure: 0.05, cooling_s: 0, blocked: false, models: [model("devin/default")], calls_24h: 0, cost_24h: 0 },
  { family: "groq", name: "GROQ", cost_class: 1, privacy: "cloud", pressure: 0.93, cooling_s: 360, blocked: false, models: [model("groq/llama", "fast")], calls_24h: 30, cost_24h: 0 },
];

const LOG: LogLine[] = [
  { id: 1, time: "13:41:40", text: "BUILD  e67f399 (claude/praxis-architecture-rev0)", level: "info" },
  { id: 2, time: "13:41:40", text: "JARVIS  conversation mind online", level: "info" },
  { id: 3, time: "13:41:41", text: "FRIDAY  execution mind online", level: "warn" },
  { id: 4, time: "13:41:41", text: "BRAINS ONLINE  claude · codex · droid · ollama", level: "ok" },
  { id: 5, time: "13:41:45", text: "Reflex: open Google Chrome (no model needed)", level: "info" },
  { id: 6, time: "13:41:45", text: "Step open: desktop.open open Google Chrome", level: "info" },
  { id: 7, time: "13:41:46", text: "Guard: ALLOW (Class 2) - Class 2 within grant", level: "ok" },
  { id: 8, time: "13:41:47", text: "PASS: process_running chrome.exe", level: "ok" },
];

const APPROVAL: Approval = { id: "ab12cd34", tool: "agent.delegate", cls: 3, risky: false, reason: "Class 3 exceeds auto grant 2",
  summary: "Hand a coding task to Claude", detail: "agent.delegate  agent=claude\n  task: Refactor parser.py to remove the global state and add tests" };

function base(): Frame {
  const f = structuredClone(EMPTY_FRAME);
  f.brains = structuredClone(MOCK_BRAINS);
  f.log = structuredClone(LOG);
  f.settings = { data_class: "project", strategy: "balanced", models: 12 };
  f.info = { build: "e67f399 (claude/praxis-architecture-rev0)", workspace: "C:\\Users\\tikto\\PRAXIS\\workspace", workspace_name: "workspace", hint: "",
             sandbox: "unshare", sandbox_strong: true, recent: ["C:\\Users\\tikto\\PRAXIS\\workspace", "C:\\Users\\tikto\\AI-agent"], can_type: false };
  f.voice = { state: "listening", level: 0, speak: 0, attentive: false, heard: "", said: "", note: "" };
  return f;
}

const STEPS = ["Write hello.py", "Run hello.py", "Check the output contains 34", "Clean up"];

export type Scenario = "starting" | "idle" | "listening" | "working" | "waiting" | "approval" | "ok" | "bad" | "stopping" | "speaking";

export function mockFrame(scenario: Scenario, t = 0): Frame {
  const f = base();
  f.t = t;
  const wave = (a: number) => Math.max(0, Math.min(1, a * (0.55 + 0.45 * Math.sin(t * 7.3) * Math.sin(t * 2.1 + 1))));
  const goal = "Create hello.py that prints the first 10 Fibonacci numbers, run it, and verify the output contains 34";
  const withGoal = (states: StepState[], checks: boolean[] = []) => {
    f.goal = goal;
    f.pipeline = { plan: "ready", steps: STEPS.map((label, i) => ({ label, state: states[i] ?? "pending" })),
                   checks: checks.map((ok, i) => ({ label: i === 0 ? "file_exists hello.py" : "command_output_contains python3 hello.py '34'", ok })), sealed: false };
  };
  const mode = (m: Mode, title: string, subtitle = "") => { f.mode = m; f.title = title; f.subtitle = subtitle; };
  switch (scenario) {
    case "starting": mode("starting", "STARTING", "detecting hardware, tools and sandbox"); f.log = f.log.slice(0, 1); f.brains = []; f.voice.state = "off"; break;
    case "idle": mode("idle", "READY", "describe an outcome"); break;
    case "listening": mode("idle", "READY", ""); f.voice = { state: "hearing", level: wave(0.7), speak: 0, attentive: true, heard: "", said: "", note: "" }; break;
    case "speaking": mode("idle", "READY", ""); f.voice = { state: "speaking", level: 0, speak: wave(0.8), attentive: false, heard: "what time is it", said: "It is nineteen forty-one. Anything else?", note: "" }; break;
    case "working":
      mode("working", "RUNNING", "step 2 of 4"); withGoal(["verified", "running", "pending", "pending"], [true]);
      f.active = "claude/sonnet"; f.voice.state = "thinking";
      f.stats = { elapsed: "00:27", steps: "1/4", checks: "1/1", brain: "claude", cost: "$0.024", last_call_ms: 4210 }; break;
    case "waiting": case "approval":
      mode("waiting", "NEEDS YOU", "approval required"); withGoal(["verified", "waiting", "pending", "pending"], [true]);
      f.stats = { elapsed: "00:41", steps: "1/4", checks: "1/1", brain: "-", cost: "$0.031", last_call_ms: 4210 };
      if (scenario === "approval") f.approvals = [APPROVAL]; break;
    case "ok":
      mode("ok", "VERIFIED", "2 checks passed"); withGoal(["verified", "verified", "verified", "verified"], [true, true]); f.pipeline.sealed = true;
      f.shock = 1; f.stats = { elapsed: "00:52", steps: "4/4", checks: "2/2", brain: "-", cost: "$0.048", last_call_ms: 3890 }; break;
    case "bad":
      mode("bad", "FAILED", "step run_hello verification failed (rolled back)"); withGoal(["verified", "failed", "pending", "pending"], [true, false]);
      f.stats = { elapsed: "00:38", steps: "1/4", checks: "1/2", brain: "-", cost: "$0.031", last_call_ms: 4210 }; break;
    case "stopping": mode("stopping", "STOPPING", "killing in-flight calls, restoring the workspace"); withGoal(["verified", "running", "pending", "pending"]); break;
  }
  return f;
}

export function isScenario(s: string | null): s is Scenario {
  return ["starting", "idle", "listening", "working", "waiting", "approval", "ok", "bad", "stopping", "speaking"].includes(s ?? "");
}

/** A looping demo: idle -> working -> approval -> verified -> failed ... for development (`?mock=demo`). */
export function demoFrame(t: number): Frame {
  const cycle: [Scenario, number][] = [["idle", 5], ["listening", 4], ["working", 8], ["approval", 6], ["ok", 6], ["speaking", 4], ["bad", 6]];
  const total = cycle.reduce((a, [, d]) => a + d, 0);
  let u = t % total;
  for (const [s, d] of cycle) {
    if (u < d) return mockFrame(s, t);
    u -= d;
  }
  return mockFrame("idle", t);
}
