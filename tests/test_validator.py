"""Валідація значення: тип, одиниці, межі, дати.

Це останній бар'єр перед записом у файл, тому перевіряється найдрібніше.
"""

from __future__ import annotations

from datetime import date

import pytest

from src.models import EnrichmentPlan, ValidationBounds
from src.validator import ValidationError, validate


def test_приймає_число_в_межах(height_plan):
    assert validate(8848.86, height_plan) == 8848.86


def test_витягає_число_з_тексту(height_plan):
    """Джерела часто повертають «8 848 m», а не голе число."""
    assert validate("8848 m above sea level", height_plan) == 8848.0


def test_відкидає_значення_вище_межі(height_plan):
    """Олімп на Марсі має 21229 метрів, і це не гора на Землі."""
    with pytest.raises(ValidationError, match="верхню межу"):
        validate(21229, height_plan)


def test_відкидає_значення_нижче_межі(height_plan):
    with pytest.raises(ValidationError, match="нижню межу"):
        validate(4, height_plan)


def test_порожнє_значення_не_проходить(height_plan):
    with pytest.raises(ValidationError):
        validate(None, height_plan)


def test_текст_без_числа_не_проходить(height_plan):
    with pytest.raises(ValidationError, match="немає числа"):
        validate("висока гора", height_plan)


@pytest.mark.parametrize(
    "source_unit, value, expected",
    [
        ("ft", 1000, 304.8),
        ("feet", 1000, 304.8),
        ("футів", 1000, 304.8),
        ("m", 1000, 1000.0),
        ("meters", 1000, 1000.0),
        ("метри", 1000, 1000.0),
    ],
)
def test_переводить_одиниці(height_plan, source_unit, value, expected):
    """Планувальник пише одиниці як завгодно: m, meters, метри."""
    assert validate(value, height_plan, source_unit) == expected


def test_невідомі_одиниці_дають_зрозумілу_помилку(height_plan):
    with pytest.raises(ValidationError, match="не вмію переводити|Не вмію"):
        validate(100, height_plan, "попугаїв")


def _date_plan() -> EnrichmentPlan:
    return EnrichmentPlan(
        target_column="first_ascent",
        value_type="date",
        tool="web_search_extract",
        search_query_template="first ascent of {Mountain}",
    )


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("29.05.1953", "29.05.1953"),
        ("1953-05-29", "29.05.1953"),
        ("29 May 1953", "29.05.1953"),
        ("1953", "1953"),
    ],
)
def test_дати_зводяться_до_одного_формату(raw, expected):
    assert validate(raw, _date_plan()) == expected


def test_дата_з_майбутнього_не_проходить():
    future = date.today().replace(year=date.today().year + 1)
    with pytest.raises(ValidationError, match="поза межами"):
        validate(future.strftime("%d.%m.%Y"), _date_plan())


def test_дата_до_1850_не_проходить():
    with pytest.raises(ValidationError, match="поза межами"):
        validate("01.01.1700", _date_plan())


def test_нерозпізнана_дата_дає_помилку():
    with pytest.raises(ValidationError, match="Не розпізнано дату"):
        validate("колись навесні", _date_plan())


def test_текстове_значення_приймається_як_є():
    plan = EnrichmentPlan(
        target_column="note",
        value_type="text",
        tool="web_search_extract",
        search_query_template="{Mountain}",
        bounds=ValidationBounds(),
    )
    assert validate("  Гімалаї  ", plan) == "Гімалаї"
