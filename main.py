"""Командний інтерфейс системи.

Приклади:
    py main.py capitals
    py main.py mountains
    py main.py --file Data/Input/capitals.xlsx --task "знайди населення міста" \
        --target population
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from src.config import INPUT_DIR
from src.pipeline import process_excel

# Готові завдання з умови курсу, щоб не набирати їх щоразу руками.
# План не задається навмисно: його щоразу будує модель, і саме це є
# предметом перевірки. Готовий план можна підставити прапорцем --plan,
# коли потрібен прогін без жодного звернення до моделі.
PRESETS = {
    "capitals": {
        "file": INPUT_DIR / "capitals.xlsx",
        "task": "знайди пряму відстань між столицями в км для колонки distance",
    },
    "mountains": {
        "file": INPUT_DIR / "mountains.xlsx",
        "task": "додай висоту гір у метрах до колонки height",
    },
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Збагачення Excel-даних з інтернету")
    parser.add_argument("preset", nargs="?", choices=sorted(PRESETS), help="Готовий набір")
    parser.add_argument("--file", help="Шлях до xlsx")
    parser.add_argument("--task", help="Завдання природною мовою")
    parser.add_argument("--plan", help="Готовий план json (без виклику моделі)")
    parser.add_argument("--output", help="Куди зберегти результат")
    parser.add_argument("--workers", type=int, default=8, help="Потоків на рядки")
    parser.add_argument("--overwrite", action="store_true", help="Перезаписувати заповнені комірки")
    parser.add_argument("--no-road", action="store_true", help="Не рахувати відстань дорогами")
    parser.add_argument("--verbose", action="store_true", help="Докладний лог")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if args.preset:
        preset = PRESETS[args.preset]
        file_path = Path(args.file) if args.file else preset["file"]
        task = args.task or preset["task"]
        plan_path = Path(args.plan) if args.plan else None
    else:
        if not args.file or not args.task:
            parser.error("Задайте або готовий набір, або --file разом із --task")
        file_path, task = Path(args.file), args.task
        plan_path = Path(args.plan) if args.plan else None

    process_excel(
        file_path=file_path,
        task_description=task,
        overwrite=args.overwrite,
        max_workers=args.workers,
        road_mode=not args.no_road,
        plan_path=plan_path,
        output_path=args.output,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
