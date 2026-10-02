import type { Brain, Frame, LogLine } from "../protocol";
import { Memo, esc, h, panel } from "./dom";
import { CHECK_ICON, STEP_ICON, brainIcon } from "./icons";
import { clock, ms } from "../util/format";

/** The four glass panels. Each one shows only real data from the Frame; each re-renders only when its own data changes. */

const COST_COLOR = { 0: "var(--c-ok)", 1: "var(--accent)", 2: "var(--c-violet)" } as const;

export class Mission {
  readonly root: HTMLElement;
  private readonly body: HTMLElement;
  private readonly memo: Memo;
  private readonly aside: HTMLElement;
  constructor() {
    const p = panel("MISSION", "mission", 0, "");
    this.root = p.root;
    this.body = p.body;
    this.aside = p.aside;
    this.memo = new Memo(this.body);
  }
  update(f: Frame) {
    const has = f.pipeline.plan !== "none" || f.pipeline.steps.length > 0 || f.pipeline.checks.length > 0;
    const done = f.pipeline.steps.filter((s) => s.state === "verified" || s.state === "ran").length;
    this.aside.textContent = has ? `${done}/${f.pipeline.steps.length}` : "";
    this.memo.set([f.goal, f.pipeline, f.progress, f.info.hint, f.mode === "starting"], () => {
      if (!has) {
        const hint = f.info.hint ? `<div class="hint" style="color:var(--c-warn)">${esc(f.info.hint)}</div>` : `<div class="hint">Talk to me. Say what you want done.<br/>I plan it, do it, and prove it.</div>`;
        return `<div class="standby">${f.mode === "starting" ? "INITIALISING" : "STANDING BY"}</div>${hint}`;
      }
      const steps = f.pipeline.steps.map((s) => `<li class="step" data-s="${esc(s.state)}">${STEP_ICON[s.state] ?? STEP_ICON.pending}<span class="lbl" title="${esc(s.label)}">${esc(s.label)}</span><span class="st">${esc(s.state)}</span></li>`).join("");
      const checks = f.pipeline.checks.map((c) => `<li class="step" data-s="${c.ok ? "verified" : "failed"}">${c.ok ? CHECK_ICON.ok : CHECK_ICON.bad}<span class="lbl" title="${esc(c.label)}">${esc(c.label)}</span><span class="st">${c.ok ? "passed" : "failed"}</span></li>`).join("");
      const plan = f.pipeline.plan === "planning" ? `<div class="sect">PLANNING</div><ul class="rows"><li class="step" data-s="running">${STEP_ICON.running}<span class="lbl">Working out how</span><span class="st">analysing</span></li></ul>` : "";
      return `<p class="goal" title="${esc(f.goal)}">${esc(f.goal || f.subtitle)}</p>${plan}${steps ? `<div class="sect">STEPS</div><ul class="rows">${steps}</ul>` : ""}${checks ? `<div class="sect">CHECKS</div><ul class="rows">${checks}</ul>` : ""}<div class="progress"><b style="width:${Math.round(f.progress * 100)}%"></b></div>`;
    });
  }
}

export class Minds {
  readonly root: HTMLElement;
  private readonly memo: Memo;
  private readonly aside: HTMLElement;
  private readonly body: HTMLElement;
  constructor(private readonly onFocus: (family: string) => void) {
    const p = panel("MINDS", "minds", 1, "");
    this.root = p.root;
    this.body = p.body;
    this.aside = p.aside;
    this.memo = new Memo(this.body);
    this.body.style.overflow = "hidden";
  }
  /** DOM element of a brain's row, so the stream of sparks can be drawn to it. */
  rowOf(family: string): HTMLElement | null {
    return this.body.querySelector(`[data-fam="${CSS.escape(family)}"]`);
  }
  update(f: Frame) {
    this.aside.textContent = f.brains.length ? `${f.settings.models} MODELS` : "";
    const activeFam = f.active.split("/")[0] ?? "";
    this.memo.set([f.brains, activeFam], () => {
      if (!f.brains.length) return `<div class="hint">No AI models yet. Sign in to Claude, Codex or Factory, install Ollama, or add a free key.</div>`;
      return f.brains.map((b) => this.row(b, b.family === activeFam)).join("");
    });
  }
  private row(b: Brain, active: boolean): string {
    let sub = "", cls = "";
    if (b.blocked) [sub, cls] = ["blocked by data class", "bad"];
    else if (b.cooling_s) [sub, cls] = [`resting ${Math.floor(b.cooling_s / 60) + 1} m`, "warn"];
    else if (b.pressure >= 0.9) [sub, cls] = [`${Math.round(b.pressure * 100)}% spent`, "bad"];
    else if (b.pressure >= 0.6) [sub, cls] = [`${Math.round(b.pressure * 100)}% spent`, "warn"];
    else if (active) [sub, cls] = ["calling…", "live"];
    else sub = b.calls_24h ? `${b.calls_24h} calls today` : "ready";
    const gauge = b.pressure >= 0.9 ? "var(--c-bad)" : b.pressure >= 0.6 ? "var(--c-warn)" : "var(--accent)";
    const segs = 20;
    const on = Math.round(b.pressure * segs);
    const meter = Array.from({ length: segs }, (_, i) => `<i class="${i < on ? "on" : ""}"></i>`).join("");
    const mcol = b.pressure >= 0.9 ? "var(--c-bad)" : b.pressure >= 0.6 ? "var(--c-warn)" : "var(--accent)";
    return `<div class="brain" data-fam="${esc(b.family)}" data-active="${active ? 1 : 0}" data-blocked="${b.blocked ? 1 : 0}" title="${esc(b.models.map((m) => m.name).join("\n"))}">
      ${brainIcon(b.pressure, COST_COLOR[b.cost_class], gauge, b.blocked)}<div><div class="nm">${esc(b.name)}</div><div class="sb ${cls}">${esc(sub)}</div><div class="meter" style="--m:${mcol}">${meter}</div></div></div>`;
  }
}

export class Stream {
  readonly root: HTMLElement;
  private readonly log: HTMLElement;
  private seen = -1;
  constructor() {
    const p = panel("EVENT STREAM", "stream", 2, "LIVE");
    this.root = p.root;
    this.log = h("div", { class: "log", role: "log", "aria-live": "polite", "aria-label": "Event stream" });
    p.body.appendChild(this.log);
    p.body.style.minHeight = "0";
  }
  update(f: Frame) {
    const lines = f.log.slice(-9);
    const last = lines.length ? lines[lines.length - 1]!.id : -1;
    if (last === this.seen && this.log.childElementCount === lines.length) return;
    const first = this.seen === -1;
    this.log.innerHTML = lines.map((l: LogLine, i) => `<div class="ln${!first && l.id > this.seen ? " new" : ""}" data-l="${esc(l.level)}" style="opacity:${(0.35 + 0.65 * ((i + 1) / lines.length)).toFixed(2)}"><time>${esc(l.time)}</time><span title="${esc(l.text)}">${esc(l.text)}</span></div>`).join("");
    this.seen = last;
  }
}

export class Telemetry {
  readonly root: HTMLElement;
  private readonly body: HTMLElement;
  private readonly memo: Memo;
  private readonly dock: HTMLElement;
  constructor(private readonly onCycle: (what: "data" | "strategy") => void, private readonly onWorkspace: () => void) {
    const p = panel("TELEMETRY", "telemetry", 3, "");
    this.root = p.root;
    this.body = h("dl", { class: "kv" });
    this.dock = h("div", { class: "dock" });
    p.body.append(this.body, this.dock);
    this.memo = new Memo(this.body);
    this.dock.addEventListener("click", (e) => {
      const t = (e.target as HTMLElement).closest("button");
      if (!t) return;
      const w = t.getAttribute("data-w");
      if (w === "workspace") this.onWorkspace();
      else this.onCycle(w as "data" | "strategy");
    });
  }
  update(f: Frame) {
    const s = f.stats;
    const has = s.elapsed || s.cost;
    this.memo.set([s, has], () => {
      if (!has) return `<dt>STATUS</dt><dd style="color:var(--c-dim)">awaiting a goal</dd>`;
      return [["ELAPSED", s.elapsed || "—"], ["STEPS", s.steps || "—"], ["CHECKS", s.checks || "—"], ["BRAIN", s.brain || "—"], ["COST", s.cost || "—"], ["LAST CALL", ms(s.last_call_ms)]]
        .map(([k, v]) => `<dt>${k}</dt><dd>${esc(String(v))}</dd>`).join("");
    });
    const sig = `${f.settings.data_class}|${f.settings.strategy}|${f.info.workspace_name}`;
    if (this.dock.getAttribute("data-sig") !== sig) {
      this.dock.setAttribute("data-sig", sig);
      this.dock.innerHTML = `<button class="tog" data-w="strategy" title="F3: how PRAXIS picks a model">ROUTING <b>${esc(f.settings.strategy)}</b></button>
        <button class="tog" data-w="data" title="F2: what data a model may see">DATA <b>${esc(f.settings.data_class)}</b></button>
        <button class="tog" data-w="workspace" title="Ctrl+O: the folder PRAXIS works in">FOLDER <b>${esc(f.info.workspace_name || "—")}</b></button>`;
    }
  }
}

export { clock };
