// Screenshots of the interface in each state, from the scripted mock engine:  npm run shots [scenario...]
import { start, out } from "./lib.mjs";
import path from "node:path";

const all = ["idle", "listening", "working", "approval", "ok", "bad", "stopping", "speaking", "starting"];
const want = process.argv.slice(2).length ? process.argv.slice(2) : all;
const t = process.env.SHOT_T ?? "7";
const w = Number(process.env.SHOT_W ?? 1600), h = Number(process.env.SHOT_H ?? 900);
const env = await start({ viewport: { width: w, height: h } });
try {
  for (const s of want) {
    await env.page.goto(`${env.url}/?mock=${s}&t=${t}`);
    await env.page.waitForFunction(() => window.__ready === true, null, { timeout: 120000 });
    await env.page.waitForTimeout(400);
    const file = path.join(out, `${s}.png`);
    await env.page.screenshot({ path: file });
    console.log("saved", file);
  }
  const errs = env.logs.filter((l) => /error/i.test(l));
  if (errs.length) console.log("console errors:\n" + errs.join("\n"));
} finally { await env.close(); }
