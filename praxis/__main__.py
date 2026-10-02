"""CLI: python -m praxis {run,resume,status,why,verify-log,rollback,doctor,bench,models}"""
import argparse
import os
import sys
import time

from . import launch, secrets
from .config import build_stack, load_config
from .free_tiers import DISCONTINUED, PRESETS, preset
from .events import EventLog
from .executive import Executive
from .hardware import detect_hardware, profile_from_config
from .registry import detect_memory_bytes
from .report import hardware_report, model_table, ollama_tips, recommendation_report


def _safe_streams():
    """A Windows console may be cp1252: never crash on a model's unicode, print a replacement instead."""
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass


def _paths(ws):
    ws = os.path.abspath(ws)
    os.makedirs(os.path.join(ws, ".praxis"), exist_ok=True)
    return ws, os.path.join(ws, ".praxis", "events.db")


def _approver(decision):
    if not sys.stdin.isatty():
        return False  # non-interactive: fail closed
    args = decision.args
    shown = args.get("task") if decision.tool == "agent.delegate" else args
    print(f"\n[approval needed] Class {decision.cls}: {decision.tool}"
          f"{' -> ' + str(args.get('agent')) if decision.tool == 'agent.delegate' else ''}\n  {shown}\n  why: {decision.reason}")
    return input("approve? [y/N] ").strip().lower() == "y"


def _executive(ws, log, stack, a):
    lim = stack.cfg["limits"]
    return Executive(ws, log, stack.router, approver=_approver, agents=stack.agents,
                     critic=not getattr(a, "no_critic", False) and len(stack.providers) > 1,
                     max_steps=lim["max_steps"], max_model_calls=lim["max_model_calls"],
                     max_cost_usd=lim["max_cost_usd"] or None, max_checkpoint_mb=lim.get("max_checkpoint_mb", 512),
                     escalate=stack.cfg["routing"].get("escalate", True), max_escalations=stack.cfg["routing"].get("max_escalations", 2),
                     data_class=("private" if getattr(a, "private", False) else getattr(a, "data_class", None)
                                 or stack.cfg["privacy"]["data_class"]),
                     sandbox=stack.sandbox)


def _print_report(rep):
    print(f"{rep.status}  goal={rep.goal_id}  checkpoint={rep.checkpoint}")
    if rep.reason:
        print(f"reason: {rep.reason}")
    for e in rep.evidence:
        print(f"  [{'PASS' if e['passed'] else 'FAIL'}] {e['claim']}")


def cmd_doctor(stack, ws, ping, ping_all=False):
    print(f"machine : {stack.profile.describe()}")
    sb = stack.sandbox
    print(f"sandbox : {sb.kind.upper()} " + ("(self-attack passed: no outside writes, no network, state hidden)" if sb.strong else
          "- NONE: running code (tests, scripts) will need your approval every time.\n"
          "          Linux: install bubblewrap. Windows/macOS: install Docker Desktop (or use WSL2).") + "\n")
    tips = ollama_tips(stack.profile)
    ok = 0
    fams = {}
    for p in stack.providers:
        fams.setdefault(p.card.name.split("/")[0], []).append(p)
    for name in ("claude", "codex", "droid", "ollama", "devin"):
        inst = fams.get(name)
        if not inst:
            print(f"  {name:<8} SKIPPED  {stack.skipped.get(name, '')}")
            continue
        first = inst[0]
        try:
            line = f"  {name:<8} READY    {first.version()}"
            if name == "ollama":
                line += f"  selected={first.resolve_model()}"
            print(line)
            where = getattr(stack, "tools_found", {}).get(name)
            if where:
                print(f"           at {where}")
            if name == "devin" and not getattr(first, "can_complete", True):
                print("           delegate-only (Class 4, spends ACUs); not pinged so no session is started")
                continue
            sample = next((x for x in inst if getattr(x, "tier", None) == "balanced"), inst[0])
            fam_ok = not (ping or ping_all)  # without --ping, "READY" means installed and answering --version
            for p in inst:
                label = p.card.name if "/" in p.card.name else f"{name}/(default model)"
                tier = f"[{p.tier}]" if getattr(p, "tier", None) else ""
                if ping_all or (ping and p is sample):
                    t0 = time.time()
                    try:
                        out = p.complete("planner", [{"role": "user", "content": "Reply with exactly: PONG"}])
                        res = f"ping {'ok' if 'PONG' in out.upper() else 'UNEXPECTED ' + repr(out[:30])} {time.time() - t0:.1f}s"
                        c = (getattr(p, "last_meta", None) or {}).get("cost_usd")
                        res += f"  ${c:.4f}" if c else ""
                        fam_ok = fam_ok or 'PONG' in out.upper()
                    except Exception as e:
                        res = f"UNAVAILABLE: {str(e)[:90]}"
                else:
                    res = "not pinged"
                print(f"           - {label:<34}{tier:<12}{res}")
            ok += 1 if fam_ok else 0
        except Exception as e:
            print(f"  {name:<8} BROKEN   {e}")
    print(f"\n{ok} usable provider group(s)." + ("" if ok else "  Install/login at least one of: claude, codex, droid, ollama."))
    if tips:
        print("\n" + tips)
    return 0 if ok else 1


def _limits(pr):
    bits = []
    if pr.rpm:
        bits.append(f"{pr.rpm}/min")
    if pr.rpd:
        bits.append(f"{pr.rpd:,}/day")
    if pr.tpd:
        bits.append(f"{pr.tpd // 1_000_000}M tok/day" if pr.tpd >= 1_000_000 else f"{pr.tpd // 1000}K tok/day")
    return ", ".join(bits) or "limits unpublished"


def cmd_keys(a):
    import getpass
    ids = [p.id for p in PRESETS]
    if a.action == "list":
        for n in secrets.names():
            print(f"  {n:<14}{secrets.mask(secrets.get(n) or '')}")
        if not secrets.names():
            print("  (no stored keys; environment variables also work, see `praxis free`)")
        return 0
    if a.name not in ids:
        print(f"choose one of: {', '.join(ids)}"); return 2
    if a.action == "remove":
        secrets.remove(a.name); print(f"removed {a.name}"); return 0
    value = getpass.getpass(f"{a.name} API key (input hidden): ").strip()
    if len(value) < 8:
        print("that does not look like a key"); return 2
    secrets.set(a.name, value)
    print(f"saved {a.name} ({secrets.mask(value)}) to your private key file; it is never logged or sent anywhere but {a.name}")
    return 0


def cmd_free(a, ws):
    cfg = load_config(ws)
    if a.action == "list":
        print("FREE CLOUD TIERS  (read 2026-10-02; a 429 from the provider always wins over these numbers)\n")
        print(f"  {'id':<14}{'status':<12}{'data':<8}{'limits':<34}models")
        for pr in PRESETS:
            on = cfg["providers"].get(pr.id, {}).get("enabled", True)
            has = bool(secrets.get(pr.id, pr.key_env))
            status = "disabled" if not on else "READY" if has else "no key"
            cls = "trusted" if pr.privacy == "cloud" else "OPEN"
            models = ", ".join(cfg["providers"].get(pr.id, {}).get("models") or pr.models) or "(choose: praxis free models " + pr.id + ")"
            print(f"  {pr.id:<14}{status:<12}{cls:<8}{_limits(pr):<34}{models}")
        print("\n  data: 'trusted' = documents no training on API data (used for project goals).")
        print("        'OPEN'    = free-tier terms may train/log/human-review your prompts: only for goals you mark")
        print("                    --data-class open, and never when a credential is detected in the prompt.\n")
        print("  Get a free key, then:  praxis keys set <id>   (or set the environment variable)")
        for pr in PRESETS:
            print(f"    {pr.id:<14}{pr.signup_url}   env {pr.key_env}")
        print("\nDiscontinued free paths (not integrated):")
        for d in DISCONTINUED:
            print(f"  - {d.name}: ended {d.ended}. {d.note}")
        return 0
    if not a.target or a.target not in [p.id for p in PRESETS]:
        print("name a provider: " + ", ".join(p.id for p in PRESETS)); return 2
    pr = preset(a.target)
    key = secrets.get(pr.id, pr.key_env)
    if not key:
        print(f"no key for {pr.id}: praxis keys set {pr.id}"); return 1
    from .openai_compat import OpenAICompatProvider
    from .providers import OllamaProvider
    try:
        if pr.kind == "ollama-cloud":
            prov = OllamaProvider(pr.base_url, "gpt-oss:120b", api_key=key, label=pr.id, privacy="cloud", tier="free")
        else:
            prov = OpenAICompatProvider(pr.id, (pr.models or ("x",))[0], pr.base_url, api_key=key, key_env=pr.key_env,
                                        privacy=pr.privacy, tier="free", rpm=pr.rpm)
        if a.action == "models":
            ids = prov.models() if pr.kind == "ollama-cloud" else prov.discover(free_only=(pr.id == "openrouter"))
            ids = [m["name"] if isinstance(m, dict) else m for m in ids]
            print("\n".join(ids) or "(none)"); return 0
        out = prov.complete("planner", [{"role": "user", "content": "Reply with exactly: PONG"}])
        print(f"{pr.id}: {'ok' if 'PONG' in out.upper() else 'unexpected reply: ' + out[:40]}")
        return 0
    except Exception as e:
        print(f"{pr.id}: {str(e)[:200]}"); return 1


def main(argv=None):
    _safe_streams()
    raw = list(sys.argv[1:] if argv is None else argv)
    if raw and raw[0] == "hud":                              # the design file tools need no workspace, models or Qt
        hp = argparse.ArgumentParser(prog="praxis hud")
        hp.add_argument("action", choices=["validate", "export", "path", "docs"])
        hp.add_argument("target", nargs="?")
        ha = hp.parse_args(raw[1:])
        from . import hudcli
        return hudcli.run(ha.action, ha.target)
    if launch.is_launch_request(raw):                       # `praxis` / `praxis app [folder]`: open the window and hand the terminal back
        return 0 if launch.start(raw[1:]) is not None else 1
    ap = argparse.ArgumentParser(prog="praxis")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, *args):
        sp = sub.add_parser(name)
        for x in args:
            sp.add_argument(*x[0], **x[1])
        sp.add_argument("--workspace", default=".")
        return sp
    r = add("run", (["goal"], {}), (["--private"], {"action": "store_true", "help": "local models only"}),
            (["--data-class"], {"choices": ["private", "project", "open"],
                                "help": "private=local only; project=+trusted cloud (default); open=+free tiers that may train"}),
            (["--no-critic"], {"action": "store_true"}))
    add("free", (["action"], {"nargs": "?", "choices": ["list", "models", "test"], "default": "list"}),
        (["target"], {"nargs": "?"}))
    add("keys", (["action"], {"choices": ["set", "list", "remove"]}), (["name"], {"nargs": "?"}))
    add("resume", (["goal_id"], {"nargs": "?"}))
    add("status")
    add("why", (["event_id"], {"type": int}))
    add("verify-log")
    add("rollback", (["checkpoint"], {}))
    add("undo")
    add("doctor", (["--ping"], {"action": "store_true", "help": "send a tiny real prompt to one model per provider"}),
        (["--ping-all"], {"action": "store_true", "help": "ping every configured model (costs a little usage)"}))
    add("models", (["--recommend"], {"action": "store_true", "help": "what to install for this hardware"}))
    add("hardware")
    add("voice")
    add("pull", (["tag"], {}), (["--yes"], {"action": "store_true", "help": "do not ask for confirmation"}))
    add("bench", (["--trials"], {"type": int, "default": 1}), (["--providers"], {"default": ""}),
        (["--all-ollama"], {"action": "store_true", "help": "benchmark every installed Ollama model that fits"}),
        (["--no-critique"], {"action": "store_true"}),
        (["--max-cost"], {"type": float, "default": 3.0, "help": "stop starting new providers once this many USD were spent"}),
        (["--holdout"], {"action": "store_true", "help": "run the held-out task set (never used for tuning)"}))
    a = ap.parse_args(argv)
    ws, db = _paths(a.workspace)
    log = EventLog(db)

    if a.cmd == "verify-log":
        ok, bad = log.verify_chain()
        print("log intact" if ok else f"LOG TAMPERED at event {bad}")
        return 0 if ok else 2
    if a.cmd == "keys":
        return cmd_keys(a)
    if a.cmd == "free":
        return cmd_free(a, ws)
    stack = build_stack(ws)
    if a.cmd == "doctor":
        return cmd_doctor(stack, ws, a.ping, a.ping_all)
    if a.cmd == "voice":
        from .desktop.voice_check import run as voice_check
        return voice_check(stack, stack.cfg.get("voice", {}))
    if a.cmd == "hardware":
        prof = profile_from_config(stack.cfg["hardware"], detect_hardware())
        print(hardware_report(prof)); print()
        tips = ollama_tips(prof)
        if tips:
            print(tips); print()
        print(recommendation_report(prof))
        return 0
    if a.cmd == "pull":
        from .providers import OllamaProvider
        o = OllamaProvider(stack.cfg["providers"]["ollama"].get("host"), timeout=7200)
        try:
            o.version()
        except Exception as e:
            print(f"Ollama is not running: {e}"); return 1
        if not a.yes:
            if not sys.stdin.isatty():
                print(f"refusing to download {a.tag} without --yes (models are multiple GB)"); return 2
            if input(f"Download {a.tag} with Ollama? [y/N] ").strip().lower() != "y":
                return 2
        last = [""]
        def show(ev):
            if ev.get("total") and ev.get("completed") is not None:
                pct = f"{ev['status']}: {100 * ev['completed'] // ev['total']}%"
            else:
                pct = ev.get("status", "")
            if pct != last[0]:
                print(pct); last[0] = pct
        ok = o.pull(a.tag, show)
        print("success" if ok else "pull did not report success")
        return 0 if ok else 1
    if a.cmd == "models" and a.recommend:
        print(recommendation_report(profile_from_config(stack.cfg["hardware"], detect_hardware()))); return 0
    if a.cmd == "models":
        o = next((p for p in stack.providers if p.card.name.startswith("ollama")), None)
        if not o:
            print("ollama not available:", stack.skipped.get("ollama")); return 1
        mem = detect_memory_bytes()
        for m in o.models():
            fit = "fits" if m.get("size", 0) <= mem else "too large"
            sc = stack.registry.score(f"ollama/{m['name']}", "planning")
            print(f"  {m['name']:<32}{m.get('size', 0) / 2**30:>7.1f} GiB  {fit:<10}"
                  f"{'measured ' + format(sc, '.2f') if sc is not None else 'unmeasured'}")
        print(f"\nselected: {o.resolve_model()}")
        return 0
    if a.cmd == "bench":
        from .bench import bench_all
        provs = [p for p in stack.providers if getattr(p, "can_complete", True)]
        if a.providers:
            want = set(a.providers.split(","))  # a family ("claude") or an exact instance ("claude/claude-opus-5-5")
            provs = [p for p in provs if p.card.name.split("/")[0] in want or p.card.name in want]
        if a.all_ollama:
            from .providers import OllamaProvider
            from .registry import parse_params
            base = next((p for p in provs if isinstance(p, OllamaProvider)), None)
            if base:
                provs.remove(base)
                mem = detect_memory_bytes()
                for m in sorted(base.models(), key=lambda m: -parse_params(m.get("details"), m["name"])):
                    if "embed" not in m["name"].lower() and m.get("size", 0) <= mem:
                        provs.append(OllamaProvider(base.host, m["name"], base.num_ctx))
                        provs[-1].card.name = f"ollama/{m['name']}"
        if not provs:
            print("no providers to benchmark (run `praxis doctor`)"); return 1
        print(f"benchmarking {[p.card.name for p in provs]}  trials={a.trials}\n")
        s = bench_all(provs, stack.registry, a.trials, not a.no_critique, sandbox=stack.sandbox, holdout=a.holdout, max_cost=a.max_cost)
        print(f"\n{'provider':<30}{'pass':>6}{'false-done':>12}{'attacks':>9}{'critique':>10}{'latency':>9}{'cost$':>8}")
        for n, v in s.items():
            print(f"{n:<30}{v['pass_rate']:>6.2f}{v['false_done']:>12}{v['attacks']:>9}"
                  f"{v.get('critique', float('nan')):>10.2f}{v['latency_s']:>8.1f}s{v['cost']:>8.3f}")
        print(f"\nscores saved to {stack.registry.path}; the router uses them when strategy=auto and all candidates are measured.")
        return 0
    ex = _executive(ws, log, stack, a)
    if a.cmd == "why":
        print(ex.why(a.event_id)); return 0
    if a.cmd == "undo":
        ok, msg = ex.undo_last(); print(msg); return 0 if ok else 1
    if a.cmd == "rollback":
        ex.ws.rollback(a.checkpoint); print(f"restored checkpoint {a.checkpoint}"); return 0
    if a.cmd == "status":
        u = ex.unfinished_goals()
        print("providers:", [p.card.name for p in stack.providers] or "none", "| skipped:", stack.skipped)
        print("unfinished goals (resumable):", u or "none")
        return 0
    if a.cmd == "resume":
        rep = ex.resume(a.goal_id)
        if rep is None:
            print("nothing to resume"); return 0
        _print_report(rep); return 0 if rep.status == "VERIFIED" else 1
    u = ex.unfinished_goals()
    if u:
        print(f"note: {len(u)} unfinished goal(s) from a previous crash; run `praxis resume` to recover.\n")
    rep = ex.run(a.goal)
    _print_report(rep)
    return 0 if rep.status == "VERIFIED" else 1


if __name__ == "__main__":
    sys.exit(main())
