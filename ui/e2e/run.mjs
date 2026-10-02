// End-to-end: the real built interface in Chromium against the real Python engine (scripted fake model).  npm run build && npm run e2e
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { chromePath, out, root } from "./lib.mjs";

fs.mkdirSync(out, { recursive: true });
const repo = path.resolve(root, "..");
const python = process.env.PYTHON ?? "python3";
const results = [];

async function engine(scenario) {
  const p = spawn(python, ["-m", "tests.ui_fake_server", scenario], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, stdio: ["ignore", "pipe", "pipe"] });
  let err = "";
  p.stderr.on("data", (d) => (err += d));
  const line = await new Promise((resolve, reject) => {
    let buf = "";
    p.stdout.on("data", (d) => { buf += d; const m = buf.match(/READY (\S+) (.*)\n/); if (m) resolve({ url: m[1], ws: m[2] }); });
    p.on("exit", () => reject(new Error("engine exited: " + err)));
    setTimeout(() => reject(new Error("engine did not start: " + err)), 30000);
  });
  return { ...line, kill: () => p.kill() };
}

async function withPage(scenario, fn) {
  const eng = await engine(scenario);
  const exe = chromePath();
  const browser = await chromium.launch({ ...(exe ? { executablePath: exe } : {}), args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist", "--disable-dev-shm-usage"] });
  const page = await (await browser.newContext({ viewport: { width: 1280, height: 720 } })).newPage();
  const logs = [];
  page.on("console", (m) => logs.push(`${m.type()}: ${m.text()}`));
  page.on("pageerror", (e) => logs.push(`pageerror: ${e.message}`));
  try { await page.goto(eng.url); await fn(page, eng, logs); } finally { await browser.close(); eng.kill(); }
}

async function test(name, fn) {
  const t0 = Date.now();
  try { await fn(); results.push([name, true, Date.now() - t0]); console.log(`  ok   ${name}`); }
  catch (e) { results.push([name, false, Date.now() - t0]); console.log(`  FAIL ${name}\n       ${String(e.message).split("\n").join("\n       ")}`); }
}

const text = (page, sel) => page.locator(sel).first().innerText();
// the title is scrambled for a moment when it changes: wait for it to settle on the real word
const title = async (page, re) => { await page.waitForFunction((s) => new RegExp(s, "i").test(document.querySelector("#stateText")?.textContent ?? ""), re.source, { timeout: 15000 }); };

await test("the key URL becomes a cookie, the interface loads, and live frames arrive", async () => {
  await withPage("goal", async (page, eng, logs) => {
    await page.waitForSelector("#stateText", { timeout: 60000 });
    await page.waitForFunction(() => window.__praxis && window.__praxis.frame.mode === "idle", null, { timeout: 60000 });
    assert.ok(!page.url().includes("?k="), "the key must not stay in the address");
    await title(page, /READY|STANDING BY/);
    assert.match(await text(page, "#minds"), /SCRIPTED/i);
    const bad = logs.filter((l) => /pageerror/.test(l));
    assert.deepEqual(bad, []);
    await page.screenshot({ path: path.join(out, "e2e-idle.png") });
  });
});

await test("typing a goal runs it for real: steps, checks, VERIFIED, and a log of what happened", async () => {
  await withPage("goal", async (page) => {
    await page.waitForFunction(() => window.__praxis?.frame.info.can_type === true, null, { timeout: 60000 });
    await page.locator("#typed").fill("make a.txt");
    await page.locator("#typed").press("Enter");
    await page.waitForFunction(() => window.__praxis.frame.mode === "ok", null, { timeout: 60000 });
    await page.waitForTimeout(800);
    await title(page, /VERIFIED/);
    const mission = await text(page, "#mission");
    assert.match(mission, /a\.txt/); assert.match(mission, /file_exists a\.txt/);
        assert.match(await text(page, "#stream"), /PASS: file_exists a\.txt/);
    await page.screenshot({ path: path.join(out, "e2e-verified.png") });
  });
});

await test("an approval appears as AUTHORISATION REQUIRED with the exact action; Escape denies; the goal ends safely", async () => {
  await withPage("approval", async (page) => {
    await page.waitForFunction(() => window.__praxis?.frame.info.can_type === true, null, { timeout: 60000 });
    await page.locator("#typed").fill("I would like to read a page on the web please");
    await page.locator("#typed").press("Enter");
    await page.waitForSelector("#auth.on", { timeout: 60000 });
    assert.match(await text(page, "#auth"), /AUTHORISATION REQUIRED/i);
    assert.match(await text(page, "#authDetail"), /never-heard\.example/);
    assert.match(await text(page, "#authWhat"), /Open https:\/\/never-heard\.example/);
    assert.equal(await page.locator("#authYes").isDisabled(), true, "approve must not be clickable the instant it appears");
    assert.equal(await page.evaluate(() => document.activeElement?.id), "authNo", "Deny holds the focus");
    await page.screenshot({ path: path.join(out, "e2e-approval.png") });
    await page.keyboard.press("Escape");
    await page.waitForFunction(() => document.querySelector("#auth")?.classList.contains("on") === false, null, { timeout: 10000 });
    await page.waitForFunction(() => ["bad", "stopped", "idle"].includes(window.__praxis.frame.mode) && window.__praxis.frame.approvals.length === 0, null, { timeout: 30000 });
    const sent = await page.evaluate(() => window.__praxis.sent);
    assert.ok(sent.some((c) => c.cmd === "approve" && c.ok === false), JSON.stringify(sent));
  });
});

await test("approving is possible, but only after a moment to read; clicking Approve runs the action", async () => {
  await withPage("approval", async (page, eng) => {
    await page.waitForFunction(() => window.__praxis?.frame.info.can_type === true, null, { timeout: 60000 });
    await page.locator("#typed").fill("I would like to read a page on the web please");
    await page.locator("#typed").press("Enter");
    await page.waitForSelector("#auth.on", { timeout: 60000 });
    await page.waitForFunction(() => !document.querySelector("#authYes").disabled, null, { timeout: 10000 });
    await page.locator("#authYes").click();
    const sent = await page.evaluate(() => window.__praxis.sent);
    assert.ok(sent.some((c) => c.cmd === "approve" && c.ok === true));
    await page.waitForFunction(() => window.__praxis.frame.approvals.length === 0, null, { timeout: 30000 });
  });
});

await test("keys and clicks send the right commands (F2 data, F3 routing, folder dialog)", async () => {
  await withPage("goal", async (page) => {
    await page.waitForFunction(() => window.__praxis?.frame.mode === "idle", null, { timeout: 60000 });
    await page.keyboard.press("F2");
    await page.waitForFunction(() => window.__praxis.frame.settings.data_class === "private", null, { timeout: 10000 });
    await page.keyboard.press("F3");
    await page.waitForFunction(() => window.__praxis.frame.settings.strategy === "frugal", null, { timeout: 10000 });
    await page.keyboard.press("Control+o");
    await page.waitForSelector("#ws.on");
    await page.keyboard.press("Escape");
    assert.equal(await page.locator("#ws.on").count(), 0);
    assert.match(await text(page, "#telemetry"), /FRUGAL/i);
  });
});

await test("closing the engine shows the link-lost banner instead of a frozen screen", async () => {
  const eng = await engine("goal");
  const exe = chromePath();
  const browser = await chromium.launch({ ...(exe ? { executablePath: exe } : {}), args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
  try {
    const page = await (await browser.newContext({ viewport: { width: 1280, height: 720 } })).newPage();
    await page.goto(eng.url);
    await page.waitForFunction(() => window.__praxis?.frame.mode === "idle", null, { timeout: 60000 });
    eng.kill();
    await page.waitForFunction(() => [...document.querySelectorAll(".chip")].some((c) => c.textContent.includes("LINK LOST") && c.style.display !== "none"), null, { timeout: 30000 });
  } finally { await browser.close(); eng.kill(); }
});

const failed = results.filter((r) => !r[1]);
console.log(`\n${results.length - failed.length}/${results.length} end-to-end checks passed`);
process.exit(failed.length ? 1 : 0);
