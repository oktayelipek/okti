"""Web tools — web_fetch and web_search (optional)."""

from __future__ import annotations

import logging

import httpx

from okti.tools.registry import ToolDef, ToolRegistry

logger = logging.getLogger(__name__)

MAX_FETCH_CHARS = 100_000


async def web_fetch(url: str, format: str = "text") -> str:
    """Fetch a URL and return its content."""
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")

            if "json" in content_type:
                text = resp.text[:MAX_FETCH_CHARS]
            elif "html" in content_type:
                # Basic HTML stripping
                import re
                html = resp.text
                text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
                text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
                text = re.sub(r"<[^>]+>", " ", text)
                text = re.sub(r"\s+", " ", text).strip()
                text = text[:MAX_FETCH_CHARS]
            else:
                text = resp.text[:MAX_FETCH_CHARS]

            return f"URL: {url}\nStatus: {resp.status_code}\nContent-Type: {content_type}\n\n{text}"

    except httpx.HTTPStatusError as e:
        return f"Error fetching {url}: HTTP {e.response.status_code}"
    except Exception as e:
        return f"Error fetching {url}: {type(e).__name__}: {e}"


async def web_search(query: str, num_results: int = 5) -> str:
    """Search the web using DuckDuckGo (no API key needed).

    Uses DuckDuckGo HTML endpoint with robust parsing and fallback.
    """
    import re

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) okti/0.2",
                },
            )
            resp.raise_for_status()
            html = resp.text

            results = []
            # Try structured parsing first
            # DuckDuckGo HTML uses <a class="result__a"> for links
            # and <a class="result__snippet"> for snippets
            link_pattern = re.compile(r'class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>', re.DOTALL)
            snippet_pattern = re.compile(r'class="result__snippet"[^>]*>(.*?)</a>', re.DOTALL)

            links = link_pattern.findall(html)
            snippets = snippet_pattern.findall(html)

            for i in range(min(num_results, len(links))):
                url = links[i][0] if links[i][0].startswith("http") else f"https://duckduckgo.com/{links[i][0]}"
                title = re.sub(r'<[^>]+>', '', links[i][1]).strip()
                snippet = re.sub(r'<[^>]+>', '', snippets[i][1]).strip() if i < len(snippets) else ""
                if title:
                    results.append(f"{i + 1}. [{title}]({url})\n   {snippet}")

            if not results:
                # Fallback: extract any links and text
                all_links = re.findall(r'href="(https?://[^"]+)"', html)
                text_clean = re.sub(r'<[^>]+>', ' ', html)
                text_clean = re.sub(r'\s+', ' ', text_clean).strip()

                if all_links:
                    for i, link in enumerate(all_links[:num_results]):
                        results.append(f"{i + 1}. {link}")

                if not results:
                    return f"Search: {query}\n\n{text_clean[:5000]}"

            return f"Search results for: {query}\n\n" + "\n\n".join(results)

    except Exception as e:
        return f"Search error: {type(e).__name__}: {e}"


def register_web_tools(registry: ToolRegistry) -> None:
    """Register web tools."""
    registry.register(ToolDef(
        name="web_fetch",
        description="Fetch a URL and return its content. Supports HTML, JSON, and plain text.",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to fetch"},
                "format": {"type": "string", "description": "Expected format: text, json, html", "enum": ["text", "json", "html"]},
            },
            "required": ["url"],
        },
        handler=web_fetch,
        risk_level="low",
    ))

    registry.register(ToolDef(
        name="web_search",
        description="Search the web using DuckDuckGo. No API key needed.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "num_results": {"type": "integer", "description": "Number of results (default: 5)"},
            },
            "required": ["query"],
        },
        handler=web_search,
        risk_level="low",
    ))
