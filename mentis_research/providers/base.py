"""providers/base.py — the SearchProviderAdapter contract + shared helpers.

A provider does three real things:
  search(query, limit)  -> yields normalised hits, one at a time, as they
                           are parsed from a REAL response
  inspect(src, ctx)     -> enriches the ResearchSource in place, step by
                           step, calling ctx.step(...) around each real fetch
  verify(src)           -> checks the facts it just gathered (license present,
                           maintained, docs exist...) and returns reasons

Providers never touch the UI or the event bus directly; the orchestrator
turns their progress into events. That keeps them testable and keeps every
event tied to a real action.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple
from urllib.parse import urlsplit

import requests

from ..models import ResearchSource

HTTP_TIMEOUT_S = float(os.environ.get("RESEARCH_HTTP_TIMEOUT_S", "10"))
USER_AGENT = "MENTIS-Research/1.0 (+local assistant; research workspace)"


class ProviderError(Exception):
    """A real failure talking to a source (HTTP error, denied, timeout)."""


def http_get(url: str, *, params: Optional[dict] = None, headers: Optional[dict] = None,
             timeout: float = HTTP_TIMEOUT_S, as_json: bool = False) -> Any:
    h = {"User-Agent": USER_AGENT}
    if headers:
        h.update(headers)
    host = urlsplit(url).netloc
    try:
        resp = requests.get(url, params=params, headers=h, timeout=timeout)
    except requests.exceptions.ProxyError as e:
        raise ProviderError(f"{host} blocked by network policy") from e
    except requests.exceptions.Timeout as e:
        raise ProviderError(f"{host} timed out after {timeout:g}s") from e
    except requests.exceptions.ConnectionError as e:
        raise ProviderError(f"cannot reach {host}") from e
    except requests.RequestException as e:
        raise ProviderError(f"{type(e).__name__}: {str(e)[:100]}") from e
    if resp.status_code >= 400:
        detail = ""
        try:
            detail = str((resp.json() or {}).get("message", ""))
        except Exception:  # noqa: BLE001
            detail = ""
        if resp.status_code == 403 and "rate limit" in detail.lower():
            detail = "rate limited (set GITHUB_TOKEN)"
        raise ProviderError(f"HTTP {resp.status_code}{' — ' + detail[:70] if detail else ''}")
    return resp.json() if as_json else resp.text


@dataclass
class Hit:
    """One normalised search result exactly as the provider returned it."""

    title: str
    url: str
    source_type: str
    snippet: str = ""
    favicon: str = ""
    image: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class InspectContext:
    """Handed to provider.inspect(). `step` announces a real action that is
    about to happen (activity feed); `update` publishes the enriched source
    after that action finished; `checkpoint` honours pause/stop."""

    step: Callable[[str], None]
    update: Callable[[List[str]], None]
    checkpoint: Callable[[], None]


class SearchProviderAdapter:
    name = "base"
    label = "Base"
    source_type = "webpage"

    def available(self) -> Tuple[bool, str]:
        return True, ""

    def search(self, query: str, limit: int) -> Iterator[Hit]:  # pragma: no cover - interface
        raise NotImplementedError

    def inspect(self, src: ResearchSource, ctx: InspectContext) -> None:  # pragma: no cover
        raise NotImplementedError

    def verify(self, src: ResearchSource) -> Tuple[bool, List[str]]:
        return generic_verify(src)


# ---------------------------------------------------------------------------
# Shared extraction helpers — all regex over REAL fetched text. If nothing
# matches, nothing is recorded (the card shows UNKNOWN / omits the field).
# ---------------------------------------------------------------------------

_HW_PATTERNS = [
    re.compile(r"[^.\n]*\b\d+(?:\.\d+)?\s?(?:GB|GiB)\s+(?:of\s+)?(?:V?RAM|VRAM|GPU memory|memory|system memory)\b[^.\n]*", re.I),
    re.compile(r"[^.\n]*\b(?:requires?|minimum|recommended)\b[^.\n]*\b(?:GPU|CUDA|VRAM|RAM|CPU|Apple Silicon|Metal)\b[^.\n]*", re.I),
    re.compile(r"[^.\n]*\b(?:runs?|works?)\s+(?:on|with)\s+(?:CPU|consumer GPUs?|Apple Silicon|a laptop|Windows|Linux|macOS)[^.\n]*", re.I),
]
_PLATFORM_RE = re.compile(r"\b(Windows|macOS|Linux|Docker|WSL)\b")
_GB_RE = re.compile(r"(\d+(?:\.\d+)?)\s?(?:GB|GiB)\s+(?:of\s+)?(V?RAM|GPU memory|memory|system memory)", re.I)


def clean_markdown(text: str) -> str:
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"[#>*_`|]+", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def extract_text_facts(src: ResearchSource, text: str, origin: str) -> List[str]:
    """Pull hardware / platform / size facts out of real fetched text.
    Returns the labels that changed (for the metadata_updated event)."""
    changed: List[str] = []
    if not text:
        return changed
    body = clean_markdown(text)[:60000]

    hw_lines: List[str] = []
    for pat in _HW_PATTERNS:
        for m in pat.finditer(body):
            line = " ".join(m.group(0).split())[:180]
            if 12 < len(line) and line not in hw_lines:
                hw_lines.append(line)
            if len(hw_lines) >= 3:
                break
    if hw_lines:
        src.add_fact("Hardware notes", " · ".join(hw_lines), origin)
        changed.append("Hardware notes")

    gbs = []
    for m in _GB_RE.finditer(body):
        try:
            gbs.append((float(m.group(1)), m.group(2).upper()))
        except ValueError:
            pass
    if gbs:
        vram = [g for g, k in gbs if "V" in k or "GPU" in k]
        ram = [g for g, k in gbs if not ("V" in k or "GPU" in k)]
        if vram:
            src.meta["min_vram_gb"] = min(vram)
            src.add_fact("Min VRAM mentioned", f"{min(vram):g} GB", origin)
            changed.append("Min VRAM mentioned")
        if ram:
            src.meta["min_ram_gb"] = min(ram)
            src.add_fact("Min RAM mentioned", f"{min(ram):g} GB", origin)
            changed.append("Min RAM mentioned")

    platforms = sorted(set(_PLATFORM_RE.findall(body)))
    if platforms:
        src.meta["platforms"] = platforms
        src.add_fact("Platforms mentioned", ", ".join(platforms), origin)
        changed.append("Platforms mentioned")

    return changed


def first_paragraph(text: str, limit: int = 320) -> str:
    for para in clean_markdown(text).split("\n\n"):
        p = " ".join(para.split())
        if len(p) > 60 and not p.lower().startswith(("table of contents", "contents")):
            return p[:limit] + ("…" if len(p) > limit else "")
    return ""


def days_since(iso: str) -> Optional[int]:
    if not iso:
        return None
    try:
        from datetime import datetime, timezone

        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return max(0, int((datetime.now(timezone.utc) - dt).total_seconds() // 86400))
    except Exception:  # noqa: BLE001
        return None


PERMISSIVE = {"MIT", "APACHE-2.0", "BSD-2-CLAUSE", "BSD-3-CLAUSE", "ISC", "MPL-2.0", "UNLICENSE", "0BSD", "ZLIB", "CC0-1.0"}
COPYLEFT = {"GPL-2.0", "GPL-3.0", "AGPL-3.0", "LGPL-2.1", "LGPL-3.0", "GPL-2.0-ONLY", "GPL-3.0-ONLY", "AGPL-3.0-ONLY",
            "GPL-3.0-OR-LATER", "LGPL-3.0-OR-LATER", "AGPL-3.0-OR-LATER"}


def license_class(spdx: Optional[str]) -> str:
    if not spdx:
        return "unknown"
    s = str(spdx).upper()
    if s in ("NOASSERTION", "OTHER", "UNKNOWN", "SEE LICENSE IN LICENSE"):
        return "unknown"
    if s in PERMISSIVE:
        return "permissive"
    if s in COPYLEFT or "GPL" in s:
        return "copyleft"
    return "other"


def generic_verify(src: ResearchSource) -> Tuple[bool, List[str]]:
    """Checks the facts actually gathered. Hard failures reject; soft ones
    are recorded as reasons but don't reject on their own."""
    reasons: List[str] = []
    ok = True
    if src.meta.get("archived"):
        ok = False
        reasons.append("Repository is archived")
    if src.meta.get("deprecated"):
        ok = False
        reasons.append(f"Deprecated: {str(src.meta['deprecated'])[:80]}")
    lic = license_class(src.meta.get("license"))
    if lic == "unknown" and src.source_type in ("repository", "package"):
        reasons.append("License unknown — reuse not cleared")
    elif lic == "copyleft":
        reasons.append(f"Copyleft license ({src.meta.get('license')}) — integration constraints")
    elif lic == "permissive":
        reasons.append(f"Permissive license ({src.meta.get('license')})")
    age = src.meta.get("days_since_update")
    if isinstance(age, int):
        if age > 730:
            ok = False
            reasons.append(f"Stale — no update in {age} days")
        elif age > 365:
            reasons.append(f"Slow maintenance — last update {age} days ago")
        else:
            reasons.append(f"Maintained — updated {age} days ago")
    if src.source_type in ("repository", "package") and len(src.preview) < 200:
        reasons.append("Little or no documentation found")
    return ok, reasons


def throttle(seconds: float) -> None:
    """Politeness delay between requests to the SAME remote API (rate
    limits). This is network etiquette, not animation pacing."""
    if seconds > 0:
        time.sleep(seconds)
