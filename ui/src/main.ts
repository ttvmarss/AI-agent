import "./styles/base.css";
import "./styles/hud.css";
import { DEFAULT_THEME, cssVars, mergeTheme } from "./theme";
import { EMPTY_FRAME, type Command, type Frame } from "./protocol";
import { HoloScene } from "./scene";
import { Hud } from "./hud";
import { demoFrame, isScenario, mockFrame } from "./mock";
import { LiveTransport, fetchTheme } from "./transport";

declare global { interface Window { __ready?: boolean; __praxis?: { frame: Frame; sent: Command[] } } }

async function boot() {
  const params = new URLSearchParams(location.search);
  const mock = params.get("mock");
  const live = !mock;
  const theme = live ? mergeTheme(await fetchTheme()) : DEFAULT_THEME;
  for (const [k, v] of Object.entries(cssVars(theme))) document.documentElement.style.setProperty(k, v);
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches || params.has("reduced");
  document.body.classList.toggle("reduced", reduced);

  const canvas = document.getElementById("scene") as HTMLCanvasElement;
  const scene = new HoloScene(canvas, theme, reduced);
  const sent: Command[] = [];
  let frame: Frame = EMPTY_FRAME;
  const transport = live ? new LiveTransport() : null;
  const send = (c: Command) => { sent.push(c); transport?.send(c); };
  const hud = new Hud(document.getElementById("hud")!, send);
  window.__praxis = { frame, sent };
  transport?.start((f) => { frame = f; window.__praxis!.frame = f; }, (ok) => hud.setLinked(ok));

  const frameAt = (t: number): Frame => (mock === "demo" ? demoFrame(t) : isScenario(mock) ? mockFrame(mock, t) : frame);
  let t = 0, last = performance.now();
  const step = (dt: number) => {
    t += dt;
    if (mock) frame = frameAt(t);
    scene.update(frame, dt);
    hud.update(frame, scene.motion, dt);
  };
  const size = () => scene.resize(innerWidth, innerHeight, Math.min(devicePixelRatio, 2));
  addEventListener("resize", size);
  addEventListener("pointermove", (e) => scene.setPointer((e.clientX / innerWidth - 0.5) * 2, -(e.clientY / innerHeight - 0.5) * 2));
  size();

  const fixed = params.get("t");                                   // ?t=7 : render a deterministic moment (screenshots, tests)
  if (fixed !== null) {
    for (let i = 0, n = Math.round(parseFloat(fixed) * 30); i < n; i++) step(1 / 30);
    scene.render(33);
    await new Promise((r) => setTimeout(r, 1300));                 // let the panel animations finish
    scene.render(33);
    window.__ready = true;
    return;
  }
  const loop = (now: number) => {
    const dt = Math.min(0.1, (now - last) / 1000);
    last = now;
    step(dt);
    scene.render(dt * 1000);
    requestAnimationFrame(loop);
  };
  requestAnimationFrame(loop);
  window.__ready = true;
}

void boot();
