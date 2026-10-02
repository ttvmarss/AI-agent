import type { Frame } from "../protocol";
import type { Motion } from "../motion";
import { clock, decode } from "../util/format";
import { esc, h } from "./dom";
import { caption } from "./state";

/** The top bar (wordmark, clock, link light) and the caption under the orb: what PRAXIS is doing, in two lines, and what it is saying. */
export class TopBar {
  readonly root = h("header", { id: "top" });
  private readonly clockEl: HTMLElement;
  private readonly meta: HTMLElement;
  constructor() {
    this.root.innerHTML = `<div class="brand"><span class="word">PRAXIS</span><span class="rule"></span></div><div class="sys"><span class="meta mono" id="meta"></span><span class="clock mono" id="clock">--:--:--</span><i class="dot" title="engine linked"></i></div>`;
    this.clockEl = this.root.querySelector("#clock") as HTMLElement;
    this.meta = this.root.querySelector("#meta") as HTMLElement;
  }
  update(f: Frame) {
    this.clockEl.textContent = clock();
    this.meta.textContent = [f.info.workspace_name && f.info.workspace_name.toUpperCase(), f.info.build && f.info.build.split(" ")[0]].filter(Boolean).join("  ·  ");
  }
}

export class CaptionStrip {
  readonly root = h("div", { id: "caption" });
  private readonly stateEl: HTMLElement;
  private readonly lineEl: HTMLElement;
  readonly typer: HTMLElement;
  readonly input: HTMLInputElement;
  private last = "";
  private t = 1;
  private line = "";
  private lineT = 1;

  constructor(private readonly onSubmit: (text: string) => void) {
    this.root.innerHTML = `<div class="state cap" id="stateText" aria-live="polite"></div><div class="line" id="lineText"></div>
      <form id="typer"><input id="typed" type="text" autocomplete="off" spellcheck="false" aria-label="Type what you want done" placeholder="Voice is off. Type what you want done, then press Enter." /></form>
      <div class="keys mono">${["ESC|STOP", "F2|DATA", "F3|ROUTING", "F4|MIC", "CTRL+O|FOLDER"].map((k) => { const [a, b] = k.split("|"); return `<kbd>${a}</kbd> ${b}`; }).join("   ")}</div>`;
    this.stateEl = this.root.querySelector("#stateText") as HTMLElement;
    this.lineEl = this.root.querySelector("#lineText") as HTMLElement;
    this.typer = this.root.querySelector("#typer") as HTMLElement;
    this.input = this.root.querySelector("#typed") as HTMLInputElement;
    this.typer.addEventListener("submit", (e) => {
      e.preventDefault();
      const v = this.input.value.trim();
      if (v) {
        this.onSubmit(v);
        this.input.value = "";
      }
    });
  }

  update(f: Frame, m: Motion, dt: number) {
    const c = caption(f);
    if (c.state !== this.last) {
      this.last = c.state;
      this.t = 0;
    }
    this.t = Math.min(1, this.t + dt / 0.4);
    this.stateEl.textContent = this.t < 1 ? decode(c.state, this.t) : c.state;
    this.stateEl.setAttribute("aria-label", c.state);
    this.stateEl.style.setProperty("--tone", c.tone === "accent" ? "var(--accent)" : `var(--c-${c.tone})`);
    // the line types itself out, like a subtitle
    if (c.line !== this.line) {
      const grows = c.line.startsWith(this.line) && this.line.length > 0;
      this.line = c.line;
      this.lineT = grows ? this.lineT : 0;
    }
    this.lineT = Math.min(1, this.lineT + dt / Math.max(0.4, this.line.length * 0.018));
    this.lineEl.textContent = this.line.slice(0, Math.ceil(this.line.length * this.lineT));
    this.typer.classList.toggle("on", f.info.can_type);
    void m;
  }
}

export { esc };
