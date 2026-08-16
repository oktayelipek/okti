"""Web tools — web_fetch and web_search (optional)."""

from __future__ import annotations

import logging

import httpx

from oktigent.tools.registry import ToolDef, ToolRegistry

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
    """Search the web using DuckDuckGo Lite (no API key needed)."""
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(
                "https://lite.duckduckgo.com/lite/",
                params={"q": query},
                headers={"User-Agent": "oktigent/0.1"},
            )
            resp.raise_for_status()

            # Basic parsing
            import re
            text = resp.text
            # Extract search result links
            links = re.findall(r'class="result-link"[^>]*>([^<]+)<', text)
            snippets = re.findall(r'class="result-snippet"[^>]*>([^<]+)<', text)

            results = []
            for i in range(min(num_results, len(links), len(snippets))):
                results.append(f"{i + 1}. {links[i].strip()}\n   {snippets[i].strip()}")

            if not results:
                # Try alternative parsing
                text_clean = re.sub(r"<[^>]+>", " ", text)
                text_clean = re.sub(r"\s+", " ", text_clean).strip()
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
