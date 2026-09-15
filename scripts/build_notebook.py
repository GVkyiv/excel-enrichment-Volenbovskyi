"""Збирає і виконує ноутбук-демонстрацію.

Ноутбук на здачу має містити збережені виводи комірок, тому він не
пишеться руками, а збирається з цього файлу і одразу виконується. Так
виводи в ноутбуці гарантовано відповідають поточному коду, а не
залишкам від давнього прогону.

Запуск: py scripts\\build_notebook.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import nbformat
from nbclient import NotebookClient

ROOT = Path(__file__).resolve().parent.parent
NOTEBOOK = ROOT / "notebooks" / "ВоленбовськийГВ_демонстрація.ipynb"

CELLS: list[tuple[str, str]] = [
    (
        "markdown",
        "# Інтелектуальне збагачення Excel-даних\n\n"
        "Фінальний проєкт курсу «Генеративний та агентний ШІ».\n"
        "Автор: Геннадій Воленбовський.\n\n"
        "Система приймає Excel-файл і завдання природною мовою, сама визначає,\n"
        "яких даних бракує, знаходить їх у відкритих джерелах і дописує колонки.\n\n"
        "Порядок демонстрації: два завдання з умови курсу, потім два додаткові,\n"
        "щоб показати роботу без жодної зміни коду, потім обробка помилок,\n"
        "масштабованість і звірка з еталоном викладача.",
    ),
    (
        "code",
        "import logging, sys\n"
        "from pathlib import Path\n\n"
        "sys.path.insert(0, str(Path.cwd().parent))\n"
        "logging.basicConfig(level=logging.WARNING, format='%(levelname)s %(message)s')\n\n"
        "from src import process_excel\n"
        "from scripts.validate_against_reference import compare, detect_alt_column\n\n"
        "DATA = Path.cwd().parent / 'Data'\n"
        "print('готово')",
    ),
    (
        "markdown",
        "## Завдання 1. Пряма відстань між столицями\n\n"
        "План будує модель: вона сама обирає інструмент, вказує тип сутності\n"
        "для розпізнавання назв і межі правдоподібності. Тут вона ще й помічає,\n"
        "що поняття відстані має два трактування, і додає окрему колонку для\n"
        "відстані дорогами.",
    ),
    (
        "code",
        "report = process_excel(\n"
        "    file_path=DATA / 'Input' / 'capitals.xlsx',\n"
        "    task_description='знайди пряму відстань між столицями в км для колонки distance',\n"
        "    show_progress=False,\n"
        ")",
    ),
    (
        "code",
        "print(report.plan.model_dump_json(indent=2, exclude={'reasoning'}))\n"
        "print('\\nЧому саме так:', report.plan.reasoning)",
    ),
    (
        "markdown",
        "### Звірка з еталоном викладача\n\n"
        "Еталон по столицях внутрішньо суперечливий: сім рядків це пряма\n"
        "відстань, два це відстань дорогами, один не збігається ні з чим.\n"
        "Тому нижче видно і те, як збігається основна колонка, і те, як\n"
        "виглядає картина з урахуванням другого трактування.",
    ),
    (
        "code",
        "result = Path(report.output_path)\n"
        "reference = DATA / 'Reference' / 'capitals_enriched.xlsx'\n"
        "compare(result, reference, 'distance', detect_alt_column(result, reference));",
    ),
    (
        "markdown",
        "## Завдання 2. Висота гір\n\n"
        "Те саме, але значення бере структуроване джерело Wikidata.\n"
        "Зверніть увагу на рядок K2 у логу: назва неоднозначна, система\n"
        "позначила це і звернулась по підтвердження.",
    ),
    (
        "code",
        "report = process_excel(\n"
        "    file_path=DATA / 'Input' / 'mountains.xlsx',\n"
        "    task_description='додай висоту гір у метрах до колонки height',\n"
        "    show_progress=False,\n"
        ")",
    ),
    (
        "code",
        "for row in report.rows:\n"
        "    print(f'{row.row_index:>3} {str(row.value):>10}  рівень {row.confidence_level}  {row.status}')\n"
        "    if row.confidence_level > 1:\n"
        "        print('     ', row.message)",
    ),
    (
        "code",
        "result = Path(report.output_path)\n"
        "compare(result, DATA / 'Reference' / 'mountains_enriched.xlsx', 'height');",
    ),
    (
        "markdown",
        "## Завдання 3. Населення міста\n\n"
        "Код не змінювався. Змінився тільки текст завдання, і планувальник\n"
        "сам обрав іншу властивість Wikidata та створив нову колонку.",
    ),
    (
        "code",
        "report = process_excel(\n"
        "    file_path=DATA / 'Input' / 'capitals.xlsx',\n"
        "    task_description='додай населення міста з колонки Capital_From у нову колонку Capital_From_population',\n"
        "    output_path=DATA / 'Output' / 'capitals_population_demo.xlsx',\n"
        "    show_progress=False,\n"
        ")\n"
        "print('\\nІнструмент:', report.plan.tool, report.plan.wikidata_property)",
    ),
    (
        "markdown",
        "## Завдання 4. Дата першого сходження\n\n"
        "Тут структурованого джерела немає, тому працює загальний шлях:\n"
        "пошук в інтернеті плюс витягання значення моделлю. Тип значення не\n"
        "числовий, а дата, тобто допуск ±10 відсотків до нього незастосовний.",
    ),
    (
        "code",
        "report = process_excel(\n"
        "    file_path=DATA / 'Input' / 'mountains.xlsx',\n"
        "    task_description='додай дату першого успішного сходження на гору у форматі ДД.ММ.РРРР до нової колонки first_ascent',\n"
        "    output_path=DATA / 'Output' / 'mountains_first_ascent_demo.xlsx',\n"
        "    show_progress=False,\n"
        ")\n"
        "print('\\nІнструмент:', report.plan.tool)\n"
        "for row in report.rows:\n"
        "    print(f'{str(row.value):>12}  {row.source_url[:70]}')",
    ),
    (
        "markdown",
        "## Обробка помилок\n\n"
        "Файл `broken.xlsx` зібраний навмисно поламаним. Жоден випадок не\n"
        "валить прогін: кожен рядок отримує статус і зрозуміле пояснення,\n"
        "а файл усе одно зберігається.",
    ),
    (
        "code",
        "report = process_excel(\n"
        "    file_path=DATA / 'Input' / 'broken.xlsx',\n"
        "    task_description='додай висоту гір у метрах до колонки height',\n"
        "    show_progress=False,\n"
        ")\n"
        "print()\n"
        "for row in report.rows:\n"
        "    print(f'{row.row_index:>3} {str(row.value):>10}  {row.status}')\n"
        "    print('     ', row.message[:150])",
    ),
    (
        "markdown",
        "## Масштабованість\n\n"
        "Тисяча пар столиць зі ста міст. Координати беруться пакетами, далі\n"
        "працює формула, тому мережевих запитів одиниці, а не тисячі.\n"
        "Дорожній режим вимкнено: публічний OSRM вимагає паузи в секунду між\n"
        "запитами, це обмеження джерела, а не системи.",
    ),
    (
        "code",
        "report = process_excel(\n"
        "    file_path=DATA / 'Input' / 'stress_1000.xlsx',\n"
        "    task_description='знайди пряму відстань між столицями в км для колонки distance',\n"
        "    plan_path=DATA / 'plans' / 'capitals_distance.json',\n"
        "    road_mode=False,\n"
        "    max_workers=16,\n"
        "    show_progress=False,\n"
        ")",
    ),
    (
        "markdown",
        "## Підсумок\n\n"
        "Чотири різні завдання пройшли одним і тим самим кодом: змінювався\n"
        "тільки текст завдання, а план під нього щоразу будувала модель.\n\n"
        "Головне архітектурне рішення проєкту: те, що задається формулою або\n"
        "структурованим джерелом, рахує код, а моделі лишається тільки те, що\n"
        "потребує розуміння природної мови. Тому тисяча рядків коштує два\n"
        "мережевих запити і жодного виклику моделі понад один план на файл.\n\n"
        "Розбіжність з еталоном викладача на трьох рядках розібрана в README:\n"
        "два з них це відстань дорогами, походження третього невідоме.",
    ),
]


def build() -> Path:
    notebook = nbformat.v4.new_notebook()
    notebook.cells = [
        nbformat.v4.new_markdown_cell(source)
        if kind == "markdown"
        else nbformat.v4.new_code_cell(source)
        for kind, source in CELLS
    ]
    notebook.metadata["kernelspec"] = {
        "display_name": "Python 3",
        "language": "python",
        "name": "python3",
    }
    NOTEBOOK.parent.mkdir(parents=True, exist_ok=True)
    nbformat.write(notebook, NOTEBOOK)
    return NOTEBOOK


def execute(path: Path) -> None:
    notebook = nbformat.read(path, as_version=4)
    client = NotebookClient(
        notebook,
        timeout=900,
        kernel_name="python3",
        resources={"metadata": {"path": str(path.parent)}},
    )
    client.execute()
    nbformat.write(notebook, path)


if __name__ == "__main__":
    path = build()
    print("зібрано:", path)
    execute(path)
    print("виконано, виводи збережено")
    sys.exit(0)
