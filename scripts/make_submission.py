"""Готує файли на здачу: копії результатів, підписані прізвищем.

Умова курсу вимагає підписувати файли власним прізвищем. Робочі імена
файлів при цьому лишаються технічними, щоб їх не доводилось міняти в коді
і в ноутбуці.

Запуск: py scripts\\make_submission.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "Data" / "Output"
SUBMISSION = ROOT / "Data" / "Submission"
SURNAME = "ВоленбовськийГВ"

FILES = ["capitals_enriched.xlsx", "mountains_enriched.xlsx"]


def main() -> int:
    SUBMISSION.mkdir(parents=True, exist_ok=True)
    missing = [name for name in FILES if not (OUTPUT / name).exists()]
    if missing:
        print(
            "Немає результатів: " + ", ".join(missing) + ". "
            "Спочатку виконайте py main.py capitals і py main.py mountains."
        )
        return 1

    for name in FILES:
        stem, suffix = name.rsplit(".", 1)
        target = SUBMISSION / f"{stem}_{SURNAME}.{suffix}"
        shutil.copyfile(OUTPUT / name, target)
        print("готово:", target.name)

    notebook = ROOT / "notebooks" / f"{SURNAME}_демонстрація.ipynb"
    print(
        "\nНа платформу здаємо: обидва файли з Data/Submission, "
        f"ноутбук {notebook.name} і архів репозиторію."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
