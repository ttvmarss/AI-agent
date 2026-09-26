"""providers/npm.py — packages from the public npm registry.

Search:  registry.npmjs.org/-/v1/search
Inspect: registry.npmjs.org/<name> (license, versions, readme, repository),
         then the linked GitHub README via raw.githubusercontent.com when the
         registry copy is missing.
"""

from __future__ import annotations

import re
from typing import Iterator
from urllib.parse import quote

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

REGISTRY = "https://registry.npmjs.org"
_GH_RE = re.compile(r"github\.com[/:]([\w.-]+)/([\w.-]+?)(?:\.git)?(?:[#/].*)?$")


class NpmProvider(SearchProviderAdapter):
    name = "npm"
    label = "npm registry"
    source_type = "package"

    def search(self, query: str, limit: int) -> Iterator[Hit]:
        data = http_get(f"{REGISTRY}/-/v1/search", params={"text": query, "size": max(1, min(limit, 50))}, as_json=True)
        for obj in (data or {}).get("objects", [])[:limit]:
            pkg = obj.get("package") or {}
            links = pkg.get("links") or {}
            name = pkg.get("name") or ""
            yield Hit(
                title=name,
                url=links.get("npm") or f"https://www.npmjs.com/package/{name}",
                source_type="package",
                snippet=(pkg.get("description") or "")[:280],
                meta={
                    "version": pkg.get("version"),
                    "license": pkg.get("license"),
                    "keywords": (pkg.get("keywords") or [])[:8],
                    "publisher": (pkg.get("publisher") or {}).get("username"),
                    "published": (pkg.get("date") or "")[:10] or None,
                    "days_since_update": days_since(obj.get("updated") or pkg.get("date") or ""),
                    "weekly_downloads": (obj.get("downloads") or {}).get("weekly"),
                    "dependents": obj.get("dependents"),
                    "repository_url": links.get("repository"),
                    "homepage": links.get("homepage"),
                    "language": "JavaScript/TypeScript",
                },
                raw=obj,
            )

    def inspect(self, src: ResearchSource, ctx: InspectContext) -> None:
        name = src.title
        m = src.meta
        changed = []
        for label, val in (
            ("Version", m.get("version")),
            ("License", m.get("license")),
            ("Weekly downloads", m.get("weekly_downloads")),
            ("Published", m.get("published")),
        ):
            if src.add_fact(label, val, "npm search API"):
                changed.append(label)
        ctx.update(changed)
        ctx.checkpoint()

        ctx.step(f"Opening package manifest — {name}")
        try:
            doc = http_get(f"{REGISTRY}/{quote(name, safe='@')}", as_json=True)
        except ProviderError as e:
            src.error = f"registry manifest unavailable ({e})"
            raise
        latest = (doc.get("dist-tags") or {}).get("latest")
        ver = (doc.get("versions") or {}).get(latest) or {}
        times = doc.get("time") or {}
        src.raw_metadata["manifest_latest"] = {k: ver.get(k) for k in ("name", "version", "license", "engines", "dependencies", "peerDependencies", "bin", "dist")}
        changed = []
        if ver.get("license") or doc.get("license"):
            lic = ver.get("license") or doc.get("license")
            if isinstance(lic, dict):
                lic = lic.get("type")
            m["license"] = lic
            src.add_fact("License", lic, "npm manifest")
            changed.append("License")
        m["release_count"] = len(doc.get("versions") or {})
        src.add_fact("Releases", m["release_count"], "npm manifest")
        m["first_release"] = (times.get("created") or "")[:10] or None
        modified = times.get("modified") or ""
        if times.get(latest):
            m["release_date"] = times[latest][:10]
            src.add_fact("Latest release", f"{latest} ({times[latest][:10]})", "npm manifest")
            m["days_since_update"] = days_since(times[latest])
        elif modified:
            m["days_since_update"] = days_since(modified)
        deps = ver.get("dependencies") or {}
        m["dependency_count"] = len(deps)
        src.add_fact("Dependencies", len(deps), "npm manifest")
        dist = ver.get("dist") or {}
        if dist.get("unpackedSize"):
            m["unpacked_kb"] = round(dist["unpackedSize"] / 1024)
            src.add_fact("Unpacked size", f"{m['unpacked_kb']:,} KB", "npm manifest")
        if (ver.get("engines") or {}).get("node"):
            m["node_engine"] = ver["engines"]["node"]
            src.add_fact("Node engine", m["node_engine"], "npm manifest")
        if ver.get("deprecated"):
            m["deprecated"] = ver["deprecated"]
            src.add_fact("Deprecated", ver["deprecated"], "npm manifest")
        repo = doc.get("repository") or {}
        repo_url = repo.get("url") if isinstance(repo, dict) else str(repo)
        gh = _GH_RE.search(repo_url or "")
        if gh:
            m["github_repo"] = f"{gh.group(1)}/{gh.group(2)}"
            src.add_fact("Source repo", m["github_repo"], "npm manifest")
        changed += ["Releases", "Latest release", "Dependencies", "Unpacked size", "Node engine", "Source repo"]
        ctx.update(changed)
        ctx.checkpoint()

        readme = doc.get("readme") or ""
        origin = "README (npm registry copy)"
        if len(readme) < 200 and m.get("github_repo"):
            ctx.step(f"Reading README — {m['github_repo']}")
            for branch in ("HEAD", "main", "master"):
                try:
                    readme = http_get(f"https://raw.githubusercontent.com/{m['github_repo']}/{branch}/README.md")
                    origin = f"README (github.com/{m['github_repo']})"
                    break
                except ProviderError:
                    continue
        else:
            ctx.step(f"Reading README — {name}")
        if readme:
            src.preview = readme[:12000]
            m["readme_chars"] = len(readme)
            summary = first_paragraph(readme)
            changed = []
            if summary:
                src.add_fact("README summary", summary, origin)
                changed.append("README summary")
            changed += extract_text_facts(src, readme, origin)
            ctx.update(changed)
        else:
            src.add_fact("README", "not found", "npm manifest")
            ctx.update(["README"])
