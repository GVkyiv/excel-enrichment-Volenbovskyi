"""Wikidata як основне структуроване джерело.

Ключова ідея для ефективності: назви сутностей розв'язуються пакетами.
Тисяча рядків це одиниці SPARQL-запитів, а не тисяча звернень.

Розпізнавання сутності за назвою відбувається у три кроки:

1. Беруться всі елементи з такою назвою (основною або альтернативною),
   які мають потрібну властивість.
2. Якщо план дав підказку про тип (гора, місто), перевага віддається
   елементам цього типу. Це вирішує класичний випадок «Annapurna»:
   назва позначає і гірський масив, і вершину Аннапурна I, а завданню
   потрібна саме вершина.
3. Серед тих, що лишились, береться найвідоміший за кількістю мовних
   розділів. Якщо в обраного елемента кілька значень властивості,
   перевага віддається тому, яке підтверджують інші кандидати.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from ..cache import Cache
from ..config import (
    HTTP_TIMEOUT_BATCH,
    TYPE_HINT_MIN_SHARE,
    WIKIDATA_BATCH_SIZE,
    WIKIDATA_SPARQL_URL,
)
from ..http_client import http_client

logger = logging.getLogger(__name__)

POINT_RE = re.compile(r"Point\(\s*(-?[\d.]+)\s+(-?[\d.]+)\s*\)")

SPARQL_TEMPLATE = """
SELECT ?label ?item ?value ?links ?typed WHERE {{
  VALUES ?label {{ {labels} }}
  ?item rdfs:label|skos:altLabel ?label .
  ?item wdt:{property_id} ?value .
  ?item wikibase:sitelinks ?links .
  {type_clause}
}}
"""

TYPE_CLAUSE = "OPTIONAL {{ ?item wdt:P31/wdt:P279* wd:{type_qid} . BIND(true AS ?typed) }}"


def _escape(label: str) -> str:
    return label.replace("\\", "\\\\").replace('"', '\\"')


def lookup_property(
    labels: list[str],
    property_id: str,
    cache: Cache,
    type_qid: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Значення властивості `property_id` для списку назв.

    Аргумент `type_qid` це підказка про тип сутності з плану, наприклад
    Q8502 для гори або Q515 для міста. Підказка не є жорстким фільтром:
    якщо жоден елемент цього типу не знайдено, беруться всі кандидати.

    Повертає словник «назва -> {value, item, links}». Назви, для яких
    нічого не знайдено, у результаті відсутні.
    """
    unique = sorted({label.strip() for label in labels if label and str(label).strip()})
    resolved: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    cache_scope = f"{property_id}|{type_qid or 'any'}"

    for label in unique:
        cached = cache.get("wikidata", f"{cache_scope}|{label}")
        if cached is None:
            missing.append(label)
        elif cached:  # порожній словник означає «шукали, не знайшли»
            resolved[label] = cached

    for start in range(0, len(missing), WIKIDATA_BATCH_SIZE):
        batch = missing[start : start + WIKIDATA_BATCH_SIZE]
        resolved.update(_query_batch(batch, property_id, cache, type_qid, cache_scope))

    return resolved


def _query_batch(
    labels: list[str],
    property_id: str,
    cache: Cache,
    type_qid: str | None,
    cache_scope: str,
) -> dict[str, dict[str, Any]]:
    query = SPARQL_TEMPLATE.format(
        labels=" ".join(f'"{_escape(label)}"@en' for label in labels),
        property_id=property_id,
        type_clause=TYPE_CLAUSE.format(type_qid=type_qid) if type_qid else "",
    )
    response = http_client.get(
        WIKIDATA_SPARQL_URL,
        params={"query": query, "format": "json"},
        headers={"Accept": "application/sparql-results+json"},
        timeout=HTTP_TIMEOUT_BATCH,
    )
    bindings = response.json()["results"]["bindings"]

    # назва -> елемент -> {values, links, typed}
    candidates: dict[str, dict[str, dict[str, Any]]] = {}
    for binding in bindings:
        label = binding["label"]["value"]
        item = binding["item"]["value"]
        entry = candidates.setdefault(label, {}).setdefault(
            item,
            {"values": [], "links": int(binding["links"]["value"]), "typed": False},
        )
        entry["values"].append(binding["value"]["value"])
        if "typed" in binding:
            entry["typed"] = True

    best = {label: _choose(items) for label, items in candidates.items()}

    for label in labels:
        cache.set("wikidata", f"{cache_scope}|{label}", best.get(label, {}))
    missing = [label for label in labels if label not in best]
    if missing:
        logger.info("Wikidata не знає властивість %s для: %s", property_id, missing)
    return best


def _choose(items: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Обирає один елемент і одне значення серед кандидатів на назву.

    Підказка про тип не є жорстким фільтром. Якщо єдиний типізований
    кандидат помітно менш відомий за нетипізованого лідера, підказка
    вважається хибною і ігнорується: так «Madrid» лишається столицею
    Іспанії, хоч формально вона не позначена як Q515, а «Annapurna»
    стає вершиною, а не масивом. Поріг у `config.TYPE_HINT_MIN_SHARE`.
    """
    typed = {item: data for item, data in items.items() if data["typed"]}
    pool = items
    if typed:
        best_typed = max(data["links"] for data in typed.values())
        best_overall = max(data["links"] for data in items.values())
        if best_typed >= TYPE_HINT_MIN_SHARE * best_overall:
            pool = typed
        else:
            logger.info(
                "Підказку про тип проігноровано: типізований кандидат має %s "
                "мовних розділів проти %s у лідера",
                best_typed,
                best_overall,
            )

    item, data = max(pool.items(), key=lambda pair: pair[1]["links"])
    values = list(dict.fromkeys(data["values"]))
    others = [
        value
        for other_item, other in pool.items()
        if other_item != item
        for value in other["values"]
    ]

    value, value_note = _pick_value(values, others)
    chosen: dict[str, Any] = {"value": value, "item": item, "links": data["links"]}

    rivals = [
        {"value": other["values"][0], "item": other_item}
        for other_item, other in pool.items()
        if other_item != item and _differs(other["values"][0], value)
    ]
    if rivals or value_note:
        chosen["ambiguous"] = True
        chosen["alternatives"] = rivals[:2]
        if value_note:
            chosen["note"] = value_note
    return chosen


def _pick_value(values: list[str], others: list[str]) -> tuple[str, str]:
    """Одне значення з кількох у того самого елемента.

    Перевага тому, яке підтверджує інший кандидат: у масиву Аннапурна
    записано і 7756, і 8091 метрів, а 8091 підтверджується окремою
    статтею про вершину.
    """
    if len(values) == 1:
        return values[0], ""
    if others:
        # Беремо не перше «достатньо близьке», а найкраще збіжне: 7756 і
        # 8091 відрізняються лише на 4 відсотки, тому правило «в межах
        # порогу» тут нічого не вирішує, вирішує саме мінімум розбіжності.
        scored = [(_distance_to_nearest(value, others), value) for value in values]
        best_distance, best_value = min(scored, key=lambda pair: pair[0])
        if best_distance is not None:
            return best_value, (
                f"у джерела кілька значень {values}, узято підтверджене іншим "
                f"елементом Wikidata"
            )
    return values[0], f"у джерела кілька значень {values}, узято перше"


def _distance_to_nearest(value: str, others: list[str]) -> float:
    """Найменша відносна розбіжність значення з чужими значеннями."""
    best = float("inf")
    for other in others:
        try:
            left, right = float(value), float(other)
        except (TypeError, ValueError):
            best = min(best, 0.0 if str(value).strip() == str(other).strip() else 1.0)
            continue
        if right == 0:
            best = min(best, 0.0 if left == 0 else 1.0)
            continue
        best = min(best, abs(left - right) / abs(right))
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


def coordinates(
    labels: list[str], cache: Cache, type_qid: str | None = None
) -> dict[str, dict[str, Any]]:
    """Координати для списку назв, властивість P625.

    Повертає «назва -> {point: (широта, довгота), item: посилання}».
    Посилання на елемент Wikidata потрібне логу: будь-яке значення в
    результаті має вести на джерело, з якого воно взяте.
    """
    found = lookup_property(labels, "P625", cache, type_qid)
    result: dict[str, dict[str, Any]] = {}
    for label, payload in found.items():
        match = POINT_RE.match(payload["value"])
        if match is None:
            logger.warning("Незрозумілий формат координат для %s: %s", label, payload)
            continue
        longitude, latitude = float(match.group(1)), float(match.group(2))
        result[label] = {"point": (latitude, longitude), "item": payload["item"]}
    return result
