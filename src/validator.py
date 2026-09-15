"""Валідація знайденого значення.

Перевірка йде кодом і в фіксованому порядку: тип, одиниці, межі
правдоподібності. Значення, яке не пройшло перевірку, не потрапляє у файл
навіть якщо джерело здавалось надійним.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from .models import EnrichmentPlan

# Множники приведення до одиниць, які просить завдання.
UNIT_FACTORS: dict[tuple[str, str], float] = {
    ("mi", "km"): 1.609344,
    ("miles", "km"): 1.609344,
    ("m", "km"): 0.001,
    ("km", "m"): 1000.0,
    ("ft", "m"): 0.3048,
    ("feet", "m"): 0.3048,
}

DATE_PATTERNS = ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y", "%d %B %Y", "%B %d, %Y")

MIN_YEAR = 1850


class ValidationError(ValueError):
    """Значення не пройшло перевірку. Текст іде в лог як є."""


def validate(value: object, plan: EnrichmentPlan, source_unit: str | None = None):
    """Повертає приведене значення або кидає `ValidationError`."""
    if value is None:
        raise ValidationError("Порожнє значення")

    if plan.value_type == "number":
        return _validate_number(value, plan, source_unit)
    if plan.value_type == "date":
        return _validate_date(value)
    text = str(value).strip()
    if not text:
        raise ValidationError("Порожній текст")
    return text


def _validate_number(value: object, plan: EnrichmentPlan, source_unit: str | None):
    number = _to_number(value)
    number = _convert_units(number, source_unit, plan.unit)

    bounds = plan.bounds
    if bounds.min_value is not None and number < bounds.min_value:
        raise ValidationError(
            f"Значення {number:g} менше за нижню межу {bounds.min_value:g}"
        )
    if bounds.max_value is not None and number > bounds.max_value:
        raise ValidationError(
            f"Значення {number:g} більше за верхню межу {bounds.max_value:g}"
        )
    return round(number, 2)


def _to_number(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(" ", " ").replace(",", "").strip()
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if match is None:
        raise ValidationError(f"У значенні «{value}» немає числа")
    return float(match.group())


def _convert_units(number: float, source_unit: str | None, target_unit: str | None):
    if not source_unit or not target_unit:
        return number
    source = source_unit.strip().lower()
    target = target_unit.strip().lower()
    if source == target:
        return number
    factor = UNIT_FACTORS.get((source, target))
    if factor is None:
        raise ValidationError(f"Не вмію переводити {source_unit} у {target_unit}")
    return number * factor


def _validate_date(value: object) -> str:
    """Дата у вигляді тексту ДД.ММ.РРРР. Рік без дня теж приймається."""
    text = str(value).strip()
    for pattern in DATE_PATTERNS:
        try:
            parsed = datetime.strptime(text, pattern).date()
        except ValueError:
            continue
        _check_date_range(parsed)
        return parsed.strftime("%d.%m.%Y")

    year_match = re.fullmatch(r"(1[89]\d{2}|20\d{2})", text)
    if year_match:
        year = int(year_match.group())
        if not MIN_YEAR <= year <= date.today().year:
            raise ValidationError(f"Рік {year} поза межами {MIN_YEAR} до сьогодні")
        return str(year)

    raise ValidationError(f"Не розпізнано дату: «{value}»")


def _check_date_range(parsed: date) -> None:
    if parsed.year < MIN_YEAR or parsed > date.today():
        raise ValidationError(
            f"Дата {parsed.isoformat()} поза межами {MIN_YEAR} до сьогодні"
        )
