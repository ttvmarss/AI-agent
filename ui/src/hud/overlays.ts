import type { Approval, Frame } from "../protocol";
import type { Motion } from "../motion";
import { decode } from "../util/format";
import { esc, h } from "./dom";

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
  private static readonly LINES = ["KERNEL", "GUARD", "VERIFICATION", "VOICE"];
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
