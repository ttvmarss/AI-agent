"""Verifiers: typed, executable checks. CLAIMS REQUIRE EVIDENCE."""
import os
from dataclasses import dataclass


@dataclass
class Result:
    passed: bool
    detail: str


def verify(spec, ws):
    """spec: {"type": ..., ...}. Unknown verifier types FAIL (never silently pass)."""
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
        if t == "command_ok":  # e.g. run the project's tests; executed through the same runtime
            r = ws.shell_run(spec["cmd"], spec.get("timeout", 120))
            return Result(r["returncode"] == 0, f"command_ok {spec['cmd']} rc={r['returncode']}")
        if t == "none":
            return Result(True, "no verifier required (read-only step)")
    except Exception as e:
        return Result(False, f"{t} errored: {type(e).__name__}: {e}")
    return Result(False, f"unknown verifier type {t!r}")
