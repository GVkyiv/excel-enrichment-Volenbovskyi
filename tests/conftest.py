"""Спільні фікстури тестів.

Головне правило набору: жоден тест не ходить у мережу і не викликає
модель. Усе, що залежить від зовнішнього світу, підміняється, інакше
тести перестають бути перевіркою коду і стають перевіркою інтернету.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.cache import Cache  # noqa: E402
from src.models import EnrichmentPlan, ValidationBounds  # noqa: E402
from src.tools import ToolContext  # noqa: E402


@pytest.fixture
def cache(tmp_path: Path) -> Cache:
    """Кеш у тимчасовому файлі, щоб тести не чіпали робочий cache.sqlite."""
    instance = Cache(tmp_path / "cache.sqlite")
    yield instance
    instance.close()


@pytest.fixture
def height_plan() -> EnrichmentPlan:
    """План на висоту гір: числове значення, метри, межі правдоподібності."""
    return EnrichmentPlan(
        target_column="height",
        value_type="number",
        unit="m",
        tool="wikidata_lookup",
        input_columns={"entity": "Mountain"},
        wikidata_property="P2044",
        wikidata_type="Q8502",
        search_query_template="height of {Mountain} in meters",
        bounds=ValidationBounds(min_value=100, max_value=9000),
    )


@pytest.fixture
def context(cache: Cache, height_plan: EnrichmentPlan) -> ToolContext:
    """Контекст прогону без моделі: гілка відкату на LLM недоступна."""
    return ToolContext(cache=cache, plan=height_plan, llm=None)


@pytest.fixture
def mountains_file(tmp_path: Path) -> Path:
    """Маленька книга з однією заповненою і двома порожніми комірками."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Mountain", "Country", "height"])
    sheet.append(["Mount Everest", "Nepal", None])
    sheet.append(["K2", "Pakistan", 8000])
    sheet.append(["Lhotse", "Nepal", None])
    path = tmp_path / "mountains.xlsx"
    workbook.save(path)
    return path
