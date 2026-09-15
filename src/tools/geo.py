"""Географія: пряма відстань за формулою і відстань дорогами.

Пряма відстань рахується кодом за координатами з Wikidata. Це свідоме
архітектурне рішення: те, що задається формулою, моделі не віддають.
Результат відтворюється до кілометра будь-ким, хто повторить розрахунок.
"""

from __future__ import annotations

import logging
from math import asin, cos, radians, sin, sqrt

from ..cache import Cache
from ..config import (
    EARTH_RADIUS_KM,
    NOMINATIM_MIN_INTERVAL,
    NOMINATIM_URL,
    OSRM_MIN_INTERVAL,
    OSRM_URL,
)
from ..http_client import RateLimiter, http_client

logger = logging.getLogger(__name__)

# Обидва джерела мають обмеження за частотою, тому звертання до них
# серіалізуються незалежно від розміру пулу потоків.
nominatim_limiter = RateLimiter(NOMINATIM_MIN_INTERVAL)
osrm_limiter = RateLimiter(OSRM_MIN_INTERVAL)


def haversine_km(
    point_from: tuple[float, float], point_to: tuple[float, float]
) -> float:
    """Відстань по великому колу між двома точками, кілометри."""
    lat1, lon1 = point_from
    lat2, lon2 = point_to
    d_lat = radians(lat2 - lat1)
    d_lon = radians(lon2 - lon1)
    inner = (
        sin(d_lat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lon / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * asin(sqrt(inner))


def road_km(
    point_from: tuple[float, float], point_to: tuple[float, float], cache: Cache
) -> float | None:
    """Довжина автомобільного маршруту між точками, кілометри.

    Публічний демо-сервер OSRM не можна навантажувати, тому запити йдуть
    послідовно з інтервалом в секунду, а результат кешується.
    """
    key = f"{point_from[0]:.4f},{point_from[1]:.4f};{point_to[0]:.4f},{point_to[1]:.4f}"
    cached = cache.get("osrm", key)
    if cached is not None:
        return cached or None

    url = (
        f"{OSRM_URL}/{point_from[1]},{point_from[0]};{point_to[1]},{point_to[0]}"
    )
    response = http_client.get(
        url, params={"overview": "false"}, limiter=osrm_limiter
    )
    payload = response.json()
    if payload.get("code") != "Ok" or not payload.get("routes"):
        cache.set("osrm", key, 0)
        logger.info("OSRM не побудував маршрут для %s", key)
        return None
    distance = payload["routes"][0]["distance"] / 1000.0
    cache.set("osrm", key, distance)
    return distance


def nominatim_coordinates(name: str, cache: Cache) -> tuple[float, float] | None:
    """Запасне геокодування, коли назви немає у Wikidata.

    Дотримується політики OSM: не більше одного запиту в секунду і
    обов'язковий User-Agent (заданий у спільному HTTP-клієнті).
    """
    cached = cache.get("nominatim", name)
    if cached is not None:
        return tuple(cached) if cached else None

    response = http_client.get(
        NOMINATIM_URL,
        params={"q": name, "format": "json", "limit": 1},
        limiter=nominatim_limiter,
    )
    payload = response.json()
    if not payload:
        cache.set("nominatim", name, [])
        return None
    point = (float(payload[0]["lat"]), float(payload[0]["lon"]))
    cache.set("nominatim", name, list(point))
    return point
