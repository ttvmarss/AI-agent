import type { Command, DataClass, Frame, Strategy } from "../protocol";
import type { Motion } from "../motion";
import type { Theme } from "../theme";
import { h } from "./dom";
import { TopBar, VoiceStrip } from "./chrome";
import { AuthModal, BootOverlay, Callouts, WorkspaceDialog } from "./overlays";
import { Minds, Mission, Stream, Telemetry } from "./panels";
import type { Scene } from "./types";

const DATA_CYCLE: DataClass[] = ["project", "private", "open"];
const STRATEGY_CYCLE: Strategy[] = ["balanced", "frugal", "quality"];

/** The glass interface over the hologram. It owns the DOM, turns each Frame into words and numbers, and turns keys and clicks into Commands. */
export class Hud {
  private readonly top: TopBar;
  private readonly mission = new Mission();
  private readonly stream = new Stream();
  private readonly minds: Minds;
  private readonly telemetry: Telemetry;
  private readonly voice: VoiceStrip;
  private readonly callouts: Callouts;
  private readonly auth: AuthModal;
  private readonly boot = new BootOverlay();
  private readonly ws: WorkspaceDialog;
  private readonly link = h("div", { class: "chip", style: "position:fixed;left:50%;top:84px;transform:translateX(-50%);display:none;--vc:var(--c-warn);--vc-rgb:var(--c-warn-rgb);z-index:15" }, "<i></i>ENGINE LINK LOST · RECONNECTING");
  private frame: Frame | null = null;

  constructor(root: HTMLElement, private readonly theme: Theme, private readonly send: (c: Command) => void) {
    this.top = new TopBar(theme);
    this.voice = new VoiceStrip((text) => this.send({ cmd: "submit", text }));
    this.minds = new Minds(() => undefined);
    this.telemetry = new Telemetry((what) => this.cycle(what), () => this.openWorkspace());
    const left = h("div", { id: "left" });
    left.append(this.mission.root, this.stream.root);
    const right = h("div", { id: "right" });
    right.append(this.minds.root, this.telemetry.root);
    const mid = h("div", { id: "mid" });
    mid.append(this.voice.root);
    root.append(this.top.root, left, mid, right);
    this.callouts = new Callouts(this.minds);
    this.auth = new AuthModal((id, ok) => this.send({ cmd: "approve", id, ok }));
    this.ws = new WorkspaceDialog((path) => this.send({ cmd: "open_workspace", path }));
    document.body.append(this.callouts.svg, this.auth.root, this.boot.root, this.ws.root, this.link);
    addEventListener("keydown", (e) => this.key(e));
  }

  private cycle(what: "data" | "strategy") {
    const f = this.frame;
    if (!f) return;
    if (what === "data") this.send({ cmd: "set_data", value: DATA_CYCLE[(Math.max(0, DATA_CYCLE.indexOf(f.settings.data_class)) + 1) % DATA_CYCLE.length]! });
    else this.send({ cmd: "set_strategy", value: STRATEGY_CYCLE[(Math.max(0, STRATEGY_CYCLE.indexOf(f.settings.strategy)) + 1) % STRATEGY_CYCLE.length]! });
  }

  private openWorkspace() {
    if (this.frame) this.ws.show(this.frame.info.workspace, this.frame.info.recent);
  }

  private key(e: KeyboardEvent) {
    const typing = e.target instanceof HTMLInputElement;
    if (e.key === "Escape") {
      if (this.auth.open) this.auth.denyNow();
      else if (this.ws.open) this.ws.hide();
      else if (typing) (e.target as HTMLInputElement).blur();
      else if (this.frame && (this.frame.mode === "working" || this.frame.mode === "waiting" || this.frame.mode === "stopping")) this.send({ cmd: "stop" });
      e.preventDefault();
    } else if (e.key === "F2") { e.preventDefault(); this.cycle("data"); }
    else if (e.key === "F3") { e.preventDefault(); this.cycle("strategy"); }
    else if (e.key === "F4") { e.preventDefault(); this.send({ cmd: "mute" }); }
    else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "o") { e.preventDefault(); this.openWorkspace(); }
    else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "r") { e.preventDefault(); this.send({ cmd: "resume" }); }
    else if (e.key === "." && (e.ctrlKey || e.metaKey)) { e.preventDefault(); this.send({ cmd: "stop" }); }
  }

  setLinked(ok: boolean) {
    this.link.style.display = ok ? "none" : "";
  }

  update(f: Frame, scene: Scene, m: Motion, dt: number) {
    this.frame = f;
    this.top.update(f, m, dt);
    this.mission.update(f);
    this.stream.update(f);
    this.minds.update(f);
    this.telemetry.update(f);
    this.voice.update(f, dt);
    this.callouts.update(f, scene, m);
    this.auth.update(f.approvals[0]);
    this.boot.update(m, f.mode !== "starting");
  }
}
