"""Provider adapters. Add a new source by subclassing SearchProviderAdapter
and registering it in build_providers()."""

from __future__ import annotations

import os
from typing import Dict, Iterable, Optional

from .base import Hit, InspectContext, ProviderError, SearchProviderAdapter
from .github import GitHubProvider
from .local import LocalProjectProvider
from .npm import NpmProvider
from .pypi import PyPIProvider
from .web import DocumentationProvider, WebSearchProvider

ALL = {
    "github": GitHubProvider,
    "web": WebSearchProvider,
    "docs": DocumentationProvider,
    "npm": NpmProvider,
    "pypi": PyPIProvider,
    "local": LocalProjectProvider,
}


def build_providers(names: Optional[Iterable[str]] = None) -> Dict[str, SearchProviderAdapter]:
    """RESEARCH_PROVIDERS=github,web,npm,pypi,local,docs (default: all)."""
    if names is None:
        env = os.environ.get("RESEARCH_PROVIDERS", "")
        names = [n.strip() for n in env.split(",") if n.strip()] or list(ALL)
    return {n: ALL[n]() for n in names if n in ALL}


__all__ = [
    "ALL",
    "Hit",
    "InspectContext",
    "ProviderError",
    "SearchProviderAdapter",
    "build_providers",
]
