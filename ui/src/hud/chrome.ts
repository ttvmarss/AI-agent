import type { Frame, VoiceState } from "../protocol";
import type { Motion } from "../motion";
import type { Theme } from "../theme";
import { clock, decode } from "../util/format";
import { esc, h } from "./dom";

/** The top bar (the two minds, the wordmark and state, clock and voice) and the voice strip at the bottom of the stage. */

const VOICE_LABEL: Record<VoiceState, string> = { off: "", listening: "LISTENING", hearing: "HEARING", thinking: "THINKING", speaking: "SPEAKING", muted: "MIC OFF · F4", offline: "NO MICROPHONE" };
const VOICE_VAR: Record<VoiceState, string> = { off: "accent", listening: "accent", hearing: "accent", thinking: "violet", speaking: "ok", muted: "warn", offline: "bad" };
const MODE_VAR: Record<string, string> = { ok: "ok", bad: "bad", waiting: "warn", stopping: "warn", stopped: "warn", starting: "muted" };

export class TopBar {
  readonly root = h("header", { id: "top" });
  private readonly mindBar: HTMLElement;
  private readonly state: HTMLElement;
  private readonly sub: HTMLElement;
  private readonly clockEl: HTMLElement;
  private readonly meta: HTMLElement;
  private readonly chip: HTMLElement;
  private readonly eq: HTMLElement[] = [];
  private lastTitle = "";
  private titleT = 1;

  constructor(private readonly theme: Theme) {
    this.root.innerHTML = `
      <div class="minds" aria-label="Active mind"><div class="row"><span class="name jarvis"><i></i><span class="cap">JARVIS</span></span><span class="name friday"><i></i><span class="cap">FRIDAY</span></span></div>
        <div class="bar"><b></b></div><div class="role">CONVERSING</div></div>
      <div id="brand"><div class="word">PRAXIS</div><div class="state cap"><i></i><span id="stateText"></span></div><div class="sub" id="subText"></div></div>
      <div id="sys"><div class="clock" id="clock">--:--:--</div>
        <div class="chip" id="vchip" style="display:none"><i></i><span id="vtext"></span><span class="eq"><b></b><b></b><b></b><b></b><b></b></span></div>
        <div class="meta" id="meta"></div></div>`;
    const q = (s: string) => this.root.querySelector(s) as HTMLElement;
    this.mindBar = q(".minds .role");
    this.state = q("#stateText");
    this.sub = q("#subText");
    this.clockEl = q("#clock");
    this.meta = q("#meta");
    this.chip = q("#vchip");
    this.root.querySelectorAll(".eq b").forEach((b) => this.eq.push(b as HTMLElement));
  }

  update(f: Frame, m: Motion, dt: number) {
    const root = document.documentElement.style;
    const [r, g, b] = m.accent().map(Math.round) as [number, number, number];
    const [hr, hg, hb] = m.hot().map(Math.round) as [number, number, number];
    root.setProperty("--accent-rgb", `${r} ${g} ${b}`);
    root.setProperty("--hot-rgb", `${hr} ${hg} ${hb}`);
    root.setProperty("--persona", m.persona.toFixed(3));
    const label = this.theme.modeLabels[f.mode] ?? f.title;
    const title = f.mode === "idle" || f.mode === "working" || f.mode === "ok" || f.mode === "bad" ? f.title || label : label;
    if (title !== this.lastTitle) {
      this.lastTitle = title;
      this.titleT = 0;
    }
    this.titleT = Math.min(1, this.titleT + dt / 0.45);
    this.state.textContent = this.titleT < 1 ? decode(title, this.titleT) : title;
    this.state.setAttribute("aria-label", title);           // the scramble is decoration: assistive technology gets the real word
    const sv = MODE_VAR[f.mode];
    (this.root.querySelector("#brand .state") as HTMLElement).style.setProperty("--state", sv ? `var(--c-${sv})` : "var(--accent)");
    this.sub.textContent = f.subtitle;
    this.mindBar.textContent = m.persona < 0.5 ? "CONVERSING" : "EXECUTING";
    this.clockEl.textContent = clock();
    this.meta.textContent = [f.info.workspace_name && `FOLDER ${f.info.workspace_name.toUpperCase()}`, f.info.sandbox && `SANDBOX ${f.info.sandbox.toUpperCase()}`, f.info.build && `BUILD ${f.info.build.split(" ")[0]}`].filter(Boolean).join("   ·   ");
    const v = f.voice;
    const label2 = VOICE_LABEL[v.state];
    this.chip.style.display = label2 ? "" : "none";
    if (label2) {
      const col = VOICE_VAR[v.state];
      this.chip.style.setProperty("--vc", `var(--c-${col})`);
      this.chip.style.setProperty("--vc-rgb", `var(--c-${col}-rgb)`);
      this.chip.classList.toggle("pulse", v.state === "hearing" || v.state === "speaking" || v.state === "thinking");
      (this.chip.querySelector("#vtext") as HTMLElement).textContent = v.state === "listening" && v.attentive ? "LISTENING · GO AHEAD" : label2;
      const lvl = v.state === "speaking" ? v.speak : v.level;
      this.eq.forEach((e, i) => (e.style.height = `${3 + Math.round(9 * Math.min(1, lvl * 2.2) * (0.5 + 0.5 * Math.sin(performance.now() / 90 + i * 1.3)))}px`));
    }
  }
}

export class VoiceStrip {
  readonly root = h("div", { id: "voice" });
  private readonly heard: HTMLElement;
  private readonly bars: HTMLElement[] = [];
  private readonly hist: number[] = new Array(48).fill(0);
  private acc = 0;
  readonly typer: HTMLElement;
  readonly input: HTMLInputElement;

  constructor(private readonly onSubmit: (text: string) => void) {
    this.root.innerHTML = `<div class="heard" id="heard"></div><div class="wave" id="wave"></div>
      <form id="typer"><input id="typed" type="text" autocomplete="off" spellcheck="false" aria-label="Type what you want done" placeholder="Voice is off. Type what you want done, then press Enter." /></form>
      <div class="keys">${["ESC|STOP", "F2|DATA", "F3|ROUTING", "F4|MIC", "CTRL+O|FOLDER", "CTRL+R|RESUME"].map((k) => { const [a, b] = k.split("|"); return `<kbd>${a}</kbd> ${b}`; }).join("  ·  ")}</div>`;
    this.heard = this.root.querySelector("#heard") as HTMLElement;
    const wave = this.root.querySelector("#wave") as HTMLElement;
    for (let i = 0; i < 48; i++) {
      const b = document.createElement("i");
      wave.appendChild(b);
      this.bars.push(b);
    }
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

  update(f: Frame, dt: number) {
    this.typer.classList.toggle("on", f.info.can_type);
    const v = f.voice;
    const level = v.state === "speaking" ? v.speak : v.state === "hearing" || v.state === "listening" ? v.level : 0;
    this.acc += dt;
    while (this.acc >= 1 / 24) {
      this.acc -= 1 / 24;
      this.hist.shift();
      this.hist.push((this.hist[this.hist.length - 1] ?? 0) * 0.5 + level * 0.5);
    }
    const n = this.bars.length;
    this.bars.forEach((b, i) => {
      const env = Math.sin((Math.PI * (i + 0.5)) / n) ** 0.7;
      const val = this.hist[i] ?? 0;
      b.style.height = `${2 + Math.round(30 * Math.min(1, val * 2) * env * (0.55 + 0.45 * Math.sin(i * 1.9 + performance.now() / 110)))}px`;
      b.style.opacity = String(0.35 + 0.65 * Math.min(1, val * 3 + (i % 8 === 0 ? 0.25 : 0)));
    });
    let html = "";
    if (v.note) html = `<span style="color:var(--c-warn)">${esc(v.note)}</span>`;
    else if (v.heard && (v.state === "hearing" || v.state === "thinking" || v.state === "speaking")) html = `<em>HEARD</em> “${esc(v.heard)}”`;
    else if (f.mode === "idle" && v.state !== "off") html = `<em>SAY WHAT YOU WANT DONE</em>`;
    if (this.heard.getAttribute("data-h") !== html) {
      this.heard.setAttribute("data-h", html);
      this.heard.innerHTML = html;
    }
  }
}
