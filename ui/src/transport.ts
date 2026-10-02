import { parseFrame, type Command, type Frame } from "./protocol";

/** How frames arrive and commands leave. The real engine is one Server-Sent-Events stream plus a POST endpoint on the same local origin
 *  (the session cookie authenticates both; see praxis/ui/server.py). */
export interface Transport {
  start(onFrame: (f: Frame) => void, onLink: (ok: boolean) => void): void;
  send(c: Command): void;
  close(): void;
}

export class LiveTransport implements Transport {
  private es: EventSource | null = null;
  private lastAt = 0;
  private timer = 0;
  constructor(private readonly base = "") {}

  start(onFrame: (f: Frame) => void, onLink: (ok: boolean) => void) {
    const open = () => {
      this.es = new EventSource(`${this.base}/api/frames`);
      this.es.onmessage = (ev) => {
        try {
          const f = parseFrame(JSON.parse(ev.data));
          if (f) {
            this.lastAt = performance.now();
            onLink(true);
            onFrame(f);
          }
        } catch {
          /* a malformed message is dropped: the next one is only a tenth of a second away */
        }
      };
      this.es.onerror = () => onLink(false);
    };
    open();
    this.timer = window.setInterval(() => {
      if (this.lastAt && performance.now() - this.lastAt > 3000) onLink(false);
    }, 1000);
  }

  send(c: Command) {
    void fetch(`${this.base}/api/cmd`, { method: "POST", headers: { "Content-Type": "application/json", "X-Praxis": "1" }, body: JSON.stringify(c), credentials: "same-origin" }).catch(() => undefined);
  }

  close() {
    this.es?.close();
    clearInterval(this.timer);
  }
}

export async function fetchTheme(base = ""): Promise<unknown> {
  try {
    const r = await fetch(`${base}/api/theme`, { credentials: "same-origin" });
    return r.ok ? await r.json() : {};
  } catch {
    return {};
  }
}
