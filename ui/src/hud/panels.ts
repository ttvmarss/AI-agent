import type { Brain, Frame, LogLine } from "../protocol";
import { Memo, esc, h } from "./dom";
import { CHECK_ICON, STEP_ICON, brainIcon } from "./icons";
import { plural } from "./state";
import { ms } from "../util/format";

/** The quiet furniture of the screen. Everything is real and everything is small: the mission card appears only while there is a goal, the minds are a
 *  slim column, the event stream is three faint lines, the numbers are one line. */
const COST_COLOR = { 0: "var(--c-ok)", 1: "var(--accent)", 2: "var(--c-violet)" } as const;

export class Mission {
  readonly root = h("section", { class: "card off", id: "mission", "aria-label": "Mission" });
  private readonly memo: Memo;
  constructor() {
    this.root.innerHTML = `<h2 class="cap"><span>MISSION</span><span class="aside mono"></span></h2><div class="body"></div>`;
    this.memo = new Memo(this.root.querySelector(".body") as HTMLElement);
  }
  update(f: Frame) {
    const has = f.pipeline.plan !== "none" || f.pipeline.steps.length > 0 || f.pipeline.checks.length > 0;
    this.root.classList.toggle("off", !has);
    const done = f.pipeline.steps.filter((s) => s.state === "verified" || s.state === "ran").length;
    (this.root.querySelector(".aside") as HTMLElement).textContent = has ? `${done}/${f.pipeline.steps.length}` : "";
    if (!has) return;
    this.memo.set([f.goal, f.pipeline], () => {
      const steps = f.pipeline.steps.map((s) => `<li class="step" data-s="${esc(s.state)}">${STEP_ICON[s.state] ?? STEP_ICON.pending}<span class="lbl" title="${esc(s.label)}">${esc(s.label)}</span></li>`).join("");
      const checks = f.pipeline.checks.map((c) => `<li class="step" data-s="${c.ok ? "verified" : "failed"}">${c.ok ? CHECK_ICON.ok : CHECK_ICON.bad}<span class="lbl" title="${esc(c.label)}">${esc(c.label)}</span></li>`).join("");
      const plan = f.pipeline.plan === "planning" ? `<ul class="rows"><li class="step" data-s="running">${STEP_ICON.running}<span class="lbl">Working out how</span></li></ul>` : "";
      return `<p class="goal" title="${esc(f.goal)}">${esc(f.goal)}</p>${plan}${steps ? `<ul class="rows">${steps}</ul>` : ""}${checks ? `<div class="sect">CHECKS</div><ul class="rows">${checks}</ul>` : ""}`;
    });
  }
}

export class Minds {
  readonly root = h("section", { id: "minds", "aria-label": "Your AIs" });
  private readonly memo: Memo;
  constructor() {
    this.memo = new Memo(this.root);
  }
  rowOf(family: string): HTMLElement | null {
    return this.root.querySelector(`[data-fam="${CSS.escape(family)}"]`);
  }
  update(f: Frame) {
    const activeFam = f.active.split("/")[0] ?? "";
    this.memo.set([f.brains, activeFam], () => f.brains.map((b) => this.row(b, b.family === activeFam)).join(""));
  }
  private row(b: Brain, active: boolean): string {
    let sub = "", cls = "";
    if (b.blocked) [sub, cls] = ["blocked by data class", "bad"];
    else if (b.cooling_s) [sub, cls] = [`resting ${Math.floor(b.cooling_s / 60) + 1} m`, "warn"];
    else if (b.pressure >= 0.6) [sub, cls] = [`${Math.round(b.pressure * 100)}% spent`, b.pressure >= 0.9 ? "bad" : "warn"];
    else if (active) [sub, cls] = ["calling…", "live"];
    const gauge = b.pressure >= 0.9 ? "var(--c-bad)" : b.pressure >= 0.6 ? "var(--c-warn)" : "var(--accent)";
    const tip = [b.name, ...b.models.map((m) => m.name), plural(b.calls_24h, "call") + " today"].join("\n");
    return `<div class="brain" data-fam="${esc(b.family)}" data-active="${active ? 1 : 0}" data-blocked="${b.blocked ? 1 : 0}" title="${esc(tip)}">${brainIcon(b.pressure, COST_COLOR[b.cost_class], gauge, b.blocked)}<span class="nm">${esc(b.name)}</span>${sub ? `<span class="sb ${cls}">${esc(sub)}</span>` : ""}</div>`;
  }
}

export class Stream {
  readonly root = h("div", { id: "stream", role: "log", "aria-live": "polite", "aria-label": "Event stream" });
  private seen = -1;
  update(f: Frame) {
    const lines = f.log.slice(-3);
    const last = lines.length ? lines[lines.length - 1]!.id : -1;
    if (last === this.seen && this.root.childElementCount === lines.length) return;
    const first = this.seen === -1;
    this.root.innerHTML = lines.map((l: LogLine, i) => `<div class="ln${!first && l.id > this.seen ? " new" : ""}" data-l="${esc(l.level)}" style="opacity:${(0.35 + 0.65 * ((i + 1) / lines.length)).toFixed(2)}"><time>${esc(l.time)}</time><span title="${esc(l.text)}">${esc(l.text)}</span></div>`).join("");
    this.seen = last;
  }
}

export class Telemetry {
  readonly root = h("div", { id: "telemetry" });
  private readonly line = h("div", { class: "numbers mono" });
  private readonly dock = h("div", { class: "dock" });
  constructor(private readonly onCycle: (what: "data" | "strategy") => void, private readonly onWorkspace: () => void) {
    this.root.append(this.line, this.dock);
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
    const parts = [s.elapsed && `<b>${esc(s.elapsed)}</b>`, s.steps && `${esc(s.steps)} steps`, s.checks && `${esc(s.checks)} checks`, s.brain && s.brain !== "-" && esc(s.brain), s.cost && esc(s.cost),
                   s.last_call_ms !== null && s.elapsed ? `last ${esc(ms(s.last_call_ms))}` : ""].filter(Boolean);
    const html = parts.join("<i>·</i>");
    if (this.line.getAttribute("data-h") !== html) {
      this.line.setAttribute("data-h", html);
      this.line.innerHTML = html;
    }
    const sig = `${f.settings.data_class}|${f.settings.strategy}|${f.info.workspace_name}|${f.settings.models}`;
    if (this.dock.getAttribute("data-sig") !== sig) {
      this.dock.setAttribute("data-sig", sig);
      this.dock.innerHTML = `<button class="tog" data-w="strategy" title="F3: how PRAXIS picks a model">${esc(f.settings.strategy)}</button><button class="tog" data-w="data" title="F2: what data a model may see">data ${esc(f.settings.data_class)}</button><button class="tog" data-w="workspace" title="Ctrl+O: the folder PRAXIS works in">${esc(f.info.workspace_name || "folder")}</button>`;
    }
  }
}
