import type { Approval, Frame } from "../protocol";
import type { Motion } from "../motion";
import type { Scene } from "./types";
import { decode } from "../util/format";
import { esc, h } from "./dom";

const NS = "http://www.w3.org/2000/svg";

/** Leader-line callouts attached to points on the hologram, and the stream of sparks from the core to the brain being called. */
export class Callouts {
  readonly svg = document.createElementNS(NS, "svg");
  private readonly items: { g: SVGGElement; line: SVGPolylineElement; dot: SVGCircleElement; box: SVGRectElement; k: SVGTextElement; v: SVGTextElement; anchor: "core" | "act" | "verify"; dx: number; dy: number }[] = [];
  private readonly stream = document.createElementNS(NS, "path");
  private readonly streamGlow = document.createElementNS(NS, "path");

  constructor(private readonly minds: { rowOf(f: string): HTMLElement | null }) {
    this.svg.id = "callouts";
    this.svg.setAttribute("aria-hidden", "true");
    this.svg.innerHTML = `<style>@keyframes flow{to{stroke-dashoffset:-24}}.stream{stroke:rgb(var(--accent-rgb));stroke-width:2;stroke-dasharray:3 9;stroke-linecap:round;fill:none;animation:flow .7s linear infinite;filter:drop-shadow(0 0 4px var(--accent))}.streamBase{stroke:rgb(var(--accent-rgb)/.18);stroke-width:1;fill:none}</style>`;
    this.streamGlow.setAttribute("class", "streamBase");
    this.stream.setAttribute("class", "stream");
    this.svg.append(this.streamGlow, this.stream);
    const spec: ["core" | "act" | "verify", number, number][] = [["core", 170, -120], ["act", 230, 60], ["verify", -250, 150]];
    for (const [anchor, dx, dy] of spec) {
      const g = document.createElementNS(NS, "g") as SVGGElement;
      g.innerHTML = `<polyline class="ln"/><circle class="dot" r="3"/><rect class="box" width="150" height="38"/><text class="k" x="10" y="15"></text><text class="v" x="10" y="30"></text>`;
      this.svg.appendChild(g);
      this.items.push({ g, line: g.querySelector("polyline") as SVGPolylineElement, dot: g.querySelector("circle") as SVGCircleElement, box: g.querySelector("rect") as SVGRectElement,
        k: g.querySelector("text.k") as SVGTextElement, v: g.querySelector("text.v") as SVGTextElement, anchor, dx, dy });
    }
  }

  update(f: Frame, scene: Scene, m: Motion) {
    const W = innerWidth, H = innerHeight;
    const lo = W > 1000 ? W * 0.245 : 12, hi = W > 1000 ? W * 0.755 : W - 12;
    const has = f.pipeline.plan !== "none" || f.pipeline.steps.length > 0;
    const texts: Record<string, [string, string]> = {
      core: [m.persona < 0.5 ? "JARVIS · CONVERSING" : "FRIDAY · EXECUTING", f.active ? f.active.split("/")[0]!.toUpperCase() + " IN FLIGHT" : f.stats.brain && f.stats.brain !== "-" ? f.stats.brain.toUpperCase() : `${f.settings.models} MODELS READY`],
      act: ["ACT", `${f.pipeline.steps.filter((s) => s.state === "verified" || s.state === "ran").length} / ${f.pipeline.steps.length} STEPS`],
      verify: ["VERIFY", f.pipeline.sealed ? "SEALED" : `${f.pipeline.checks.filter((c) => c.ok).length} / ${f.pipeline.checks.length} CHECKS`],
    };
    for (const it of this.items) {
      const vis = it.anchor === "core" || has;
      const p = scene.project(it.anchor);
      const show = vis && p.visible && m.reveal(it.anchor === "core" ? 11 : 13) > 0.5;
      it.g.style.display = show ? "" : "none";
      if (!show) continue;
      const bw = 168;
      let lx = p.x + it.dx;
      lx = Math.max(lo, Math.min(hi - bw, it.dx < 0 ? lx - bw : lx));
      const ly = Math.max(100, Math.min(H - 200, p.y + it.dy));
      const ex = it.dx < 0 ? lx + bw : lx;
      it.line.setAttribute("points", `${p.x},${p.y} ${p.x + (it.dx < 0 ? -30 : 30)},${ly + 19} ${ex},${ly + 19}`);
      it.dot.setAttribute("cx", String(p.x)); it.dot.setAttribute("cy", String(p.y));
      it.box.setAttribute("x", String(lx)); it.box.setAttribute("y", String(ly)); it.box.setAttribute("width", String(bw));
      const [k, v] = texts[it.anchor] ?? ["", ""];
      it.k.setAttribute("x", String(lx + 10)); it.k.setAttribute("y", String(ly + 15)); it.k.textContent = k;
      it.v.setAttribute("x", String(lx + 10)); it.v.setAttribute("y", String(ly + 30)); it.v.textContent = v;
    }
    // the stream: from the core to the row of the brain being called right now
    const fam = f.active.split("/")[0] ?? "";
    const row = fam && W > 1000 ? this.minds.rowOf(fam) : null;
    if (row) {
      const c = scene.project("core");
      const r = row.getBoundingClientRect();
      const tx = r.left + 18, ty = r.top + r.height / 2;
      const d = `M ${c.x} ${c.y} C ${c.x + (tx - c.x) * 0.5} ${c.y - 80}, ${tx - (tx - c.x) * 0.3} ${ty}, ${tx} ${ty}`;
      this.stream.setAttribute("d", d); this.streamGlow.setAttribute("d", d);
      this.stream.style.display = this.streamGlow.style.display = "";
    } else this.stream.style.display = this.streamGlow.style.display = "none";
  }
}

/** AUTHORISATION REQUIRED: the approval the engine is waiting for, with the exact action. Deny is the default. */
export class AuthModal {
  readonly root = h("div", { id: "auth", role: "alertdialog", "aria-modal": "true", "aria-labelledby": "authTitle" });
  private current = "";
  private shownAt = 0;
  private readonly approve: HTMLButtonElement;
  private readonly deny: HTMLButtonElement;

  constructor(private readonly send: (id: string, ok: boolean) => void) {
    this.root.innerHTML = `<div class="card"><h3 class="cap" id="authTitle"><i></i>AUTHORISATION REQUIRED<span class="cls mono" id="authCls"></span></h3>
      <div class="what" id="authWhat"></div><pre id="authDetail"></pre><div class="why" id="authWhy"></div>
      <div class="btns"><button class="btn no" id="authNo">Deny</button><button class="btn go" id="authYes" disabled>Approve</button></div></div>`;
    this.approve = this.root.querySelector("#authYes") as HTMLButtonElement;
    this.deny = this.root.querySelector("#authNo") as HTMLButtonElement;
    this.approve.addEventListener("click", () => this.answer(true));
    this.deny.addEventListener("click", () => this.answer(false));
  }

  private answer(ok: boolean) {
    if (!this.current) return;
    if (ok && performance.now() - this.shownAt < (this.risky ? 1500 : 700)) return;     // never approve something you had no time to read
    const id = this.current;
    this.current = "";
    this.root.classList.remove("on");
    this.send(id, ok);
  }
  private risky = false;

  get open(): boolean {
    return !!this.current;
  }

  /** Escape denies: the safe answer is always one key away. */
  denyNow() {
    if (this.current) this.answer(false);
  }

  update(a: Approval | undefined) {
    if (!a) {
      if (this.current) {
        this.current = "";
        this.root.classList.remove("on");
      }
      return;
    }
    if (a.id !== this.current) {
      this.current = a.id;
      this.shownAt = performance.now();
      this.risky = a.risky || a.cls >= 4;
      (this.root.querySelector("#authWhat") as HTMLElement).textContent = a.summary || a.tool;
      (this.root.querySelector("#authDetail") as HTMLElement).textContent = a.detail;
      (this.root.querySelector("#authWhy") as HTMLElement).textContent = a.reason;
      const cls = this.root.querySelector("#authCls") as HTMLElement;
      cls.textContent = `CLASS ${a.cls}`;
      cls.style.color = this.risky ? "var(--c-bad)" : "var(--c-warn)";
      this.approve.textContent = this.risky ? "Approve (risky)" : "Approve";
      this.approve.disabled = true;
      this.root.classList.add("on");
      this.deny.focus();
    }
    const wait = this.risky ? 1500 : 700;
    this.approve.disabled = performance.now() - this.shownAt < wait;
  }
}

/** The start-up sequence: the subsystems announce themselves while the hologram assembles. */
export class BootOverlay {
  readonly root = h("div", { id: "boot", "aria-hidden": "true" });
  private static readonly LINES = ["PRAXIS KERNEL", "CAPABILITY GUARD", "VERIFICATION GATE", "EVENT LOG · HASH CHAIN", "JARVIS · CONVERSATION MIND", "FRIDAY · EXECUTION MIND"];
  constructor() {
    this.root.innerHTML = BootOverlay.LINES.map(() => `<div></div>`).join("");
  }
  update(m: Motion, ready: boolean) {
    const rows = Array.from(this.root.children) as HTMLElement[];
    const b = m.boot;
    rows.forEach((row, i) => {
      const u = Math.max(0, Math.min(1, (b - 0.1 - i * 0.1) / 0.18));
      const text = BootOverlay.LINES[i]!;
      const done = u >= 1 && ready;
      row.innerHTML = u <= 0 ? "" : `${esc(decode(text, u))}${done ? '<span class="ok">ONLINE</span>' : u >= 1 ? '<span class="ok" style="color:var(--c-dim)">…</span>' : ""}`;
    });
    const shown = rows.some((r) => r.innerHTML !== "");
    this.root.style.display = shown ? "" : "none";
    this.root.style.opacity = b >= 1 && ready ? "0" : "1";
  }
}

export class WorkspaceDialog {
  readonly root = h("div", { id: "ws", role: "dialog", "aria-modal": "true", "aria-label": "Choose a project folder" });
  private readonly input: HTMLInputElement;
  private readonly list: HTMLElement;
  constructor(private readonly choose: (path: string) => void) {
    this.root.innerHTML = `<div class="card panel" style="animation:none"><h2 class="cap"><span class="led"></span>PROJECT FOLDER<span class="rule"></span></h2>
      <div class="hint">PRAXIS acts only inside one folder, and can undo everything it does there. Paste a path:</div>
      <input id="wsPath" type="text" spellcheck="false" aria-label="Folder path" /><ul id="wsRecent"></ul>
      <div class="btns" style="display:flex;gap:12px;justify-content:flex-end"><button class="btn no" id="wsCancel">Cancel</button><button class="btn go" id="wsOk">Open</button></div></div>`;
    this.input = this.root.querySelector("#wsPath") as HTMLInputElement;
    this.list = this.root.querySelector("#wsRecent") as HTMLElement;
    const go = () => {
      const v = this.input.value.trim();
      if (v) this.choose(v);
      this.hide();
    };
    this.root.querySelector("#wsOk")!.addEventListener("click", go);
    this.root.querySelector("#wsCancel")!.addEventListener("click", () => this.hide());
    this.input.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
    this.list.addEventListener("click", (e) => {
      const li = (e.target as HTMLElement).closest("li");
      if (li) { this.choose(li.getAttribute("data-p") ?? ""); this.hide(); }
    });
  }
  show(current: string, recent: string[]) {
    this.input.value = current;
    this.list.innerHTML = recent.map((p) => `<li data-p="${esc(p)}">${esc(p)}</li>`).join("");
    this.root.classList.add("on");
    this.input.focus();
    this.input.select();
  }
  hide() {
    this.root.classList.remove("on");
  }
  get open() {
    return this.root.classList.contains("on");
  }
}
