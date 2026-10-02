"""API-key store. Environment variables win; otherwise a per-user JSON file readable only by you (0600 on POSIX; inside
your user profile on Windows). Keys are never written to the event log, the workspace, or error messages."""
import json
import os

from .paths import home


def _path():
    return os.path.join(home(), "secrets.json")


def _load():
    try:
        with open(_path(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(d):
    os.makedirs(home(), exist_ok=True)
    tmp = _path() + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # born private: never briefly world-readable
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(d, f)
    os.replace(tmp, _path())
    try:
        os.chmod(_path(), 0o600)
    except OSError:
        pass


def get(name, env=None):
    v = os.environ.get(env) if env else None
    return v or _load().get(name) or None


def set(name, value):
    d = _load()
    d[name] = value.strip()
    _save(d)


def remove(name):
    d = _load()
    if d.pop(name, None) is not None:
        _save(d)


def names():
    return sorted(_load())


def mask(value):
    return value[:4] + "..." + value[-4:] if value and len(value) >= 12 else "****"
