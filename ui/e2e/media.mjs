// Regenerates the screenshots used in the docs:  npm run media
import { start } from "./lib.mjs";
import path from "node:path";
import { root } from "./lib.mjs";
const media = path.resolve(root, "..", "docs", "media");
const env = await start({ viewport: { width: 1600, height: 900 } });
try {
  for (const [scenario, file] of [["idle", "ui-idle"], ["working", "ui-working"], ["ok", "ui-verified"], ["approval", "ui-approval"]]) {
    await env.page.goto(`${env.url}/?mock=${scenario}&t=7`);
    await env.page.waitForFunction(() => window.__ready === true, null, { timeout: 120000 });
    if (scenario === "approval") await env.page.evaluate(() => { const b = document.querySelector("#authYes"); if (b) b.disabled = false; });
    await env.page.waitForTimeout(500);
    await env.page.screenshot({ path: path.join(media, `${file}.jpg`), type: "jpeg", quality: 86 });
    console.log("saved", file);
  }
} finally { await env.close(); }
