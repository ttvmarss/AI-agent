"""providers/github.py — GitHub repositories via the public REST API.

Set GITHUB_TOKEN in .env for 5000 req/h instead of the anonymous 60/h
(and 30 vs 10 searches/min). Nothing here is cached or invented: if the API
denies us, the query fails visibly with the real HTTP status.
"""

from __future__ import annotations

import base64
import os
from typing import Iterator, List, Tuple

from ..models import ResearchSource
from .base import (
    Hit,
    InspectContext,
    ProviderError,
    SearchProviderAdapter,
    days_since,
    extract_text_facts,
    first_paragraph,
    generic_verify,
    http_get,
)

API = "https://api.github.com"


def _headers() -> dict:
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    tok = os.environ.get("GITHUB_TOKEN", "").strip()
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


class GitHubProvider(SearchProviderAdapter):
    name = "github"
    label = "GitHub"
    source_type = "repository"

    def search(self, query: str, limit: int) -> Iterator[Hit]:
        data = http_get(
            f"{API}/search/repositories",
            params={"q": query, "sort": "stars", "order": "desc", "per_page": max(1, min(limit, 30))},
            headers=_headers(),
            as_json=True,
        )
        for item in (data or {}).get("items", [])[:limit]:
            lic = (item.get("license") or {}).get("spdx_id")
            owner = item.get("owner") or {}
            yield Hit(
                title=item.get("full_name") or item.get("name") or "",
                url=item.get("html_url") or "",
                source_type="repository",
                snippet=(item.get("description") or "")[:280],
                favicon=owner.get("avatar_url", ""),
                meta={
                    "owner": owner.get("login"),
                    "repo": item.get("name"),
                    "stars": item.get("stargazers_count"),
                    "forks": item.get("forks_count"),
                    "language": item.get("language"),
                    "license": lic if lic and lic != "NOASSERTION" else None,
                    "pushed_at": item.get("pushed_at"),
                    "days_since_update": days_since(item.get("pushed_at") or ""),
                    "archived": bool(item.get("archived")),
                    "topics": (item.get("topics") or [])[:8],
                    "size_kb": item.get("size"),
                    "open_issues": item.get("open_issues_count"),
                    "default_branch": item.get("default_branch"),
                },
                raw=item,
            )

    def inspect(self, src: ResearchSource, ctx: InspectContext) -> None:
        full = src.title
        m = src.meta

        # License / activity come straight from the search payload — surface
        # them as facts first (they are real, already retrieved).
        changed: List[str] = []
        for label, val in (
            ("Stars", m.get("stars")),
            ("Forks", m.get("forks")),
            ("Language", m.get("language")),
            ("License", m.get("license") or None),
            ("Last push", (m.get("pushed_at") or "")[:10] or None),
        ):
            if src.add_fact(label, val, "GitHub API /search"):
                changed.append(label)
        ctx.update(changed)
        ctx.checkpoint()

        ctx.step(f"Reading README — {full}")
        try:
            readme = http_get(f"{API}/repos/{full}/readme", headers=_headers(), as_json=True)
            content = base64.b64decode(readme.get("content", "")).decode("utf-8", "replace")
            src.preview = content[:12000]
            summary = first_paragraph(content)
            if summary:
                src.add_fact("README summary", summary, "README")
            changed = ["README summary"] + extract_text_facts(src, content, "README")
            src.meta["readme_chars"] = len(content)
            ctx.update(changed)
        except ProviderError as e:
            src.add_fact("README", f"unavailable ({e})", "GitHub API /readme")
            ctx.update(["README"])
        ctx.checkpoint()

        ctx.step(f"Inspecting releases — {full}")
        try:
            rel = http_get(f"{API}/repos/{full}/releases/latest", headers=_headers(), as_json=True)
            tag = rel.get("tag_name")
            published = (rel.get("published_at") or "")[:10]
            src.meta["latest_release"] = tag
            src.meta["release_date"] = published
            src.add_fact("Latest release", f"{tag} ({published})" if published else tag, "GitHub API /releases/latest")
            ctx.update(["Latest release"])
        except ProviderError as e:
            if "404" in str(e):
                src.add_fact("Latest release", "none published", "GitHub API /releases/latest")
                ctx.update(["Latest release"])
            else:
                src.add_fact("Latest release", f"unavailable ({e})", "GitHub API /releases/latest")
                ctx.update(["Latest release"])

    def verify(self, src: ResearchSource) -> Tuple[bool, List[str]]:
        return generic_verify(src)
