"""providers/pypi.py — Python packages via the PyPI JSON API.

PyPI has no public search API (its HTML search sits behind a bot check), so
this provider does honest EXACT-NAME lookups: each candidate name taken from
the query is looked up at pypi.org/pypi/<name>/json. A 404 means no such
package — nothing is shown for it.
"""

from __future__ import annotations

import re
from typing import Iterator

from ..models import ResearchSource
from .base import (
    Hit,
    InspectContext,
    ProviderError,
    SearchProviderAdapter,
    days_since,
    extract_text_facts,
    first_paragraph,
    http_get,
)

_GH_RE = re.compile(r"github\.com/([\w.-]+)/([\w.-]+)")


class PyPIProvider(SearchProviderAdapter):
    name = "pypi"
    label = "PyPI"
    source_type = "package"

    def search(self, query: str, limit: int) -> Iterator[Hit]:
        names = [t for t in re.findall(r"[a-z0-9][a-z0-9._-]{1,40}", query.lower())][: max(limit, 1) * 2]
        found = 0
        for name in names:
            try:
                data = http_get(f"https://pypi.org/pypi/{name}/json", as_json=True)
            except ProviderError as e:
                if "404" in str(e):
                    continue
                raise
            info = data.get("info") or {}
            urls = info.get("project_urls") or {}
            releases = data.get("releases") or {}
            latest_files = releases.get(info.get("version") or "", [])
            upload = latest_files[0].get("upload_time_iso_8601") if latest_files else ""
            yield Hit(
                title=info.get("name") or name,
                url=info.get("package_url") or f"https://pypi.org/project/{name}/",
                source_type="package",
                snippet=(info.get("summary") or "")[:280],
                meta={
                    "version": info.get("version"),
                    "license": (info.get("license_expression") or info.get("license") or "")[:40] or None,
                    "requires_python": info.get("requires_python"),
                    "release_count": len(releases),
                    "release_date": (upload or "")[:10] or None,
                    "days_since_update": days_since(upload or ""),
                    "homepage": info.get("home_page") or urls.get("Homepage"),
                    "language": "Python",
                    "_description": info.get("description") or "",
                    "_urls": urls,
                },
                raw={k: info.get(k) for k in ("name", "version", "summary", "license", "requires_python", "project_urls")},
            )
            found += 1
            if found >= limit:
                return

    def inspect(self, src: ResearchSource, ctx: InspectContext) -> None:
        m = src.meta
        desc = m.pop("_description", "")
        urls = m.pop("_urls", {}) or {}
        changed = []
        for label, val, origin in (
            ("Version", m.get("version"), "PyPI JSON"),
            ("License", m.get("license"), "PyPI JSON"),
            ("Requires Python", m.get("requires_python"), "PyPI JSON"),
            ("Releases", m.get("release_count"), "PyPI JSON"),
            ("Latest release", m.get("release_date"), "PyPI JSON"),
        ):
            if src.add_fact(label, val, origin):
                changed.append(label)
        for v in urls.values():
            gh = _GH_RE.search(v or "")
            if gh:
                m["github_repo"] = f"{gh.group(1)}/{gh.group(2)}"
                src.add_fact("Source repo", m["github_repo"], "PyPI project_urls")
                changed.append("Source repo")
                break
        ctx.update(changed)
        ctx.checkpoint()

        ctx.step(f"Reading project description — {src.title}")
        if desc:
            src.preview = desc[:12000]
            m["readme_chars"] = len(desc)
            summary = first_paragraph(desc)
            changed = []
            if summary:
                src.add_fact("README summary", summary, "PyPI long description")
                changed.append("README summary")
            changed += extract_text_facts(src, desc, "PyPI long description")
            ctx.update(changed)
