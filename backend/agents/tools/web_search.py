"""
Web search tool — uses Tavily (primary) or SerpAPI (fallback)
"""
from config import settings


async def web_search(query: str, max_results: int = 5) -> list[dict]:
    if settings.tavily_api_key:
        return await _tavily_search(query, max_results)
    elif settings.serp_api_key:
        return await _serp_search(query, max_results)
    return [{"title": "Search not configured", "content": "No search API key provided.", "url": ""}]


async def _tavily_search(query: str, max_results: int) -> list[dict]:
    from tavily import TavilyClient
    client = TavilyClient(api_key=settings.tavily_api_key)
    response = client.search(query=query, max_results=max_results)
    return [
        {"title": r.get("title", ""), "content": r.get("content", ""), "url": r.get("url", "")}
        for r in response.get("results", [])
    ]


async def _serp_search(query: str, max_results: int) -> list[dict]:
    from serpapi import GoogleSearch
    search = GoogleSearch({"q": query, "api_key": settings.serp_api_key, "num": max_results})
    results = search.get_dict().get("organic_results", [])
    return [
        {"title": r.get("title", ""), "content": r.get("snippet", ""), "url": r.get("link", "")}
        for r in results
    ]
