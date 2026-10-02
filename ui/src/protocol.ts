/** The contract between the PRAXIS engine (Python) and this interface. The engine sends one `Frame` about ten times a second
 *  (Server-Sent Events) and accepts `Command`s. Everything on screen is derived from a Frame; nothing is invented in the browser. */

export type Mode = "starting" | "idle" | "working" | "waiting" | "ok" | "bad" | "stopping" | "stopped";
export type StepState = "pending" | "running" | "waiting" | "ran" | "verified" | "denied" | "failed" | "rolled back";
export type PlanState = "none" | "planning" | "ready" | "failed";
export type Level = "info" | "ok" | "warn" | "bad";
export type VoiceState = "off" | "listening" | "hearing" | "thinking" | "speaking" | "muted" | "offline";
export type DataClass = "private" | "project" | "open";
export type Strategy = "frugal" | "balanced" | "quality";

export interface Step {
  label: string;
  state: StepState;
}
export interface Check {
  label: string;
  ok: boolean;
}
export interface Pipeline {
  plan: PlanState;
  steps: Step[];
  checks: Check[];
  sealed: boolean;
}
export interface BrainModel {
  name: string;
  tier: string;
  score: number | null;
  cooling_s: number;
}
/** One of the user's AIs (a family: claude, codex, droid, devin, ollama, ...). */
export interface Brain {
  family: string;
  name: string; // display name, upper case
  cost_class: 0 | 1 | 2; // 0 local, 1 free cloud, 2 subscription
  privacy: string;
  pressure: number; // 0..1 of the allowance spent
  cooling_s: number; // resting after a rate limit
  blocked: boolean; // forbidden by this goal's data class
  models: BrainModel[];
  calls_24h: number;
  cost_24h: number;
}
export interface Voice {
  state: VoiceState;
  level: number; // 0..1 loudness of the microphone
  speak: number; // 0..1 loudness of PRAXIS's own voice
  attentive: boolean;
  heard: string; // the last thing it understood you to say
  said: string; // the sentence it is saying right now (shown as the subtitle)
  note: string; // why the voice is degraded or off, if it is
}
export interface LogLine {
  id: number; // strictly increasing: new ids are new real events
  time: string;
  text: string;
  level: Level;
}
export interface Approval {
  id: string;
  tool: string;
  cls: number;
  risky: boolean;
  reason: string;
  summary: string; // one human sentence: "open Google Chrome"
  detail: string; // the exact action
}
export interface Settings {
  data_class: DataClass;
  strategy: Strategy;
  models: number;
}
export interface Info {
  build: string;
  workspace: string;
  workspace_name: string;
  hint: string;
  sandbox: string;
  sandbox_strong: boolean;
  recent: string[];
  can_type: boolean; // voice could not start: a typing line is shown
}

export interface Frame {
  v: 1;
  t: number; // engine clock, seconds
  mode: Mode;
  title: string;
  subtitle: string;
  goal: string;
  progress: number;
  pipeline: Pipeline;
  active: string; // "family/model" being called right now, or ""
  brains: Brain[];
  stats: { elapsed: string; steps: string; checks: string; brain: string; cost: string; last_call_ms: number | null };
  voice: Voice;
  log: LogLine[];
  approvals: Approval[];
  settings: Settings;
  info: Info;
  shock: number; // increments each time a goal verifies
}

export type Command =
  | { cmd: "submit"; text: string }
  | { cmd: "stop" }
  | { cmd: "approve"; id: string; ok: boolean }
  | { cmd: "set_data"; value: DataClass }
  | { cmd: "set_strategy"; value: Strategy }
  | { cmd: "mute"; value?: boolean }
  | { cmd: "resume" }
  | { cmd: "undo" }
  | { cmd: "open_workspace"; path: string }
  | { cmd: "quit" };

export const EMPTY_FRAME: Frame = {
  v: 1,
  t: 0,
  mode: "starting",
  title: "STARTING",
  subtitle: "detecting hardware, tools and sandbox",
  goal: "",
  progress: 0,
  pipeline: { plan: "none", steps: [], checks: [], sealed: false },
  active: "",
  brains: [],
  stats: { elapsed: "", steps: "", checks: "", brain: "", cost: "", last_call_ms: null },
  voice: { state: "off", level: 0, speak: 0, attentive: false, heard: "", said: "", note: "" },
  log: [],
  approvals: [],
  settings: { data_class: "project", strategy: "balanced", models: 0 },
  info: { build: "", workspace: "", workspace_name: "", hint: "", sandbox: "", sandbox_strong: false, recent: [], can_type: false },
  shock: 0,
};

/** Defensive parse of whatever arrives over the wire: unknown fields are ignored, wrong types fall back to the empty frame's values,
 *  so a half-broken engine message can never crash the interface. */
export function parseFrame(raw: unknown): Frame | null {
  if (!raw || typeof raw !== "object") return null;
  const o = raw as Record<string, unknown>;
  if (o["v"] !== 1) return null;
  const f: Frame = structuredClone(EMPTY_FRAME);
  const str = (x: unknown, d: string) => (typeof x === "string" ? x : d);
  const num = (x: unknown, d: number) => (typeof x === "number" && Number.isFinite(x) ? x : d);
  const arr = <T>(x: unknown): T[] => (Array.isArray(x) ? (x as T[]) : []);
  f.t = num(o["t"], 0);
  const modes: Mode[] = ["starting", "idle", "working", "waiting", "ok", "bad", "stopping", "stopped"];
  f.mode = modes.includes(o["mode"] as Mode) ? (o["mode"] as Mode) : "idle";
  f.title = str(o["title"], "").slice(0, 60);
  f.subtitle = str(o["subtitle"], "").slice(0, 200);
  f.goal = str(o["goal"], "").slice(0, 400);
  f.progress = Math.min(1, Math.max(0, num(o["progress"], 0)));
  f.active = str(o["active"], "");
  f.shock = num(o["shock"], 0);
  const p = (o["pipeline"] ?? {}) as Record<string, unknown>;
  const plans: PlanState[] = ["none", "planning", "ready", "failed"];
  f.pipeline = {
    plan: plans.includes(p["plan"] as PlanState) ? (p["plan"] as PlanState) : "none",
    steps: arr<Step>(p["steps"]).slice(0, 40).map((s) => ({ label: str(s?.label, "step").slice(0, 120), state: str(s?.state, "pending") as StepState })),
    checks: arr<Check>(p["checks"]).slice(0, 40).map((c) => ({ label: str(c?.label, "check").slice(0, 120), ok: !!c?.ok })),
    sealed: !!p["sealed"],
  };
  f.brains = arr<Brain>(o["brains"]).slice(0, 24).map((b) => ({
    family: str(b?.family, "?"),
    name: str(b?.name, str(b?.family, "?")).toUpperCase(),
    cost_class: ([0, 1, 2].includes(b?.cost_class as number) ? b.cost_class : 1) as 0 | 1 | 2,
    privacy: str(b?.privacy, ""),
    pressure: Math.min(1, Math.max(0, num(b?.pressure, 0))),
    cooling_s: Math.max(0, num(b?.cooling_s, 0)),
    blocked: !!b?.blocked,
    models: arr<BrainModel>(b?.models).slice(0, 12),
    calls_24h: num(b?.calls_24h, 0),
    cost_24h: num(b?.cost_24h, 0),
  }));
  const s = (o["stats"] ?? {}) as Record<string, unknown>;
  f.stats = { elapsed: str(s["elapsed"], ""), steps: str(s["steps"], ""), checks: str(s["checks"], ""), brain: str(s["brain"], ""), cost: str(s["cost"], ""),
              last_call_ms: typeof s["last_call_ms"] === "number" ? (s["last_call_ms"] as number) : null };
  const v = (o["voice"] ?? {}) as Record<string, unknown>;
  const vs: VoiceState[] = ["off", "listening", "hearing", "thinking", "speaking", "muted", "offline"];
  f.voice = { state: vs.includes(v["state"] as VoiceState) ? (v["state"] as VoiceState) : "off", level: Math.min(1, Math.max(0, num(v["level"], 0))),
              speak: Math.min(1, Math.max(0, num(v["speak"], 0))), attentive: !!v["attentive"], heard: str(v["heard"], "").slice(0, 200), said: str(v["said"], "").slice(0, 200), note: str(v["note"], "").slice(0, 200) };
  f.log = arr<LogLine>(o["log"]).slice(-40).map((l) => ({ id: num(l?.id, 0), time: str(l?.time, ""), text: str(l?.text, "").slice(0, 160), level: str(l?.level, "info") as Level }));
  f.approvals = arr<Approval>(o["approvals"]).slice(0, 5).map((a) => ({ id: str(a?.id, ""), tool: str(a?.tool, ""), cls: num(a?.cls, 3), risky: !!a?.risky,
    reason: str(a?.reason, "").slice(0, 300), summary: str(a?.summary, "").slice(0, 200), detail: str(a?.detail, "").slice(0, 600) }));
  const st = (o["settings"] ?? {}) as Record<string, unknown>;
  f.settings = { data_class: str(st["data_class"], "project") as DataClass, strategy: str(st["strategy"], "balanced") as Strategy, models: num(st["models"], 0) };
  const i = (o["info"] ?? {}) as Record<string, unknown>;
  f.info = { build: str(i["build"], ""), workspace: str(i["workspace"], ""), workspace_name: str(i["workspace_name"], ""), hint: str(i["hint"], "").slice(0, 400),
             sandbox: str(i["sandbox"], ""), sandbox_strong: !!i["sandbox_strong"], recent: arr<string>(i["recent"]).slice(0, 8).map(String), can_type: !!i["can_type"] };
  return f;
}
