"""Built-in web tools."""

from __future__ import annotations

import os
import re
from html import unescape
from urllib.parse import urlparse

from mindbot.capability.backends.tooling.models import Tool

_USER_AGENT = "MindBot/1.0"


def _strip_html(html: str) -> str:
    text = re.sub(r"<script[\s\S]*?</script>", "", html, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", "", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return unescape(text).strip()


def _validate_url(url: str) -> str | None:
    try:
        parsed = urlparse(url)
    except ValueError as exc:
        return str(exc)
    if parsed.scheme not in {"http", "https"}:
        return "only http and https URLs are allowed"
    if not parsed.netloc:
        return "URL is missing a host"
    return None


def create_web_tools() -> list[Tool]:
    """Create built-in web tools."""

    async def fetch_url(url: str, timeout: int = 20, max_chars: int = 50_000) -> str:
        error = _validate_url(url)
        if error:
            return f"Error: invalid URL: {error}"

        import httpx

        try:
            async with httpx.AsyncClient(timeout=max(timeout, 1), follow_redirects=True) as client:
                response = await client.get(url, headers={"User-Agent": _USER_AGENT})
                response.raise_for_status()
        except Exception as exc:
            return f"Error fetching URL: {exc}"

        body = response.text
        content_type = response.headers.get("content-type", "")
        if "html" in content_type:
            body = _strip_html(body)
        if len(body) > max_chars:
            body = body[:max_chars] + "\n... (truncated)"
        return body

    async def web_search(query: str, max_results: int = 5) -> str:
        api_key = os.environ.get("BRAVE_API_KEY", "")
        if not api_key:
            return (
                "Error: web_search is unavailable because BRAVE_API_KEY is not configured. "
                "Set BRAVE_API_KEY to enable web search."
            )

        import httpx

        count = min(max(max_results, 1), 10)
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    params={"q": query, "count": count},
                    headers={
                        "Accept": "application/json",
                        "User-Agent": _USER_AGENT,
                        "X-Subscription-Token": api_key,
                    },
                )
                response.raise_for_status()
        except Exception as exc:
            return f"Error performing web search: {exc}"

        results = response.json().get("web", {}).get("results", [])[:count]
        if not results:
            return f"No results for: {query}"

        lines = [f"Results for: {query}"]
        for idx, item in enumerate(results, start=1):
            lines.append(f"{idx}. {item.get('title', '')}")
            lines.append(f"   {item.get('url', '')}")
            description = item.get("description")
            if description:
                lines.append(f"   {description}")
        return "\n".join(lines)

    return [
        Tool(
            name="fetch_url",
            description="Fetch a URL and return the readable text content.",
            parameters_schema_override={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "HTTP or HTTPS URL to fetch."},
                    "timeout": {"type": "integer", "description": "Timeout in seconds.", "default": 20},
                    "max_chars": {
                        "type": "integer",
                        "description": "Maximum number of characters to return.",
                        "default": 50000,
                    },
                },
                "required": ["url"],
            },
            handler=fetch_url,
        ),
        Tool(
            name="web_search",
            description="Search the web using Brave Search and return titles, links, and snippets.",
            parameters_schema_override={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query."},
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of search results.",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
            handler=web_search,
        ),
    ]
