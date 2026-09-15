"""Контракт плану: очищення ідентифікаторів і звірка зі структурою файлу.

Тут же зафіксовано регресію, знайдену аудитом: модель писала в поле типу
«Q515 city», і цей рядок потрапляв у текст SPARQL-запиту.
"""

from __future__ import annotations

import pytest

from src.models import EnrichmentPlan
from src.planner import ColumnBinding, PlanError, PlannerOutput, validate_plan


def _plan(**overrides) -> EnrichmentPlan:
    base = dict(
        target_column="height",
        value_type="number",
        tool="wikidata_lookup",
        input_columns={"entity": "Mountain"},
        wikidata_property="P2044",
        search_query_template="height of {Mountain}",
    )
    base.update(overrides)
    return EnrichmentPlan(**base)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Q515", "Q515"),
        ("Q515 city", "Q515"),
        ("місто (Q515)", "Q515"),
        ("місто", None),
        (None, None),
    ],
)
def test_ідентифікатор_типу_очищається(raw, expected):
    """Регресія аудиту: «Q515 city» ламав SPARQL з помилкою 400."""
    assert _plan(wikidata_type=raw).wikidata_type == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("P2044", "P2044"),
        ("властивість P2044 висота", "P2044"),
        ("висота", None),
    ],
)
def test_ідентифікатор_властивості_очищається(raw, expected):
    assert _plan(wikidata_property=raw).wikidata_property == expected


def test_план_з_невідомою_колонкою_відхиляється():
    plan = _plan(input_columns={"entity": "Гора"})
    with pytest.raises(PlanError, match="якої немає у файлі"):
        validate_plan(plan, ["Mountain", "Country", "height"])


def test_відстань_без_двох_точок_відхиляється():
    plan = _plan(tool="geo_distance", input_columns={"from": "Mountain"})
    with pytest.raises(PlanError, match="from"):
        validate_plan(plan, ["Mountain"])


def test_wikidata_без_властивості_відхиляється():
    plan = _plan(wikidata_property="просто текст")
    with pytest.raises(PlanError, match="ідентифікатор властивості"):
        validate_plan(plan, ["Mountain"])


def test_план_без_шаблону_запиту_відхиляється():
    """Без шаблону система не зможе відкотитись на пошук."""
    plan = _plan(search_query_template="   ")
    with pytest.raises(PlanError, match="шаблону пошукового запиту"):
        validate_plan(plan, ["Mountain"])


def test_коректний_план_проходить():
    validate_plan(_plan(), ["Mountain", "Country", "height"])


def test_відповідь_моделі_перетворюється_в_план():
    """Модель повертає списки пар, система працює зі словниками."""
    output = PlannerOutput(
        target_column="distance",
        value_type="number",
        unit="km",
        tool="geo_distance",
        input_columns=[
            ColumnBinding(argument="from", column="Capital_From"),
            ColumnBinding(argument="to", column="Capital_To"),
        ],
        wikidata_property=None,
        wikidata_type="Q515",
        search_query_template="distance between {Capital_From} and {Capital_To}",
        min_value=1,
        max_value=20038,
        ambiguous_interpretations=["road"],
        extra_columns=[],
        reasoning="тест",
    )
    plan = output.to_plan()
    assert plan.input_columns == {"from": "Capital_From", "to": "Capital_To"}
    assert plan.bounds.min_value == 1
    assert plan.bounds.max_value == 20038
