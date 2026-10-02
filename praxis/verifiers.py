"""Verifiers: typed, executable checks. CLAIMS REQUIRE EVIDENCE."""
import os
from dataclasses import dataclass


@dataclass
class Result:
    passed: bool
    detail: str
    output: str = ""  # raw tool output (UNTRUSTED data); fed to replanners, never to the reason string


def verify(spec, ws, command_gate=None, processes=None):
    """spec: {"type": ..., ...}. Unknown verifier types FAIL (never silently pass).

    `command_gate(cmd) -> (allowed, reason)` is the Guard: verifier commands are actions like any other."""
    t = spec.get("type")
    try:
        if t == "file_exists":
            return Result(os.path.isfile(ws.resolve(spec["path"])), f"file_exists {spec['path']}")
        if t == "file_absent":
            return Result(not os.path.lexists(ws.resolve(spec["path"])), f"file_absent {spec['path']}")
        if t == "file_contains":
            txt = ws.fs_read(spec["path"])
            ok = spec["text"] in txt
            return Result(ok, f"file_contains {spec['path']} {spec['text']!r}")
        if t == "file_not_contains":
            txt = ws.fs_read(spec["path"])
            return Result(spec["text"] not in txt, f"file_not_contains {spec['path']}")
        if t == "file_equals":  # exact content, tolerant only of trailing newlines
            return Result(ws.fs_read(spec["path"]).rstrip("\n") == spec["text"].rstrip("\n"),
                          f"file_equals {spec['path']}")
        if t == "command_ok":  # e.g. run the project's tests
            if command_gate is not None:
                allowed, why = command_gate(spec["cmd"])
                if not allowed:
                    return Result(False, f"command_ok {spec['cmd']!r} refused by guard: {why}")
            r = ws.shell_run(spec["cmd"], spec.get("timeout", 120))
            return Result(r["returncode"] == 0, f"command_ok {spec['cmd']} rc={r['returncode']}", r["output"][-1500:])
        if t == "command_output_contains":  # run a program and check what it PRINTS (no redirect needed); same guard as any command
            if command_gate is not None:
                allowed, why = command_gate(spec["cmd"])
                if not allowed:
                    return Result(False, f"command_output_contains {spec['cmd']!r} refused by guard: {why}")
            r = ws.shell_run(spec["cmd"], spec.get("timeout", 120))
            out = r["output"]
            want = spec["text"]
            ok = r["returncode"] == 0 and (want in out)
            return Result(ok, f"command_output_contains {spec['cmd']} {want!r} rc={r['returncode']}", out[-1500:])
        if t == "command_output_equals":
            if command_gate is not None:
                allowed, why = command_gate(spec["cmd"])
                if not allowed:
                    return Result(False, f"command_output_equals {spec['cmd']!r} refused by guard: {why}")
            r = ws.shell_run(spec["cmd"], spec.get("timeout", 120))
            ok = r["returncode"] == 0 and r["output"].strip() == str(spec["text"]).strip()
            return Result(ok, f"command_output_equals {spec['cmd']} rc={r['returncode']}", r["output"][-1500:])
        if t == "process_running":  # a program is really running now (polls up to `wait` seconds for it to appear)
            if processes is None:
                from .opener import Processes
                processes = Processes()
            names = spec["name"] if isinstance(spec["name"], (list, tuple)) else [spec["name"]]
            wait = min(30.0, float(spec.get("wait", 10)))
            end = processes.clock() + wait
            hit = next((n for n in names if processes.running(n)), None)
            while hit is None and processes.clock() < end:
                processes.sleep(0.5)
                hit = next((n for n in names if processes.running(n)), None)
            return Result(hit is not None, f"process_running {hit or ' / '.join(map(str, names))}" + ("" if hit else " (not found)"))
        if t == "none":
            return Result(True, "no verifier required (read-only step)")
    except Exception as e:
        return Result(False, f"{t} errored: {type(e).__name__}: {e}")
    return Result(False, f"unknown verifier type {t!r}")
