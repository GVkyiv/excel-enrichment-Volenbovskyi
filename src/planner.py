"""Планувальник: єдине місце, де завдання природною мовою стає планом.

Викликається один раз на файл. Саме тому система універсальна: при зміні
завдання змінюється план, а не код.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .models import EnrichmentPlan, ToolName, ValidationBounds, ValueType
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

Для geo_distance і wikidata_lookup обов'язково вкажи wikidata_type, тобто
тип сутності, про яку йдеться в рядках: Q8502 гора, Q515 місто, Q6256
країна, Q4022 річка. Ця підказка знімає омонімію назв: наприклад
«Annapurna» це водночас гірський масив і вершина, і без типу система
візьме масив, бо він відоміший.

Правила:
1. target_column це колонка з завдання. Якщо її в таблиці немає, вкажи
   назву, яку треба створити.
2. bounds це межі правдоподібності значення, вони відсікають нісенітницю.
   Наприклад для висоти гори від 100 до 9000 метрів.
3. search_query_template це шаблон запиту з підстановкою назв колонок у
   фігурних дужках, наприклад "height of {Mountain} in {Country} meters".
   Заповнюй його завжди, навіть коли основний інструмент інший: цим
   шаблоном система користується, якщо основний шлях не дав значення.
4. Якщо поняття в завданні має кілька усталених трактувань (наприклад
   відстань буває пряма і дорогами), перелічи їх в ambiguous_interpretations,
   а в extra_columns додай колонку для другого трактування. В основну
   колонку йде те трактування, яке прямо назване в завданні. Назву
   додаткової колонки склади за схемою «цільова колонка, підкреслення,
   трактування англійською одним словом», наприклад distance_road.
5. Для однозначних величин (висота, населення, дата) ambiguous_interpretations
   лишається порожнім.
6. reasoning це один-два речення українською про те, чому обрано цей шлях.
7. input_columns це список пар «аргумент інструмента, назва колонки».
   extra_columns це список пар «назва нової колонки, трактування».
   Поля, які не потрібні цьому інструменту, став у null, а списки, яких
   немає, лишай порожніми.
"""


class PlanError(ValueError):
    """План не відповідає структурі файлу. Текст призначений людині."""


class ColumnBinding(BaseModel):
    """Прив'язка аргумента інструмента до колонки файлу."""

    argument: str
    column: str


class ExtraColumn(BaseModel):
    """Додаткова колонка під друге трактування поняття."""

    column: str
    interpretation: str


class PlannerOutput(BaseModel):
    """Схема відповіді моделі.

    Відрізняється від `EnrichmentPlan` навмисно: строгий структурований
    вихід OpenAI вимагає, щоб усі поля були обов'язковими і щоб не було
    словників з довільними ключами. Тому замість словників тут списки
    пар, а необов'язкові поля описані як `| None`. Перетворення в
    робочий план робить метод `to_plan`.
    """

    target_column: str
    value_type: ValueType
    unit: str | None
    tool: ToolName
    input_columns: list[ColumnBinding]
    wikidata_property: str | None
    wikidata_type: str | None
    search_query_template: str
    min_value: float | None
    max_value: float | None
    ambiguous_interpretations: list[str]
    extra_columns: list[ExtraColumn]
    reasoning: str

    def to_plan(self) -> EnrichmentPlan:
        return EnrichmentPlan(
            target_column=self.target_column,
            value_type=self.value_type,
            unit=self.unit,
            tool=self.tool,
            input_columns={
                binding.argument: binding.column for binding in self.input_columns
            },
            wikidata_property=self.wikidata_property,
            wikidata_type=self.wikidata_type,
            search_query_template=self.search_query_template,
            bounds=ValidationBounds(
                min_value=self.min_value, max_value=self.max_value
            ),
            ambiguous_interpretations=self.ambiguous_interpretations,
            extra_columns={
                extra.column: extra.interpretation for extra in self.extra_columns
            },
            reasoning=self.reasoning,
        )


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
    plan = llm.parse(PLANNER_SYSTEM, user, PlannerOutput).to_plan()
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
    if not plan.search_query_template.strip():
        raise PlanError(
            "План не містить шаблону пошукового запиту: без нього система "
            "не зможе відкотитись на пошук, якщо основне джерело мовчатиме"
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
