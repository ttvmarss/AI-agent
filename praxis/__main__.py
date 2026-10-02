"""CLI: python -m praxis {run,resume,status,why,verify-log,rollback,doctor,bench,models}"""
import argparse
import os
import sys
import time

from .config import build_stack
from .events import EventLog
from .executive import Executive
from .registry import detect_memory_bytes


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
                     max_cost_usd=lim["max_cost_usd"] or None,
                     data_class="private" if getattr(a, "private", False) else stack.cfg["privacy"]["data_class"],
                     sandbox=stack.sandbox)


def _print_report(rep):
    print(f"{rep.status}  goal={rep.goal_id}  checkpoint={rep.checkpoint}")
    if rep.reason:
        print(f"reason: {rep.reason}")
    for e in rep.evidence:
        print(f"  [{'PASS' if e['passed'] else 'FAIL'}] {e['claim']}")


def cmd_doctor(stack, ws, ping):
    mem = detect_memory_bytes()
    print(f"memory budget for local models: {mem / 2**30:.1f} GiB")
    sb = stack.sandbox
    print(f"code-execution sandbox: {sb.kind.upper()} " + ("(self-attack passed: no outside writes, no network)" if sb.strong else
          "- NONE: running code (tests, scripts) will need your approval every time.\n"
          "   Fix: install bubblewrap (apt/dnf install bwrap), or enable rootless user namespaces, or start Docker.") + "\n")
    ok = 0
    for name in ("claude", "codex", "droid", "ollama", "devin"):
        p = next((x for x in stack.providers if x.card.name.split("/")[0] == name), None)
        if p is None:
            print(f"  {name:<8} SKIPPED  {stack.skipped.get(name, '')}")
            continue
        try:
            ver = p.version()
            line = f"  {name:<8} READY    {ver}"
            if name == "ollama":
                line += f"  model={p.resolve_model()}"
            if ping and getattr(p, "can_complete", True):
                t0 = time.time()
                out = p.complete("planner", [{"role": "user", "content": "Reply with exactly: PONG"}])
                line += f"  ping={'ok' if 'PONG' in out.upper() else 'UNEXPECTED:' + out[:30]!r} {time.time() - t0:.1f}s"
            if hasattr(p, "can_complete") and p.can_complete:
                ok += 1
            print(line)
        except Exception as e:
            print(f"  {name:<8} BROKEN   {e}")
        # delegation-only providers are listed but cannot plan
    for name in ("devin",):
        if name in [x.card.name for x in stack.providers]:
            print(f"  devin    READY    delegate-only (Class 4, spends ACUs); not pinged to avoid starting a session")
    print(f"\n{ok} provider(s) can plan." + ("" if ok else "  Install/login at least one of: claude, codex, droid, ollama."))
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(prog="praxis")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, *args):
        sp = sub.add_parser(name)
        for x in args:
            sp.add_argument(*x[0], **x[1])
        sp.add_argument("--workspace", default=".")
        return sp
    r = add("run", (["goal"], {}), (["--private"], {"action": "store_true", "help": "local models only"}),
            (["--no-critic"], {"action": "store_true"}))
    add("resume", (["goal_id"], {"nargs": "?"}))
    add("status")
    add("why", (["event_id"], {"type": int}))
    add("verify-log")
    add("rollback", (["checkpoint"], {}))
    add("doctor", (["--ping"], {"action": "store_true", "help": "send a tiny real prompt to each provider"}))
    add("models")
    add("bench", (["--trials"], {"type": int, "default": 1}), (["--providers"], {"default": ""}),
        (["--all-ollama"], {"action": "store_true", "help": "benchmark every installed Ollama model that fits"}),
        (["--no-critique"], {"action": "store_true"}))
    a = ap.parse_args(argv)
    ws, db = _paths(a.workspace)
    log = EventLog(db)

    if a.cmd == "verify-log":
        ok, bad = log.verify_chain()
        print("log intact" if ok else f"LOG TAMPERED at event {bad}")
        return 0 if ok else 2
    stack = build_stack(ws)
    if a.cmd == "doctor":
        return cmd_doctor(stack, ws, a.ping)
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
            want = set(a.providers.split(","))
            provs = [p for p in provs if p.card.name.split("/")[0] in want]
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
        s = bench_all(provs, stack.registry, a.trials, not a.no_critique, sandbox=stack.sandbox)
        print(f"\n{'provider':<30}{'pass':>6}{'false-done':>12}{'attacks':>9}{'critique':>10}{'latency':>9}{'cost$':>8}")
        for n, v in s.items():
            print(f"{n:<30}{v['pass_rate']:>6.2f}{v['false_done']:>12}{v['attacks']:>9}"
                  f"{v.get('critique', float('nan')):>10.2f}{v['latency_s']:>8.1f}s{v['cost']:>8.3f}")
        print(f"\nscores saved to {stack.registry.path}; the router uses them when strategy=auto and all candidates are measured.")
        return 0
    ex = _executive(ws, log, stack, a)
    if a.cmd == "why":
        print(ex.why(a.event_id)); return 0
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
