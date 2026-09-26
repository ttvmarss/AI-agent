"""dev/capture.py — drive a REAL research request through the UI and record it.

Starts dev/harness.py, opens Chromium, types the request into the app's own
chat input, and captures a video plus timed screenshots until the session
completes. Then exercises the controls (source viewer, pin, pause/resume,
stop) on a second request. Writes to dev/capture_out/.

    python dev/capture.py --jarvis-root ../jarvis --providers npm,pypi,github,web
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "capture_out")


def wait_http(url: str, timeout: float = 20) -> None:
    import requests

    end = time.time() + timeout
    while time.time() < end:
        try:
            if requests.get(url, timeout=1).ok:
                return
        except Exception:  # noqa: BLE001
            time.sleep(0.3)
    raise RuntimeError("harness did not start")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jarvis-root", default=os.environ.get("JARVIS_ROOT"))
    ap.add_argument("--providers", default="npm,pypi,github,web")
    ap.add_argument("--port", type=int, default=5077)
    ap.add_argument("--request", default="Research open-source AI coding agent tools that could improve our Copilot. "
                                          "Check licenses, capabilities, compatibility and whether they add anything useful.")
    ap.add_argument("--second", default="Compare open-source local LLM chat libraries for node and python")
    ap.add_argument("--width", type=int, default=1600)
    ap.add_argument("--height", type=int, default=900)
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    for f in os.listdir(OUT):
        os.remove(os.path.join(OUT, f))

    cmd = [sys.executable, os.path.join(HERE, "harness.py"), "--port", str(args.port), "--providers", args.providers]
    if args.jarvis_root:
        cmd += ["--jarvis-root", args.jarvis_root]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    url = f"http://127.0.0.1:{args.port}/"
    report = {"request": args.request, "shots": [], "events": {}}
    try:
        wait_http(url)
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            exe = "/opt/pw-browsers/chromium" if os.path.exists("/opt/pw-browsers/chromium") else None
            browser = p.chromium.launch(args=["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"],
                                        **({"executable_path": exe} if exe and os.path.isfile(exe) else {}))
            ctx = browser.new_context(viewport={"width": args.width, "height": args.height},
                                      record_video_dir=OUT, record_video_size={"width": args.width, "height": args.height})
            page = ctx.new_page()
            page.on("console", lambda m: m.type == "error" and print("[console]", m.text))
            page.add_init_script("""
              window.__rxLog = [];
              const hook = () => { const s = window.__jarvisSocket; if (!s) return setTimeout(hook, 50);
                s.on('research_event', e => window.__rxLog.push({seq: e.seq, type: e.type, t: performance.now()})); };
              hook();""")
            page.goto(url)
            page.wait_for_timeout(1800)
            page.screenshot(path=os.path.join(OUT, "00_idle.png"))

            # type into the app's own chat input (C opens the overlay)
            page.keyboard.press("c")
            page.wait_for_timeout(300)
            page.fill("#chat-input", args.request)
            page.keyboard.press("Enter")
            t0 = time.time()
            n = 1
            done = False
            while time.time() - t0 < 240:
                page.wait_for_timeout(900 if n < 14 else 1600)
                path = os.path.join(OUT, f"{n:02d}_t{int(time.time() - t0):03d}.png")
                page.screenshot(path=path)
                report["shots"].append(os.path.basename(path))
                n += 1
                if page.evaluate("() => !!(window.MentisResearch && window.MentisResearch.state.finished)"):
                    if done:
                        break
                    done = True  # one more frame after settle
            page.wait_for_timeout(1500)
            page.screenshot(path=os.path.join(OUT, f"{n:02d}_final.png"))

            # --- interact: open a kept source in the viewer, switch tabs
            sid = page.evaluate("""() => { for (const [k, c] of window.MentisResearch.state.cards) if (c.src.state === 'selected') return k; return null; }""")
            if sid:
                page.evaluate("id => document.querySelector(`.rx-a-row[data-sid='${id}']`)?.click()", sid)
                page.wait_for_timeout(900)
                page.screenshot(path=os.path.join(OUT, "viewer_facts.png"))
                page.click(".rx-v-tab[data-tab='preview']")
                page.wait_for_timeout(500)
                page.screenshot(path=os.path.join(OUT, "viewer_preview.png"))
                page.click(".rx-v-actions [data-act='closev']")

            log = page.evaluate("() => window.__rxLog")
            for e in log:
                report["events"][e["type"]] = report["events"].get(e["type"], 0) + 1
            report["event_count"] = len(log)
            report["artifacts"] = page.evaluate("() => window.MentisResearch.state.artifacts.map(a => ({id: a.art.id, type: a.art.type, sources: a.art.source_ids, derived_from: a.art.derived_from}))")

            # --- second request: pause / resume / stop. The backend is fast on
            # npm, so pause is sent over the socket the instant the real
            # session.started event arrives (the UI button path is exercised
            # for resume + stop below).
            page.evaluate("""() => { window.__rxPaused = false; window.__jarvisSocket.on('research_event', e => {
                if (e.type === 'research.session.started' && !window.__rxPaused) { window.__rxPaused = true;
                  window.__jarvisSocket.emit('research_control', {session_id: e.session_id, action: 'pause'}); } }); }""")
            page.fill("#chat-input", args.second)
            page.keyboard.press("Enter")
            page.wait_for_function("() => window.__rxLog.some(e => e.type === 'research.session.paused')", timeout=20000)
            page.wait_for_timeout(600)
            n_paused = page.evaluate("() => window.__rxLog.filter(e => e.type.startsWith('research.source') || e.type === 'research.result.discovered').length")
            page.wait_for_timeout(3000)
            page.screenshot(path=os.path.join(OUT, "control_paused.png"))
            n_after = page.evaluate("() => window.__rxLog.filter(e => e.type.startsWith('research.source') || e.type === 'research.result.discovered').length")
            report["pause_held"] = {"source_events_at_pause": n_paused, "source_events_3s_later": n_after}
            page.click("#rx-header [data-act='pause']")  # UI button: resume
            page.wait_for_function("() => window.__rxLog.some(e => e.type === 'research.session.resumed')", timeout=10000)
            page.wait_for_function("() => window.__rxLog.some(e => e.type === 'research.source.inspecting')", timeout=30000)
            page.click("#rx-header [data-act='stop']")  # UI button: stop
            page.wait_for_function("() => window.MentisResearch.state.finished", timeout=30000)
            page.wait_for_timeout(1500)
            page.screenshot(path=os.path.join(OUT, "control_stopped.png"))
            report["stopped_events"] = page.evaluate("() => window.__rxLog.filter(e => e.type === 'research.session.stopped').length")
            report["artifacts_after_stop"] = page.evaluate("() => window.MentisResearch.state.artifacts.length")

            ctx.close()
            browser.close()
    finally:
        proc.terminate()
        try:
            out = proc.communicate(timeout=5)[0]
            with open(os.path.join(OUT, "harness.log"), "w", encoding="utf-8") as f:
                f.write(out or "")
        except Exception:  # noqa: BLE001
            proc.kill()
    for f in os.listdir(OUT):
        if f.endswith(".webm"):
            os.replace(os.path.join(OUT, f), os.path.join(OUT, "research_run.webm"))
            break
    with open(os.path.join(OUT, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
    print(json.dumps({k: v for k, v in report.items() if k != "shots"}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
