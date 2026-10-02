// Shared helpers for the end-to-end and screenshot scripts: start a Vite server, launch a Chromium with software WebGL, open a page.
import { chromium } from "playwright";
import { createServer } from "vite";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const here = path.dirname(fileURLToPath(import.meta.url));
export const root = path.resolve(here, "..");
export const out = path.join(here, "out");

export function chromePath() {
  const cands = [process.env.CHROME_PATH, "/opt/pw-browsers/chromium", "/usr/bin/chromium", "/usr/bin/google-chrome", "C:/Program Files/Google/Chrome/Application/chrome.exe",
    "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"].filter(Boolean);
  return cands.find((p) => fs.existsSync(p));
}

export async function start({ port = 5188, viewport = { width: 1600, height: 900 } } = {}) {
  fs.mkdirSync(out, { recursive: true });
  const server = await createServer({ root, server: { port, strictPort: false }, logLevel: "error" });
  await server.listen();
  const url = `http://localhost:${server.config.server.port}`;
  const exe = chromePath();
  const browser = await chromium.launch({ ...(exe ? { executablePath: exe } : {}),
    args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist", "--disable-dev-shm-usage"] });
  const page = await browser.newPage({ viewport });
  const logs = [];
  page.on("console", (m) => logs.push(`${m.type()}: ${m.text()}`));
  page.on("pageerror", (e) => logs.push(`pageerror: ${e.message}`));
  return { server, browser, page, url, logs, async close() { await browser.close(); await server.close(); } };
}
