# PRAXIS interface

The window you see is a web interface: **TypeScript + Three.js (WebGL)**, built with Vite, served to an app-mode Edge/Chrome window by a small local
server in the Python engine (`praxis/ui/`). You never need Node to *use* PRAXIS: the built interface is committed in `../praxis/ui/static`.
Node is only for working on how it looks.

```
npm ci              install (once)
npm run dev         live-reload at http://localhost:5173/?mock=working   (a scripted engine, no Python needed)
npm run typecheck   strict TypeScript
npm test            unit tests (vitest): motion, theme, protocol parsing, formatting
npm run build       build into ../praxis/ui/static   (commit the result)
npm run e2e         the real interface in Chromium against the real Python engine (needs a Chromium: set CHROME_PATH)
npm run shots       screenshots of every state into e2e/out/
```

Mock scenarios (`?mock=`): `starting idle listening speaking working waiting approval ok bad stopping demo`; add `&t=7` for a deterministic moment.

## How it fits together

* `src/protocol.ts` is the contract: the engine streams one `Frame` about ten times a second (Server-Sent Events) and accepts `Command`s. Everything
  on screen is derived from a frame; nothing is invented in the browser. `parseFrame` bounds and sanitises whatever arrives.
* `src/motion.ts` is the animation state (pure maths, unit-tested): state changes glide, real events flare the core and send ripples, a verified goal
  sends a shockwave. JARVIS (cool, conversing) and FRIDAY (warm, executing) are the `persona` number in each state's row of `src/theme.json`.
* `src/scene/` is the hologram: an exploded arc reactor, three tilted gyro rings that are the real PLAN / ACT / VERIFY pipeline, the holo table,
  projector beam, particles, bloom and a projector-flaw post pass. `src/hud/` is the glass interface (DOM + SVG) over it.
* `src/theme.json` is the look as data (colours, fonts, effect strengths, the per-state motion table). Put overrides in `~/.praxis/theme.json`.
