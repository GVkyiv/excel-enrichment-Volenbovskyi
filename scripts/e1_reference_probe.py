"""Замір E1: чи відтворює модель по пам'яті еталон викладача.

Гіпотеза, яку перевіряємо: три розбіжні рядки еталону з'явились тому, що
його дописували мовною моделлю, а не рахували. Якщо модель по пам'яті дає
ті самі числа, це знання варте рядка в README: воно пояснює походження
еталону і підтверджує, що розрахунок у системі має бути кодом, а не
відповіддю моделі.

Запуск: py scripts\\e1_reference_probe.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.tools.llm import LLMClient  # noqa: E402

PAIRS = [
    ("Kyiv", "Paris", 2500, 2023),
    ("London", "Rome", 1435, 1434),
    ("Paris", "Berlin", 878, 876),
    ("Berlin", "Vienna", 779, 524),
    ("Warsaw", "Kyiv", 688, 689),
    ("Rome", "Madrid", 1363, 1363),
    ("Madrid", "Lisbon", 502, 503),
    ("Vienna", "Budapest", 243, 214),
    ("Stockholm", "Oslo", 416, 417),
    ("Athens", "Istanbul", 563, 561),
]

TOLERANCE = 0.10


class Distance(BaseModel):
    capital_from: str
    capital_to: str
    km: float


class Distances(BaseModel):
    items: list[Distance]


SYSTEM = (
    "Ти заповнюєш колонку таблиці. Відповідай числами з власних знань, "
    "без пошуку і без застережень."
)


def main() -> int:
    client = LLMClient()
    user = "Пряма відстань між столицями в кілометрах:\n" + "\n".join(
        f"{first} - {second}" for first, second, _, _ in PAIRS
    )
    answer = client.parse(SYSTEM, user, Distances)
    by_pair = {
        (item.capital_from.strip(), item.capital_to.strip()): item.km
        for item in answer.items
    }

    print(f"\nМодель: {client.model}, викликів: {client.calls}")
    print(
        f"{'пара':>22} {'еталон':>8} {'модель':>8} {'формула':>9}"
        f"  {'модель=еталон':>14}  {'формула=еталон':>14}"
    )
    like_reference = like_formula = 0
    for first, second, reference, formula in PAIRS:
        model_value = by_pair.get((first, second))
        if model_value is None:
            print(f"{first + '-' + second:>22} {reference:>8} {'немає':>8}")
            continue
        close_to_reference = abs(model_value - reference) / reference <= TOLERANCE
        close_to_formula = abs(formula - reference) / reference <= TOLERANCE
        like_reference += close_to_reference
        like_formula += close_to_formula
        print(
            f"{first + '-' + second:>22} {reference:>8} {model_value:>8.0f} "
            f"{formula:>9} {'так' if close_to_reference else 'ні':>14}"
            f" {'так' if close_to_formula else 'ні':>14}"
        )

    total = len(PAIRS)
    print(f"\nМодель по пам'яті збіглася з еталоном у {like_reference} з {total}")
    print(f"Розрахунок за координатами збігся з еталоном у {like_formula} з {total}")
    print(
        f"Токенів: вхід {client.input_tokens}, вихід {client.output_tokens}; "
        f"вартість за цінами з .env: {client.cost_usd:.4f} USD"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
