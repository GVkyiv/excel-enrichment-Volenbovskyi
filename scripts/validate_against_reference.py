"""Звірка результату системи з еталоном викладача.

Точність у рубриці курсу це попадання в ±10 відсотків. Скрипт рахує це
числом, а не на око, і окремо показує рядки, де еталон сам собі
суперечить (детально в README, розділ про звірку).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from openpyxl import load_workbook

TOLERANCE = 0.10


def read_column(path: Path, column: str) -> dict[int, object]:
    """Значення колонки за номером рядка книги."""
    workbook = load_workbook(path, data_only=True)
    sheet = workbook.worksheets[0]
    headers = [
        str(cell.value).strip() if cell.value is not None else "" for cell in sheet[1]
    ]
    if column not in headers:
        raise SystemExit(f"У файлі {path.name} немає колонки «{column}»")
    index = headers.index(column) + 1
    values = {
        row: sheet.cell(row=row, column=index).value
        for row in range(2, sheet.max_row + 1)
    }
    workbook.close()
    return values


def compare(
    result_path: Path, reference_path: Path, column: str, alt_column: str | None = None
) -> int:
    result = read_column(result_path, column)
    reference = read_column(reference_path, column)
    alternative = read_column(result_path, alt_column) if alt_column else {}

    matched = checked = matched_any = 0
    print(f"\nЗвірка «{column}»: {result_path.name} проти {reference_path.name}")
    print(f"{'рядок':>6} {'еталон':>10} {'наше':>10} {'відхилення':>12}  вердикт")
    for row, expected in reference.items():
        if expected is None:
            continue
        actual = result.get(row)
        checked += 1
        if actual is None:
            print(f"{row:>6} {expected:>10} {'немає':>10} {'':>12}  не заповнено")
            continue
        try:
            deviation = (float(actual) - float(expected)) / float(expected)
        except (TypeError, ValueError):
            verdict = "збіг" if str(actual) == str(expected) else "різниця"
            matched += verdict == "збіг"
            print(f"{row:>6} {expected:>10} {actual:>10} {'':>12}  {verdict}")
            continue
        ok = abs(deviation) <= TOLERANCE
        matched += ok
        verdict = "у допуску" if ok else "ПОЗА ДОПУСКОМ"

        alt_value = alternative.get(row)
        if not ok and alt_value is not None:
            alt_deviation = (float(alt_value) - float(expected)) / float(expected)
            if abs(alt_deviation) <= TOLERANCE:
                verdict += f", але «{alt_column}» = {float(alt_value):.0f} збігається"
                matched_any += 1
        matched_any += ok

        print(
            f"{row:>6} {float(expected):>10.0f} {float(actual):>10.0f} "
            f"{deviation * 100:>11.1f}%  {verdict}"
        )

    share = matched / checked * 100 if checked else 0.0
    print(f"\nУ допуску ±10% по колонці «{column}»: {matched} з {checked} ({share:.0f}%)")
    if alt_column:
        share_any = matched_any / checked * 100 if checked else 0.0
        print(
            f"Збігається хоч одне з двох трактувань «{column}» або «{alt_column}»: "
            f"{matched_any} з {checked} ({share_any:.0f}%)"
        )
    return matched


def main() -> int:
    parser = argparse.ArgumentParser(description="Звірка з еталоном викладача")
    parser.add_argument("result", help="Файл, який зробила система")
    parser.add_argument("reference", help="Еталонний файл викладача")
    parser.add_argument("column", help="Колонка для порівняння")
    parser.add_argument(
        "--alt",
        help="Додаткова колонка з іншим трактуванням, наприклад distance_road_km",
    )
    args = parser.parse_args()
    compare(Path(args.result), Path(args.reference), args.column, args.alt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
