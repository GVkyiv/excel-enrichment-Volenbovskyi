"""Планувальник: єдине місце, де завдання природною мовою стає планом.

Викликається один раз на файл. Саме тому система універсальна: при зміні
завдання змінюється план, а не код.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .models import EnrichmentPlan
from .tools.llm import LLMClient

logger = logging.getLogger(__name__)

PLANNER_SYSTEM = """
Ти плануєш збагачення таблиці даними з інтернету. На вхід отримуєш
структуру таблиці, кілька прикладів рядків і завдання природною мовою.
Повертаєш план у заданій структурі.

Доступні інструменти:
- geo_distance: відстань між двома географічними точками. input_columns
  має містити ключі "from" і "to" з назвами колонок. Підходить, коли в
  завданні йдеться про відстань між містами чи країнами.
- wikidata_lookup: властивість сутності зі структурованої бази Wikidata.
  input_columns має містити ключ "entity". Обов'язково вкажи
  wikidata_property, наприклад P2044 для висоти над рівнем моря,
  P1082 для населення, P571 для дати заснування.
- web_search_extract: загальний шлях через пошук в інтернеті. Обирай,
  коли структурованого джерела під завдання немає.
- llm_knowledge: відповідь з пам'яті моделі, лише як крайній випадок.

Правила:
1. target_column це колонка з завдання. Якщо її в таблиці немає, вкажи
   назву, яку треба створити.
2. bounds це межі правдоподібності значення, вони відсікають нісенітницю.
   Наприклад для висоти гори від 100 до 9000 метрів.
3. search_query_template це шаблон запиту з підстановкою назв колонок у
   фігурних дужках, наприклад "height of {Mountain} in {Country} meters".
4. Якщо поняття в завданні має кілька усталених трактувань (наприклад
   відстань буває пряма і дорогами), перелічи їх в ambiguous_interpretations,
   а в extra_columns додай колонку для другого трактування. В основну
   колонку йде те трактування, яке прямо назване в завданні.
5. Для однозначних величин (висота, населення, дата) ambiguous_interpretations
   лишається порожнім.
6. reasoning це один-два речення українською про те, чому обрано цей шлях.
"""


class PlanError(ValueError):
    """План не відповідає структурі файлу. Текст призначений людині."""


def build_plan(
    llm: LLMClient,
    task_description: str,
    headers: list[str],
    sample_rows: list[dict[str, Any]],
) -> EnrichmentPlan:
    """Один виклик моделі на файл."""
    user = (
        f"Завдання: {task_description}\n\n"
        f"Колонки таблиці: {headers}\n\n"
        f"Приклади рядків: {json.dumps(sample_rows, ensure_ascii=False)}"
    )
    plan = llm.parse(PLANNER_SYSTEM, user, EnrichmentPlan)
    logger.info("План побудовано: %s", plan.model_dump())
    return plan


def validate_plan(plan: EnrichmentPlan, headers: list[str]) -> None:
    """Звіряє план зі справжньою структурою файлу."""
    for argument, column in plan.input_columns.items():
        if column not in headers:
            raise PlanError(
                f"План посилається на колонку «{column}» (аргумент {argument}), "
                f"якої немає у файлі. Наявні колонки: {headers}"
            )
    if plan.tool == "geo_distance" and not {"from", "to"} <= set(plan.input_columns):
        raise PlanError(
            "Для розрахунку відстані план має містити колонки «from» і «to» "
            "в input_columns"
        )
    if plan.tool == "wikidata_lookup":
        if "entity" not in plan.input_columns:
            raise PlanError(
                "Для Wikidata план має містити колонку «entity» в input_columns"
            )
        if not plan.wikidata_property:
            raise PlanError(
                "Для Wikidata план має містити ідентифікатор властивості, "
                "наприклад P2044"
            )


def load_plan(path: Path | str) -> EnrichmentPlan:
    """Читає збережений план. Потрібен для повторюваних прогонів і тестів."""
    return EnrichmentPlan.model_validate_json(Path(path).read_text(encoding="utf-8"))


def save_plan(plan: EnrichmentPlan, path: Path | str) -> Path:
    """Зберігає план поруч із даними, щоб прогін можна було повторити."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(plan.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path
