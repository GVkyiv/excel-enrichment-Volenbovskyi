"""Спільний шар мережі: повтори, таймаути, дотримання лімітів джерел.

Винесено окремо, бо кожне джерело має власне обмеження частоти, і
розкидати ці правила по інструментах означало б рано чи пізно порушити
вимоги OSM або OSRM.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import requests

from .config import HTTP_BACKOFF, HTTP_RETRIES, HTTP_TIMEOUT, USER_AGENT

logger = logging.getLogger(__name__)


class NetworkError(RuntimeError):
    """Мережа не відповіла після всіх спроб."""


class RateLimiter:
    """Мінімальний інтервал між запитами до одного джерела."""

    def __init__(self, min_interval: float) -> None:
        self._min_interval = min_interval
        self._lock = threading.Lock()
        self._last_call = 0.0

    def wait(self) -> None:
        with self._lock:
            delta = time.monotonic() - self._last_call
            if delta < self._min_interval:
                time.sleep(self._min_interval - delta)
            self._last_call = time.monotonic()


class HttpClient:
    """Обгортка над requests із повторами і лічильником запитів."""

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": USER_AGENT})
        self._lock = threading.Lock()
        self.calls = 0

    def get(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        limiter: RateLimiter | None = None,
    ) -> requests.Response:
        """GET із трьома спробами і паузами 1, 2, 4 секунди."""
        last_error: Exception | None = None
        for attempt in range(HTTP_RETRIES):
            if limiter is not None:
                limiter.wait()
            try:
                with self._lock:
                    self.calls += 1
                response = self._session.get(
                    url, params=params, headers=headers, timeout=HTTP_TIMEOUT
                )
                if response.status_code == 429:
                    raise requests.HTTPError("429 Too Many Requests")
                response.raise_for_status()
                return response
            except Exception as error:  # мережа, таймаут, 5xx, 429
                last_error = error
                logger.warning(
                    "Запит до %s не вдався (спроба %s з %s): %s",
                    url,
                    attempt + 1,
                    HTTP_RETRIES,
                    error,
                )
                if attempt < HTTP_RETRIES - 1:
                    time.sleep(HTTP_BACKOFF[attempt])
        reason = str(last_error).split("(Caused by", 1)[0].strip()
        if len(reason) > 120:
            reason = reason[:120] + "..."
        raise NetworkError(
            f"Джерело {url.split('?')[0]} не відповіло після {HTTP_RETRIES} спроб "
            f"({type(last_error).__name__}: {reason})"
        )


http_client = HttpClient()
