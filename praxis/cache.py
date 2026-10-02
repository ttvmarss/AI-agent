"""A tiny on-disk cache for things that are slow to find out and almost never change (the CPU's marketing name from PowerShell,
the GPU list from nvidia-smi, whether a given `devin` binary is the CLI): each took 0.5 to 3 seconds on every launch on Windows.
Entries carry a stamp: when the stamp differs (a new binary, a new driver) the value is recomputed. Failures never matter: no cache, no problem."""
import json
import os
import tempfile
import time

from .paths import home


def _path():
    return os.path.join(home(), "cache.json")


def _load():
    try:
        with open(_path(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(d):
    try:
        os.makedirs(home(), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=home(), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(d, f)
        os.replace(tmp, _path())                      # atomic: a crash never leaves half a file
    except OSError:
        pass


def get(name, compute, ttl_s=7 * 86400, stamp="", now=time.time):
    """The cached value for `name` if it is fresh and has the same stamp; otherwise compute() it and remember it (None is never cached)."""
    if os.environ.get("PRAXIS_NO_CACHE"):
        return compute()
    d = _load()
    e = d.get(name)
    if isinstance(e, dict) and e.get("stamp") == stamp and now() - float(e.get("ts", 0)) < ttl_s and "v" in e:
        return e["v"]
    v = compute()
    if v is not None:
        d[name] = {"v": v, "ts": now(), "stamp": stamp}
        _save(d)
    return v
