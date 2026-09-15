"""Контракти даних.

План збагачення це єдина структура, якою планувальник керує рештою
системи. Він типізований через Pydantic: невалідна відповідь моделі це
помилка на вході, а не привід «здогадатись», що вона мала на увазі.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ToolName = Literal[
    "geo_distance",
    "wikidata_lookup",
    "web_search_extract",
    "llm_knowledge",
]

ValueType = Literal["number", "date", "text"]

RowStatus = Literal[
    "ok",
    "not_found",
    "unconfirmed",
    "ambiguous",
    "out_of_bounds",
    "network_error",
    "api_key_error",
    "skipped_empty_input",
    "skipped_filled",
]


class ValidationBounds(BaseModel):
    """Межі правдоподібності значення. Відсікають очевидну нісенітницю."""

    min_value: float | None = None
    max_value: float | None = None


class EnrichmentPlan(BaseModel):
    """Те, що планувальник виводить із тексту завдання і структури файлу."""

    target_column: str = Field(description="Колонка, яку заповнюємо")
    value_type: ValueType
    unit: str | None = Field(default=None, description="km, m, або None")
    tool: ToolName
    input_columns: dict[str, str] = Field(
        default_factory=dict,
        description="Аргумент інструмента -> назва колонки у файлі",
    )
    wikidata_property: str | None = Field(
        default=None, description="Ідентифікатор властивості, напр. P2044"
    )
    search_query_template: str = Field(
        default="", description="Шаблон запиту з підстановкою {Колонка}"
    )
    bounds: ValidationBounds = Field(default_factory=ValidationBounds)
    ambiguous_interpretations: list[str] = Field(
        default_factory=list,
        description="Кілька усталених трактувань, напр. straight і road",
    )
    extra_columns: dict[str, str] = Field(
        default_factory=dict,
        description="Додаткова колонка -> трактування, яке в неї пишемо",
    )
    reasoning: str = Field(default="", description="Чому обрано саме цей шлях")


class RowResult(BaseModel):
    """Результат по одному рядку. Рівно це лягає в аркуш enrichment_log."""

    row_index: int
    target_column: str
    value: float | str | None = None
    unit: str | None = None
    tool: str = ""
    source_url: str = ""
    query: str = ""
    confidence_level: int = 0  # 1 структуроване джерело, 2 пошук, 3 модель
    status: RowStatus = "not_found"
    message: str = ""
    duration_ms: int = 0
    llm_calls: int = 0
    extra_values: dict[str, float | str | None] = Field(default_factory=dict)


class EnrichmentReport(BaseModel):
    """Підсумок прогону. Повертається викликачу і друкується в консоль."""

    file_path: str
    output_path: str = ""
    task_description: str = ""
    plan: EnrichmentPlan | None = None
    rows_total: int = 0
    filled: int = 0
    not_found: int = 0
    errors: int = 0
    skipped: int = 0
    llm_calls: int = 0
    network_calls: int = 0
    cache_hits: int = 0
    duration_s: float = 0.0
    cost_usd: float = 0.0
    rows: list[RowResult] = Field(default_factory=list)

    def summary_lines(self) -> list[str]:
        """Рядки підсумку українською для друку в консоль."""
        return [
            f"Файл: {self.file_path}",
            f"Збережено: {self.output_path}",
            f"Рядків усього: {self.rows_total}",
            f"Заповнено: {self.filled}",
            f"Не знайдено: {self.not_found}",
            f"Помилок: {self.errors}",
            f"Пропущено (вже заповнені або порожній вхід): {self.skipped}",
            f"Викликів моделі: {self.llm_calls}",
            f"Мережевих запитів: {self.network_calls} (з кешу: {self.cache_hits})",
            f"Час: {self.duration_s:.1f} с",
            f"Оцінена вартість: {self.cost_usd:.4f} USD",
        ]
