"""providers/web.py — general web search (DuckDuckGo HTML endpoint) and
page inspection (title, meta description, headings, body text).

Also hosts DocumentationProvider: the same engine restricted to official
documentation domains via `site:` filters.
"""

from __future__ import annotations

from typing import Iterator, List
from urllib.parse import parse_qs, unquote, urlsplit

from ..models import ResearchSource
from .base import Hit, InspectContext, SearchProviderAdapter, extract_text_facts, http_get

DDG_HTML = "https://html.duckduckgo.com/html/"


def _real_url(href: str) -> str:
    # DuckDuckGo wraps results as //duckduckgo.com/l/?uddg=<encoded>
    if "uddg=" in href:
        q = parse_qs(urlsplit(href).query)
        if q.get("uddg"):
            return unquote(q["uddg"][0])
    if href.startswith("//"):
        return "https:" + href
    return href


def _favicon(url: str) -> str:
    host = urlsplit(url).netloc
    return f"https://{host}/favicon.ico" if host else ""


class WebSearchProvider(SearchProviderAdapter):
    name = "web"
    label = "Web"
    source_type = "webpage"
    site_filter = ""

    def search(self, query: str, limit: int) -> Iterator[Hit]:
        from bs4 import BeautifulSoup

        q = f"{query} {self.site_filter}".strip()
        html = http_get(DDG_HTML, params={"q": q}, headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(html, "html.parser")
        n = 0
        for res in soup.select(".result"):
            a = res.select_one("a.result__a")
            if not a or not a.get("href"):
                continue
            url = _real_url(a["href"])
            if "duckduckgo.com/y.js" in url:  # sponsored
                continue
            snip = res.select_one(".result__snippet")
            yield Hit(
                title=a.get_text(" ", strip=True)[:160],
                url=url,
                source_type=self.source_type,
                snippet=(snip.get_text(" ", strip=True) if snip else "")[:280],
                favicon=_favicon(url),
                meta={"domain": urlsplit(url).netloc.removeprefix("www.")},
            )
            n += 1
            if n >= limit:
                break

    def inspect(self, src: ResearchSource, ctx: InspectContext) -> None:
        from bs4 import BeautifulSoup

        ctx.step(f"Opening page — {src.meta.get('domain') or src.url}")
        html = http_get(src.url, headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(html, "html.parser")
        for t in soup(["script", "style", "noscript", "svg", "nav", "footer"]):
            t.decompose()
        changed: List[str] = []
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        if title:
            src.add_fact("Page title", title[:160], "page <title>")
            changed.append("Page title")
        desc = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
        if desc and desc.get("content"):
            src.add_fact("Description", desc["content"][:300], "page meta description")
            changed.append("Description")
        img = soup.find("meta", attrs={"property": "og:image"})
        if img and img.get("content"):
            src.image = img["content"]
        heads = [h.get_text(" ", strip=True) for h in soup.find_all(["h1", "h2"])][:6]
        if heads:
            src.add_fact("Sections", " · ".join(h[:60] for h in heads), "page headings")
            changed.append("Sections")
        ctx.update(changed)
        ctx.checkpoint()

        ctx.step(f"Reading content — {src.meta.get('domain') or src.url}")
        text = soup.get_text("\n", strip=True)
        src.preview = text[:12000]
        src.meta["readme_chars"] = len(text)
        ctx.update(extract_text_facts(src, text, "page body"))


class DocumentationProvider(WebSearchProvider):
    name = "docs"
    label = "Official docs"
    source_type = "documentation"
    site_filter = "(site:docs.* OR site:readthedocs.io OR site:learn.microsoft.com OR site:developer.mozilla.org)"
