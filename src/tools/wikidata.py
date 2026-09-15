"""Wikidata як основне структуроване джерело.

Ключова ідея для ефективності: назви сутностей розв'язуються пакетами.
Тисяча рядків це одиниці SPARQL-запитів, а не тисяча звернень.

Розпізнавання сутності за назвою зроблено без підказок про тип: беруться
всі елементи з такою назвою (основною або альтернативною), які мають
потрібну властивість, і серед них обирається найвідоміший за кількістю
мовних розділів. «Paris» так дає місто Париж, а не Париж у Техасі,
«Everest» дає гору, бо тільки в неї є висота над рівнем моря.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from ..cache import Cache
from ..config import WIKIDATA_BATCH_SIZE, WIKIDATA_SPARQL_URL
from ..http_client import http_client

logger = logging.getLogger(__name__)

POINT_RE = re.compile(r"Point\(\s*(-?[\d.]+)\s+(-?[\d.]+)\s*\)")

SPARQL_TEMPLATE = """
SELECT ?label ?item ?value ?links WHERE {{
  VALUES ?label {{ {labels} }}
  ?item rdfs:label|skos:altLabel ?label .
  ?item wdt:{property_id} ?value .
  ?item wikibase:sitelinks ?links .
}}
ORDER BY DESC(?links)
"""


def _escape(label: str) -> str:
    return label.replace("\\", "\\\\").replace('"', '\\"')


def lookup_property(
    labels: list[str], property_id: str, cache: Cache
) -> dict[str, dict[str, Any]]:
    """Значення властивості `property_id` для списку назв.

    Повертає словник «назва -> {value, item, links}». Назви, для яких
    нічого не знайдено, у результаті відсутні.
    """
    unique = sorted({label.strip() for label in labels if label and str(label).strip()})
    resolved: dict[str, dict[str, Any]] = {}
    missing: list[str] = []

    for label in unique:
        cached = cache.get("wikidata", f"{property_id}|{label}")
        if cached is None:
            missing.append(label)
        elif cached:  # порожній словник означає «шукали, не знайшли»
            resolved[label] = cached

    for start in range(0, len(missing), WIKIDATA_BATCH_SIZE):
        batch = missing[start : start + WIKIDATA_BATCH_SIZE]
        resolved.update(_query_batch(batch, property_id, cache))

    return resolved


def _query_batch(
    labels: list[str], property_id: str, cache: Cache
) -> dict[str, dict[str, Any]]:
    query = SPARQL_TEMPLATE.format(
        labels=" ".join(f'"{_escape(label)}"@en' for label in labels),
        property_id=property_id,
    )
    response = http_client.get(
        WIKIDATA_SPARQL_URL,
        params={"query": query, "format": "json"},
        headers={"Accept": "application/sparql-results+json"},
    )
    bindings = response.json()["results"]["bindings"]

    candidates: dict[str, list[dict[str, Any]]] = {}
    for binding in bindings:
        label = binding["label"]["value"]
        candidates.setdefault(label, []).append(
            {
                "value": binding["value"]["value"],
                "item": binding["item"]["value"],
                "links": int(binding["links"]["value"]),
            }
        )

    best: dict[str, dict[str, Any]] = {}
    for label, found in candidates.items():
        found.sort(key=lambda item: item["links"], reverse=True)
        chosen = dict(found[0])
        rivals = [item for item in found[1:] if _differs(item["value"], chosen["value"])]
        if rivals:
            # Назва описує кілька різних об'єктів (класика: «Annapurna» це
            # і масив, і вершина Аннапурна I). Беремо найвідоміший, але
            # чесно віддаємо альтернативи далі, щоб вони потрапили в лог.
            chosen["ambiguous"] = True
            chosen["alternatives"] = [
                {"value": item["value"], "item": item["item"]} for item in rivals[:2]
            ]
        best[label] = chosen

    for label in labels:
        cache.set("wikidata", f"{property_id}|{label}", best.get(label, {}))
    missing = [label for label in labels if label not in best]
    if missing:
        logger.info("Wikidata не знає властивість %s для: %s", property_id, missing)
    return best


def _differs(first: str, second: str, threshold: float = 0.10) -> bool:
    """Чи різні два значення однієї властивості у різних кандидатів."""
    try:
        left, right = float(first), float(second)
    except (TypeError, ValueError):
        return str(first).strip() != str(second).strip()
    if right == 0:
        return left != 0
    return abs(left - right) / abs(right) > threshold


def coordinates(labels: list[str], cache: Cache) -> dict[str, dict[str, Any]]:
    """Координати для списку назв, властивість P625.

    Повертає «назва -> {point: (широта, довгота), item: посилання}».
    Посилання на елемент Wikidata потрібне логу: будь-яке значення в
    результаті має вести на джерело, з якого воно взяте.
    """
    found = lookup_property(labels, "P625", cache)
    result: dict[str, dict[str, Any]] = {}
    for label, payload in found.items():
        match = POINT_RE.match(payload["value"])
        if match is None:
            logger.warning("Незрозумілий формат координат для %s: %s", label, payload)
            continue
        longitude, latitude = float(match.group(1)), float(match.group(2))
        result[label] = {"point": (latitude, longitude), "item": payload["item"]}
    return result
