"""Start Ollama if it is installed but not running, so local models (the fastest brains for chat, and free) are simply there.

Only a LOCAL server is ever started, only if the `ollama` program exists, and it is started with the settings its own FAQ recommends for
a small-VRAM GPU (flash attention, a compressed context cache, one resident model), which is exactly the tuning `praxis hardware` prints.
The server is detached: it keeps running after PRAXIS closes, like the tray app would."""
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

LOCAL = ("127.0.0.1", "localhost", "[::1]", "::1")


def is_local(host):
    h = host.split("://", 1)[-1].split("/", 1)[0].rsplit(":", 1)[0] if ":" in host.split("://", 1)[-1] else host.split("://", 1)[-1]
    return h in LOCAL


def up(host, timeout=1.5, opener=urllib.request.urlopen):
    try:
        with opener(host.rstrip("/") + "/api/version", timeout=timeout) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def tuning(vram_bytes):
    """The documented environment for a small-VRAM GPU (<= 8.5 GiB): the same advice `praxis hardware` prints."""
    if 0 < vram_bytes <= 8.5 * 2 ** 30:
        return {"OLLAMA_FLASH_ATTENTION": "1", "OLLAMA_KV_CACHE_TYPE": "q8_0", "OLLAMA_MAX_LOADED_MODELS": "1"}
    return {}


def ensure(host="http://127.0.0.1:11434", vram_bytes=0, wait_s=6.0, which=shutil.which, popen=subprocess.Popen, probe=up, sleep=time.sleep,
          env=None):
    """-> (running, note). Never raises. Does nothing unless Ollama is local, installed and not already up."""
    if os.environ.get("PRAXIS_NO_AUTOSTART"):
        return probe(host), "autostart disabled"
    if probe(host):
        return True, ""
    if not is_local(host):
        return False, "ollama is not reachable (and it is not a local server, so PRAXIS will not start it)"
    exe = which("ollama")
    if not exe:
        return False, "ollama is not installed"
    e = dict(env if env is not None else os.environ)
    for k, v in tuning(vram_bytes).items():
        e.setdefault(k, v)
    kw = {"creationflags": 0x00000008 | 0x08000000} if sys.platform.startswith("win") else {"start_new_session": True}   # DETACHED_PROCESS | CREATE_NO_WINDOW
    try:
        popen([exe, "serve"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=e, **kw)
    except Exception as ex:
        return False, f"could not start ollama: {type(ex).__name__}: {ex}"
    end = time.time() + wait_s
    while time.time() < end:
        if probe(host):
            return True, "started ollama for you"
        sleep(0.3)
    return False, "started ollama but it did not answer in time"
