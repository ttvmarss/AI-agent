"""providers/local.py — the user's own project files.

Searches a local directory (RESEARCH_LOCAL_ROOT, default: the working
directory) for files that mention the query terms. Real file reads only;
binary, vendored and huge files are skipped.
"""

from __future__ import annotations

import os
import re
from typing import Iterator, List, Optional

from ..models import ResearchSource
from .base import Hit, InspectContext, SearchProviderAdapter, extract_text_facts

TEXT_EXT = {".py", ".js", ".ts", ".tsx", ".jsx", ".md", ".txt", ".json", ".toml", ".yaml", ".yml", ".css", ".html", ".bat", ".ps1", ".cfg", ".ini"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "vendor", "dist", "build", ".mypy_cache", ".pytest_cache"}
MAX_FILE_BYTES = 400_000


class LocalProjectProvider(SearchProviderAdapter):
    name = "local"
    label = "Project files"
    source_type = "file"

    def __init__(self, root: Optional[str] = None) -> None:
        self.root = os.path.abspath(root or os.environ.get("RESEARCH_LOCAL_ROOT") or os.getcwd())

    def _files(self) -> Iterator[str]:
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
            for fn in filenames:
                if os.path.splitext(fn)[1].lower() in TEXT_EXT:
                    path = os.path.join(dirpath, fn)
                    try:
                        if os.path.getsize(path) <= MAX_FILE_BYTES:
                            yield path
                    except OSError:
                        continue

    def search(self, query: str, limit: int) -> Iterator[Hit]:
        terms = [t for t in re.findall(r"[a-z0-9_]{3,}", query.lower())]
        if not terms:
            return
        scored = []
        for path in self._files():
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read().lower()
            except OSError:
                continue
            hits = {t: text.count(t) for t in terms}
            matched = [t for t, c in hits.items() if c]
            if len(matched) >= max(1, len(terms) // 2):
                scored.append((len(matched), sum(hits.values()), path, matched))
        scored.sort(reverse=True)
        for n_terms, total, path, matched in scored[:limit]:
            rel = os.path.relpath(path, self.root)
            yield Hit(
                title=rel.replace(os.sep, "/"),
                url="file:///" + path.replace(os.sep, "/").lstrip("/"),
                source_type="file",
                snippet=f"Mentions {', '.join(matched[:6])} ({total} occurrences)",
                meta={"path": path, "matched_terms": matched, "occurrences": total,
                      "language": os.path.splitext(path)[1].lstrip(".").upper() or None},
            )

    def inspect(self, src: ResearchSource, ctx: InspectContext) -> None:
        path = src.meta.get("path", "")
        ctx.step(f"Reading file — {src.title}")
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
        src.preview = text[:12000]
        src.meta["readme_chars"] = len(text)
        lines = text.splitlines()
        src.add_fact("Lines", len(lines), "file on disk")
        terms = src.meta.get("matched_terms") or []
        excerpts: List[str] = []
        for i, line in enumerate(lines):
            low = line.lower()
            if any(t in low for t in terms):
                excerpts.append(f"L{i + 1}: {line.strip()[:120]}")
            if len(excerpts) >= 3:
                break
        if excerpts:
            src.add_fact("Matches", " · ".join(excerpts), "file on disk")
        ctx.update(["Lines", "Matches"] + extract_text_facts(src, text, "file on disk"))

    def verify(self, src: ResearchSource):
        return True, [f"Local file · {src.meta.get('occurrences', 0)} term occurrences"]
