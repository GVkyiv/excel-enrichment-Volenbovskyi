"""Головний сценарій: process_excel.

Порядок роботи: читання книги, один виклик планувальника на файл,
пакетне отримання даних для всіх рядків одразу, паралельна обробка рядків
графом, запис книги одним потоком.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from tqdm import tqdm

from .cache import Cache
from .config import MAX_WORKERS, OUTPUT_DIR, PLANS_DIR
from .excel_io import ExcelTable, write_enriched
from .graph import build_graph
from .models import EnrichmentPlan, EnrichmentReport, RowResult
from .planner import build_plan, load_plan, save_plan, validate_plan
from .tools import ToolContext
from .tools import wikidata
from .tools.llm import LLMClient, MissingApiKeyError

logger = logging.getLogger(__name__)


def process_excel(
    file_path: str | Path,
    task_description: str,
    overwrite: bool = False,
    max_workers: int = MAX_WORKERS,
    road_mode: bool = True,
    plan_path: str | Path | None = None,
    output_path: str | Path | None = None,
    show_progress: bool = True,
) -> EnrichmentReport:
    """Збагачує таблицю даними з інтернету і зберігає новий файл.

    Аргументи:
        file_path: вхідний xlsx.
        task_description: завдання природною мовою.
        overwrite: чи перезаписувати вже заповнені комірки (за
            замовчуванням ні, оригінальні дані недоторканні).
        max_workers: скільки рядків обробляти паралельно.
        road_mode: чи рахувати додаткову колонку з відстанню дорогами,
            коли план визнав завдання неоднозначним.
        plan_path: готовий план у json. Якщо заданий і файл існує, модель
            не викликається зовсім; інакше план будується моделлю і
            зберігається за цим шляхом.
        output_path: куди зберегти результат.

    Повертає звіт із лічильниками і списком результатів по рядках.
    """
    started = time.monotonic()
    file_path = Path(file_path)
    table = ExcelTable(file_path)
    cache = Cache()

    llm = _make_llm()
    plan = _resolve_plan(plan_path, file_path, task_description, table, llm)
    validate_plan(plan, table.headers)

    context = ToolContext(cache=cache, plan=plan, llm=llm, road_mode=road_mode)
    try:
        _prefetch(table, plan, context)
    except Exception as error:
        # Пакетний запит це оптимізація, а не обов'язковий крок: якщо
        # джерело недоступне, рядки підуть звичайним шляхом і кожен
        # поверне власну зрозумілу причину, а не аварію всього прогону.
        logger.warning(
            "Пакетне попереднє завантаження не вдалося (%s), рядки обробляються поодинці",
            error,
        )

    report = EnrichmentReport(
        file_path=str(file_path), task_description=task_description, plan=plan
    )
    graph = build_graph(context)

    pending: list[dict[str, Any]] = []
    for row in table.rows:
        skip = _skip_reason(row, plan, overwrite)
        if skip is None:
            pending.append(row)
            continue
        report.rows.append(
            RowResult(
                row_index=row["__row__"],
                target_column=plan.target_column,
                status=skip[0],
                message=skip[1],
            )
        )

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(_process_row, graph, row, plan): row for row in pending
        }
        iterator = as_completed(futures)
        if show_progress:
            iterator = tqdm(iterator, total=len(futures), desc="Рядки", unit="рядок")
        for future in iterator:
            report.rows.append(future.result())

    report.rows.sort(key=lambda item: item.row_index)
    output = Path(output_path) if output_path else _default_output(file_path)
    # Додаткову колонку створюємо лише тоді, коли в ній справді є значення:
    # порожня колонка в результаті це сміття, а не збереження структури.
    used_extras = sorted(
        {
            name
            for row in report.rows
            for name, value in row.extra_values.items()
            if value is not None
        }
    )
    write_enriched(file_path, output, report, plan.target_column, used_extras)

    _finalize(report, output, cache, llm, started)
    cache.close()
    for line in report.summary_lines():
        print(line)
    return report


def _process_row(graph, row: dict[str, Any], plan: EnrichmentPlan) -> RowResult:
    """Один рядок через граф. У кожного рядка власний thread_id."""
    started = time.monotonic()
    state = graph.invoke(
        {"row": row, "row_index": row["__row__"], "attempt": 0, "tools_tried": []},
        config={"configurable": {"thread_id": f"row-{row['__row__']}"}},
    )
    result = RowResult.model_validate(state["result"])
    result.duration_ms = int((time.monotonic() - started) * 1000)
    return result


def _make_llm() -> LLMClient | None:
    """Модель необов'язкова: без ключа працюють детерміновані джерела."""
    try:
        return LLMClient()
    except MissingApiKeyError as error:
        logger.warning("%s", error)
        return None


def _resolve_plan(
    plan_path: str | Path | None,
    file_path: Path,
    task_description: str,
    table: ExcelTable,
    llm: LLMClient | None,
) -> EnrichmentPlan:
    """Готовий план або один виклик моделі на файл."""
    if plan_path and Path(plan_path).exists():
        logger.info("Використано збережений план: %s", plan_path)
        return load_plan(plan_path)
    if llm is None:
        raise MissingApiKeyError(
            "Немає ні збереженого плану, ні ключа моделі. Задайте "
            "OPENAI_API_KEY у .env або передайте plan_path із готовим планом."
        )
    plan = build_plan(llm, task_description, table.headers, table.sample())
    target = Path(plan_path) if plan_path else PLANS_DIR / f"{file_path.stem}.json"
    save_plan(plan, target)
    return plan


def _prefetch(table: ExcelTable, plan: EnrichmentPlan, context: ToolContext) -> None:
    """Пакетне отримання даних для всіх рядків одразу.

    Саме цей крок робить систему придатною для тисячі рядків: замість
    тисячі звернень до Wikidata виходять одиниці запитів.
    """
    if plan.tool == "geo_distance":
        labels: list[str] = []
        for argument in ("from", "to"):
            column = plan.input_columns.get(argument)
            if column:
                labels += [str(row[column]) for row in table.rows if row.get(column)]
        context.coordinates = wikidata.coordinates(labels, context.cache)
        logger.info(
            "Попередньо отримано координати: %s з %s унікальних назв",
            len(context.coordinates),
            len(set(labels)),
        )
    elif plan.tool == "wikidata_lookup" and plan.wikidata_property:
        column = plan.input_columns.get("entity")
        labels = [str(row[column]) for row in table.rows if column and row.get(column)]
        context.entity_values = wikidata.lookup_property(
            labels, plan.wikidata_property, context.cache
        )
        logger.info(
            "Попередньо отримано значення %s: %s з %s унікальних назв",
            plan.wikidata_property,
            len(context.entity_values),
            len(set(labels)),
        )


def _skip_reason(
    row: dict[str, Any], plan: EnrichmentPlan, overwrite: bool
) -> tuple[str, str] | None:
    """Чи треба пропустити рядок і чому."""
    current = row.get(plan.target_column)
    if current not in (None, "") and not overwrite:
        return "skipped_filled", "Комірка вже заповнена, оригінальні дані не чіпаємо"
    for column in plan.input_columns.values():
        if row.get(column) in (None, ""):
            return (
                "skipped_empty_input",
                f"У рядку порожня вхідна колонка «{column}»",
            )
    return None


def _default_output(file_path: Path) -> Path:
    return OUTPUT_DIR / f"{file_path.stem}_enriched.xlsx"


def _finalize(
    report: EnrichmentReport,
    output: Path,
    cache: Cache,
    llm: LLMClient | None,
    started: float,
) -> None:
    """Заповнює лічильники звіту."""
    from .http_client import http_client

    report.output_path = str(output)
    report.rows_total = len(report.rows)
    report.filled = sum(1 for row in report.rows if row.value is not None)
    report.not_found = sum(
        1 for row in report.rows if row.status in ("not_found", "unconfirmed")
    )
    report.errors = sum(
        1
        for row in report.rows
        if row.status in ("network_error", "out_of_bounds", "api_key_error")
    )
    report.skipped = sum(1 for row in report.rows if row.status.startswith("skipped"))
    report.llm_calls = llm.calls if llm else 0
    report.cost_usd = llm.cost_usd if llm else 0.0
    report.network_calls = http_client.calls
    report.cache_hits = cache.hits
    report.duration_s = time.monotonic() - started
