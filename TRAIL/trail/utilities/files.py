import hashlib
import json
import os
import tempfile


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def sha256_text(s):
    return hashlib.sha256(s.encode("utf-8", "replace")).hexdigest()


def write_json_atomic(path, obj):
    """Write-then-rename so an interrupted run never leaves a half-written state file."""
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, sort_keys=True)
    os.replace(tmp, path)


def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
