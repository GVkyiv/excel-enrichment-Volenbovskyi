"""Пошук в інтернеті: загальний шлях для завдань без структурованого джерела.

Основний провайдер Tavily (безкоштовний тариф, ключ у змінній оточення),
резервний ddgs (без ключа, менш стабільний). Сам пошук нічого не
вирішує: він повертає сніпети, значення з них витягує модель, а далі
працює валідатор.
"""

from __future__ import annotations

import logging

from ..cache import Cache
from ..config import TAVILY_API_KEY
from ..http_client import http_client

logger = logging.getLogger(__name__)

MAX_RESULTS = 5


class SearchUnavailableError(RuntimeError):
    """Жоден провайдер пошуку не доступний."""


def search(query: str, cache: Cache) -> list[dict[str, str]]:
    """Сніпети за запитом. Результат кешується, повтор безкоштовний."""
    cached = cache.get("search", query)
    if cached is not None:
        return cached

    http_client.count_external()
    results = _search_tavily(query) or _search_ddgs(query)
    if results is None:
        raise SearchUnavailableError(
            "Пошук недоступний: не задано TAVILY_API_KEY і не встановлено "
            "резервний пакет ddgs. Впишіть ключ у .env або виконайте "
            "pip install ddgs."
        )
    cache.set("search", query, results)
    return results


def _search_tavily(query: str) -> list[dict[str, str]] | None:
    if not TAVILY_API_KEY:
        return None
    try:
        from tavily import TavilyClient

        client = TavilyClient(api_key=TAVILY_API_KEY)
        response = client.search(query=query, max_results=MAX_RESULTS)
        return [
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "content": item.get("content", ""),
            }
            for item in response.get("results", [])
        ]
    except Exception as error:
        logger.warning("Tavily не відповів (%s), пробую резервний пошук", error)
        return None


def _search_ddgs(query: str) -> list[dict[str, str]] | None:
    try:
        from ddgs import DDGS
    except ImportError:
        return None
    try:
        with DDGS() as ddgs:
            return [
                {
                    "title": item.get("title", ""),
                    "url": item.get("href", ""),
                    "content": item.get("body", ""),
                }
                for item in ddgs.text(query, max_results=MAX_RESULTS)
            ]
    except Exception as error:
        logger.warning("Резервний пошук ddgs не відповів: %s", error)
        return None
