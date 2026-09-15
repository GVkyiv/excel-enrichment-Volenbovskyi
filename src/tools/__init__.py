"""Реєстр інструментів.

Кожен інструмент має однаковий контракт: на вхід рядок таблиці і
контекст прогону, на вихід `ToolOutcome`. Завдяки цьому планувальник
обирає інструмент назвою, а решта системи про інструменти нічого не знає.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from ..cache import Cache
from ..models import EnrichmentPlan
from . import geo, wikidata, websearch
from .llm import LLMClient, ask_knowledge, extract_from_snippets

logger = logging.getLogger(__name__)

PLACEHOLDER_RE = re.compile(r"\{([^{}]+)\}")


@dataclass
class ToolContext:
    """Спільні дані прогону: кеш, попередньо отримані пакети, модель."""

    cache: Cache
    plan: EnrichmentPlan
    coordinates: dict[str, dict[str, Any]] = field(default_factory=dict)
    entity_values: dict[str, dict[str, Any]] = field(default_factory=dict)
    llm: LLMClient | None = None
    road_mode: bool = True


@dataclass
class ToolOutcome:
    """Результат роботи одного інструмента над одним рядком."""

    found: bool = False
    value: float | str | None = None
    extra_values: dict[str, float | str | None] = field(default_factory=dict)
    source_url: str = ""
    query: str = ""
    confidence_level: int = 0
    message: str = ""
    llm_calls: int = 0


def render_template(template: str, row: dict[str, Any]) -> str:
    """Підставляє значення колонок у шаблон запиту.

    Відсутня колонка не валить прогін: підставляється порожній рядок, а
    факт підстановки видно в логу за самим запитом.
    """

    def replace(match: re.Match[str]) -> str:
        column = match.group(1).strip()
        value = row.get(column)
        return "" if value is None else str(value)

    return PLACEHOLDER_RE.sub(replace, template).strip()


def _cell(row: dict[str, Any], plan: EnrichmentPlan, argument: str) -> str | None:
    """Значення колонки, прив'язаної планом до аргумента інструмента."""
    column = plan.input_columns.get(argument)
    if column is None:
        return None
    value = row.get(column)
    return None if value is None else str(value).strip()


# --- інструменти ---------------------------------------------------------


def geo_distance(row: dict[str, Any], context: ToolContext) -> ToolOutcome:
    """Пряма відстань за координатами, за потреби плюс відстань дорогами."""
    plan = context.plan
    label_from = _cell(row, plan, "from")
    label_to = _cell(row, plan, "to")
    if not label_from or not label_to:
        return ToolOutcome(message="У рядку немає обох точок маршруту")

    points: dict[str, tuple[float, float]] = {}
    sources: list[str] = []
    for label in (label_from, label_to):
        payload = context.coordinates.get(label)
        if payload is None:
            point = geo.nominatim_coordinates(label, context.cache)
            if point is None:
                return ToolOutcome(
                    message=f"Не вдалося визначити координати: {label}"
                )
            points[label] = point
            sources.append("https://nominatim.openstreetmap.org/")
        else:
            points[label] = payload["point"]
            sources.append(payload["item"])

    straight = geo.haversine_km(points[label_from], points[label_to])
    outcome = ToolOutcome(
        found=True,
        value=round(straight),
        source_url=" ; ".join(dict.fromkeys(sources)),
        query=f"haversine({label_from}, {label_to})",
        confidence_level=1,
        message="Велике коло за координатами Wikidata",
    )

    road_column = _road_column(plan)
    if context.road_mode and road_column:
        road = geo.road_km(points[label_from], points[label_to], context.cache)
        if road is not None:
            outcome.extra_values[road_column] = round(road)
            outcome.message += f"; автомобільний маршрут OSRM {round(road)} км"
    return outcome


def _road_column(plan: EnrichmentPlan) -> str | None:
    """Назва додаткової колонки для дорожнього трактування, якщо план її просить."""
    for column, interpretation in plan.extra_columns.items():
        if "road" in interpretation.lower() or "дорог" in interpretation.lower():
            return column
    return None


def wikidata_lookup(row: dict[str, Any], context: ToolContext) -> ToolOutcome:
    """Значення властивості Wikidata для сутності з рядка."""
    plan = context.plan
    label = _cell(row, plan, "entity")
    if not label:
        return ToolOutcome(message="У рядку немає назви сутності")

    payload = context.entity_values.get(label)
    if payload is None and plan.wikidata_property:
        # Рядок міг прийти в обхід пакетного попереднього запиту
        # (наприклад, як відкат з іншого інструмента), тоді питаємо точково.
        found = wikidata.lookup_property(
            [label], plan.wikidata_property, context.cache
        )
        context.entity_values.update(found)
        payload = found.get(label)
    if not payload:
        return ToolOutcome(
            message=f"Wikidata не має властивості {plan.wikidata_property} для «{label}»"
        )

    raw = payload["value"]
    value: float | str
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = str(raw)
    if payload.get("ambiguous"):
        alternatives = ", ".join(
            f"{item['value']} ({item['item'].rsplit('/', 1)[-1]})"
            for item in payload.get("alternatives", [])
        )
        return ToolOutcome(
            found=True,
            value=value,
            source_url=payload.get("item", ""),
            query=f"wikidata {plan.wikidata_property} / {label}",
            confidence_level=2,
            message=(
                f"Назва «{label}» описує кілька об'єктів, узято найвідоміший; "
                f"інші варіанти: {alternatives}"
            ),
        )

    return ToolOutcome(
        found=True,
        value=value,
        source_url=payload.get("item", ""),
        query=f"wikidata {plan.wikidata_property} / {label}",
        confidence_level=1,
        message="Структуроване джерело Wikidata",
    )


def web_search_extract(row: dict[str, Any], context: ToolContext) -> ToolOutcome:
    """Пошук в інтернеті плюс витягання значення моделлю з сніпетів."""
    plan = context.plan
    query = render_template(plan.search_query_template, row)
    if not query:
        return ToolOutcome(message="Порожній пошуковий запит за шаблоном плану")
    if context.llm is None:
        return ToolOutcome(
            query=query,
            message="Пошук знайшов текст, але без ключа моделі нікому витягти значення",
        )

    snippets = websearch.search(query, context.cache)
    if not snippets:
        return ToolOutcome(query=query, message="Пошук не дав результатів")

    extracted = extract_from_snippets(context.llm, query, plan.unit, snippets)
    if not extracted.found or extracted.value is None:
        return ToolOutcome(
            query=query,
            llm_calls=1,
            source_url=snippets[0].get("url", ""),
            message=extracted.comment or "У знайденому тексті значення немає",
        )
    return ToolOutcome(
        found=True,
        value=extracted.value,
        source_url=extracted.source_url or snippets[0].get("url", ""),
        query=query,
        confidence_level=2,
        llm_calls=1,
        message="Значення з пошукової видачі",
    )


def llm_knowledge(row: dict[str, Any], context: ToolContext) -> ToolOutcome:
    """Пам'ять моделі. Самостійно значення не підтверджує."""
    plan = context.plan
    question = render_template(plan.search_query_template, row)
    if context.llm is None:
        return ToolOutcome(message="Немає ключа моделі")
    answer = ask_knowledge(context.llm, question, plan.unit)
    if not answer.found or answer.value is None:
        return ToolOutcome(
            query=question,
            llm_calls=1,
            message=answer.comment or "Модель не має впевненої відповіді",
        )
    return ToolOutcome(
        found=True,
        value=answer.value,
        query=question,
        confidence_level=3,
        llm_calls=1,
        message="Відповідь з пам'яті моделі, потребує підтвердження",
    )


REGISTRY: dict[str, Callable[[dict[str, Any], ToolContext], ToolOutcome]] = {
    "geo_distance": geo_distance,
    "wikidata_lookup": wikidata_lookup,
    "web_search_extract": web_search_extract,
    "llm_knowledge": llm_knowledge,
}

# Порядок відкату: якщо основний інструмент не дав значення, система йде
# наступним. Пам'ять моделі завжди остання і завжди потребує підтвердження.
FALLBACK_CHAIN: dict[str, list[str]] = {
    "geo_distance": ["web_search_extract", "llm_knowledge"],
    "wikidata_lookup": ["web_search_extract", "llm_knowledge"],
    "web_search_extract": ["wikidata_lookup", "llm_knowledge"],
    "llm_knowledge": ["web_search_extract"],
}


def run_tool(name: str, row: dict[str, Any], context: ToolContext) -> ToolOutcome:
    """Виконує інструмент за назвою, перетворюючи збій на результат зі статусом."""
    tool = REGISTRY.get(name)
    if tool is None:
        return ToolOutcome(message=f"Невідомий інструмент: {name}")
    try:
        return tool(row, context)
    except Exception as error:  # мережа, ключі, несподіваний формат відповіді
        logger.warning("Інструмент %s не спрацював: %s", name, error)
        return ToolOutcome(message=f"{type(error).__name__}: {error}")
