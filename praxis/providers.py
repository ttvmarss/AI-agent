"""Real adapters. Subscription-backed CLIs (claude, codex, droid), local Ollama, and Devin's v3 API.

`complete()`  : read-only text completion for planner/critic roles (CLIs run in an empty temp dir
                with write tools disabled, so a planning call cannot touch the project).
`delegate()`  : agentic work inside the workspace (always Class >= 3 in the Guard, always rolled
                back on failed verification, always diff-logged).
"""
import json
import os
import re
import tempfile
import time
import urllib.error
import urllib.request

from .proc import classify, flatten, run_cli
from .registry import detect_memory_bytes, pick_for_hardware, pick_ollama_model
from .router import CapabilityCard, ModelUnavailable, Provider, ProviderError, RateLimited

_API_KEYS = {
    "claude": ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"),   # force subscription login, never API billing
    "codex": ("CODEX_API_KEY", "OPENAI_API_KEY"),
}


class _CLIProvider(Provider):
    binary = ""
    can_complete = True
    can_delegate = True

    def __init__(self, model=None, timeout=300, strip_keys=True, tier=None):
        self.model = model or None
        self.tier = tier
        self.timeout = timeout
        self.strip = _API_KEYS.get(self.binary, ()) if strip_keys else ()
        self.card = CapabilityCard(f"{self.binary}/{self.model}" if self.model else self.binary, "cloud")
        self.last_meta = {}

    def _run(self, argv, stdin, cwd):
        t0 = time.time()
        out, _ = run_cli(argv, stdin, self.strip, self.timeout, cwd)
        self.last_meta = {"duration_ms": int((time.time() - t0) * 1000)}
        return out

    def version(self):
        out, _ = run_cli([self.binary, "--version"], "", (), 20)
        return out.strip().splitlines()[0] if out.strip() else "?"


class ClaudeCLI(_CLIProvider):
    """Uses the user's Claude subscription through the official `claude` CLI (headless `-p`)."""
    binary = "claude"

    def _base(self):
        a = ["claude", "-p", "--output-format", "json", "--no-session-persistence", "--setting-sources", ""]
        return a + (["--model", self.model] if self.model else [])

    def _parse(self, out):
        if "unrecognized_model" in out:
            raise ModelUnavailable(f"claude: model {self.model!r} is not available on this account")
        try:
            d = json.loads(out)
        except json.JSONDecodeError:
            raise ProviderError("claude: non-JSON output")
        if d.get("is_error"):
            msg = str(d.get("result", ""))[:300]
            cls = classify(msg)
            raise (RateLimited if cls is ProviderError and re.search(r"limit|quota|credit", msg, re.I) else cls)(f"claude: {msg}")
        self.last_meta.update({"cost_usd": d.get("total_cost_usd"), "stop": d.get("stop_reason")})
        return d.get("result", "")

    def complete(self, role, messages):
        system, convo = flatten(messages)
        with tempfile.TemporaryDirectory() as empty:
            argv = self._base() + ["--tools", ""]
            if system:  # via file: argv has length/newline limits on Windows (.cmd shims) that a file does not
                sp = os.path.join(empty, "planner.sysprompt")
                with open(sp, "w", encoding="utf-8") as f:
                    f.write(system)
                argv += ["--system-prompt-file", sp]
            return self._parse(self._run(argv, convo, empty))

    def delegate(self, task, cwd):
        argv = self._base() + ["--permission-mode", "acceptEdits", "--tools", "Read,Edit,Write,Glob,Grep"]
        return self._parse(self._run(argv, task, cwd))


class CodexCLI(_CLIProvider):
    """Uses the user's ChatGPT subscription through `codex exec` (saved CLI login)."""
    binary = "codex"

    def _exec(self, prompt, sandbox, cwd):
        with tempfile.NamedTemporaryFile("r", suffix=".txt", delete=False) as tf:
            outp = tf.name
        try:
            argv = ["codex", "exec", "--sandbox", sandbox, "--skip-git-repo-check", "--ephemeral",
                    "-o", outp] + (["-m", self.model] if self.model else []) + ["-"]
            self._run(argv, prompt, cwd)
            with open(outp) as f:
                text = f.read().strip()
        finally:
            if os.path.exists(outp):
                os.unlink(outp)
        if not text:
            raise ProviderError("codex: empty final message")
        return text

    def complete(self, role, messages):
        system, convo = flatten(messages)
        with tempfile.TemporaryDirectory() as empty:
            return self._exec(f"{system}\n\n{convo}".strip(), "read-only", empty)

    def delegate(self, task, cwd):
        return self._exec(task, "workspace-write", cwd)


class DroidCLI(_CLIProvider):
    """Factory's `droid exec`. Default autonomy is read-only; delegate uses `--auto low` (file edits only).
    Auth: FACTORY_API_KEY (passed through; it *is* the Factory credential)."""
    binary = "droid"

    def _parse(self, out):
        out = out.strip()
        try:
            d = json.loads(out)
        except json.JSONDecodeError:
            return out  # plain text
        if isinstance(d, dict):
            if d.get("is_error") or d.get("error"):
                raise ProviderError(f"droid: {str(d.get('error') or d.get('result'))[:300]}")
            for k in ("result", "response", "output", "text", "message", "content"):
                if k in d:
                    v = d[k]
                    return v if isinstance(v, str) else json.dumps(v)
        return out

    def _argv(self, auto=None):
        a = ["droid", "exec", "-o", "json"] + (["-m", self.model] if self.model else [])
        return a + (["--auto", auto] if auto else [])

    def complete(self, role, messages):
        system, convo = flatten(messages)
        with tempfile.TemporaryDirectory() as empty:
            return self._parse(self._run(self._argv() + ["--cwd", empty], f"{system}\n\n{convo}".strip(), empty))

    def delegate(self, task, cwd):
        return self._parse(self._run(self._argv("low") + ["--cwd", cwd], task, cwd))


class OllamaProvider(Provider):
    """Local models over Ollama's REST API. Private data may use this provider."""
    can_complete = True
    can_delegate = False

    def __init__(self, host="http://127.0.0.1:11434", model="auto", num_ctx=16384, timeout=900,
                 memory_bytes=None, registry=None, prefer=(), profile=None, min_tps=6.0):
        self.profile, self.min_tps = profile, min_tps
        self.tier = "local"
        self.host = host.rstrip("/")
        self.configured = model
        self.num_ctx, self.timeout = num_ctx, timeout
        self.memory_bytes = memory_bytes
        self.registry, self.prefer = registry, tuple(prefer)
        self.model = None if model in (None, "", "auto") else model
        self.card = CapabilityCard("ollama", "local")
        self.last_meta = {}

    def _http(self, path, body=None, timeout=None):
        req = urllib.request.Request(self.host + path, data=None if body is None else json.dumps(body).encode(),
                                     headers={"content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
                return json.load(r)
        except urllib.error.URLError as e:
            raise ProviderError(f"ollama unreachable at {self.host}: {e.reason if hasattr(e, 'reason') else e}")
        except Exception as e:
            raise ProviderError(f"ollama: {type(e).__name__}: {e}")

    def version(self):
        return self._http("/api/version", timeout=10).get("version", "?")

    def models(self):
        return self._http("/api/tags", timeout=15).get("models", [])

    def resolve_model(self):
        if self.model:
            return self.model
        if self.profile is not None:  # hardware-aware: VRAM + RAM split, MoE-aware speed estimate, measured wins
            pick = pick_for_hardware(self.models(), self.profile, self.registry, self.prefer, self.min_tps)
        else:
            mem = self.memory_bytes if self.memory_bytes is not None else detect_memory_bytes()
            pick = pick_ollama_model(self.models(), mem, self.registry, self.prefer)
        if not pick:
            raise ProviderError("ollama: no installed model fits this machine (run `ollama pull <model>`)")
        self.model = pick
        self.card.name = f"ollama/{pick}"
        return pick

    def complete(self, role, messages):
        model = self.resolve_model()
        body = {"model": model, "messages": messages, "stream": False, "keep_alive": "10m",
                "options": {"temperature": 0, "num_ctx": self.num_ctx}}
        if role in ("planner", "replanner", "critic"):
            body["format"] = "json"  # constrain to valid JSON (documented API feature)
        d = self._http("/api/chat", body)
        text = (d.get("message") or {}).get("content", "")
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()  # thinking models
        if not text:
            raise ProviderError("ollama: empty response")
        self.last_meta = {"duration_ms": int(d.get("total_duration", 0) / 1e6), "eval_count": d.get("eval_count")}
        if d.get("eval_count") and d.get("eval_duration"):  # MEASURED decode speed, not an estimate
            self.last_meta["tokens_per_s"] = round(d["eval_count"] / (d["eval_duration"] / 1e9), 2)
        return text

    def pull(self, tag, on_progress=None):
        """Download a model (streams Ollama's NDJSON progress). Returns True on success."""
        req = urllib.request.Request(self.host + "/api/pull", data=json.dumps({"model": tag, "stream": True}).encode(),
                                     headers={"content-type": "application/json"})
        ok = False
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                for line in r:
                    line = line.strip()
                    if not line:
                        continue
                    ev = json.loads(line)
                    if ev.get("error"):
                        raise ProviderError(f"ollama pull {tag}: {ev['error']}")
                    if on_progress:
                        on_progress(ev)
                    ok = ok or ev.get("status") == "success"
        except ProviderError:
            raise
        except Exception as e:
            raise ProviderError(f"ollama pull {tag}: {type(e).__name__}: {e}")
        return ok


class DevinProvider(Provider):
    """Devin (Cognition) v3 API: asynchronous remote agent sessions. Delegate-only.

    Devin works in its own cloud environment on the repos it is connected to, so it cannot edit the
    local workspace; its output is a session URL / structured output / PR for a human to review.
    Sessions consume ACUs (money), so the Guard classes this Class 4: explicit approval every time.
    """
    can_complete = False
    can_delegate = True
    TERMINAL = {"exit", "error", "suspended"}
    WAITING = {"waiting_for_user", "waiting_for_approval", "usage_limit_exceeded", "out_of_credits",
               "out_of_quota", "no_quota_allocation", "payment_declined", "org_usage_limit_exceeded",
               "total_session_limit_exceeded"}

    def __init__(self, org_id=None, api_key=None, base="https://api.devin.ai/v3", poll_s=15, timeout_s=3600):
        self.org = org_id or os.environ.get("DEVIN_ORG_ID")
        self.key = api_key or os.environ.get("DEVIN_API_KEY")
        self.base, self.poll_s, self.timeout_s = base.rstrip("/"), poll_s, timeout_s
        self.card = CapabilityCard("devin", "cloud")
        self.last_meta = {}

    def _call(self, method, path, body=None):
        if not (self.org and self.key):
            raise ProviderError("devin: set DEVIN_API_KEY and DEVIN_ORG_ID")
        req = urllib.request.Request(f"{self.base}/organizations/{self.org}{path}", method=method,
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers={"Authorization": f"Bearer {self.key}", "content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            raise (RateLimited if e.code in (402, 429) else ProviderError)(f"devin HTTP {e.code}: {e.read()[:200]!r}")
        except Exception as e:
            raise ProviderError(f"devin: {type(e).__name__}: {e}")

    def complete(self, role, messages):
        raise ProviderError("devin is delegate-only")

    def delegate(self, task, cwd=None):
        s = self._call("POST", "/sessions", {"prompt": task})
        sid, deadline = s["session_id"], time.time() + self.timeout_s
        while True:
            s = self._call("GET", f"/sessions/{sid}")
            status, detail = s.get("status"), s.get("status_detail")
            if status in self.TERMINAL or detail in self.WAITING:
                break
            if time.time() > deadline:
                detail = "poll_timeout"
                break
            time.sleep(self.poll_s)
        self.last_meta = {"session_id": sid, "status": status, "status_detail": detail}
        return json.dumps({"session_id": sid, "url": s.get("url"), "status": status,
                           "status_detail": detail, "structured_output": s.get("structured_output")})
