"""Граф обробки одного рядка на LangGraph.

Граф описує саме рядок, а не файл: у ньому є справжній цикл, заради
якого фреймворк і брали. Валідатор може повернути роботу досліднику, і
той піде іншим інструментом. Рядки виконуються паралельно, кожен зі
своїм `thread_id`.

Вузол `writer` тут формує підсумок по рядку. Фізичний запис книги
робиться одним потоком після пулу, бо openpyxl не є потокобезпечним.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Literal, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from .config import DISAGREEMENT_THRESHOLD, MAX_TOOL_ATTEMPTS
from .models import RowResult
from .tools import FALLBACK_CHAIN, ToolContext, ToolOutcome, run_tool
from .validator import ValidationError, validate

logger = logging.getLogger(__name__)


class RowState(TypedDict, total=False):
    """Стан обробки одного рядка."""

    row: dict[str, Any]
    row_index: int
    attempt: int
    tools_tried: list[str]
    outcome: dict[str, Any]
    validated_value: Any
    status: str
    message: str
    messages: list[str]
    statuses: list[str]
    result: dict[str, Any]


def build_graph(context: ToolContext):
    """Збирає і компілює граф під конкретний план прогону."""

    def researcher(state: RowState) -> RowState:
        """Обирає інструмент і намагається дістати значення."""
        tried = state.get("tools_tried", [])
        tool_name = _next_tool(context.plan.tool, tried)
        if tool_name is None:
            return {
                "outcome": ToolOutcome(message="Інструменти вичерпано").__dict__,
                "tools_tried": tried,
                "attempt": state.get("attempt", 0) + 1,
            }
        outcome = run_tool(tool_name, state["row"], context)
        outcome.message = f"[{tool_name}] {outcome.message}"
        return {
            "outcome": {**outcome.__dict__, "tool": tool_name},
            "tools_tried": [*tried, tool_name],
            "attempt": state.get("attempt", 0) + 1,
        }

    def validator(state: RowState) -> RowState:
        """Перевіряє тип, одиниці і межі, потім за потреби шукає підтвердження.

        Повідомлення кожної спроби накопичуються: якщо перший інструмент
        дав значення поза межами, а другий нічого не знайшов, у лог мають
        потрапити обидві причини, а не лише остання.
        """
        outcome = state["outcome"]
        history = list(state.get("messages", []))

        statuses = list(state.get("statuses", []))

        if not outcome.get("found"):
            history.append(outcome.get("message", ""))
            failure = {
                "network": "network_error",
                "api_key": "api_key_error",
            }.get(outcome.get("error_kind", ""), "not_found")
            return {
                "status": failure,
                "message": "",
                "messages": history,
                "statuses": [*statuses, failure],
            }

        try:
            value = validate(outcome["value"], context.plan, outcome.get("unit"))
        except ValidationError as error:
            history.append(f"{outcome.get('message', '')}: {error}")
            return {
                "status": "out_of_bounds",
                "message": "",
                "messages": history,
                "statuses": [*statuses, "out_of_bounds"],
            }

        status, message = _cross_check(value, outcome, state["row"], context)
        history.append(message)
        return {
            "validated_value": value,
            "status": status,
            "message": message,
            "messages": history,
            "statuses": [*statuses, status],
        }

    def writer(state: RowState) -> RowState:
        """Складає підсумок по рядку для аркуша enrichment_log."""
        outcome = state.get("outcome", {})
        status = _final_status(state)
        value = state.get("validated_value") if status in ("ok", "ambiguous") else None
        result = RowResult(
            row_index=state["row_index"],
            target_column=context.plan.target_column,
            value=value,
            unit=context.plan.unit,
            tool=outcome.get("tool", ""),
            source_url=outcome.get("source_url", ""),
            query=outcome.get("query", ""),
            confidence_level=outcome.get("confidence_level", 0),
            status=status,
            message=" | ".join(filter(None, state.get("messages", []))),
            llm_calls=outcome.get("llm_calls", 0),
            extra_values=outcome.get("extra_values", {}) if value is not None else {},
        )
        return {"result": result.model_dump()}

    def route(state: RowState) -> Literal["retry", "done"]:
        """Невдача це привід спробувати інший інструмент, поки є спроби."""
        if state.get("status") in ("ok", "ambiguous"):
            return "done"
        if state.get("attempt", 0) >= MAX_TOOL_ATTEMPTS:
            return "done"
        if _next_tool(context.plan.tool, state.get("tools_tried", [])) is None:
            return "done"
        return "retry"

    builder = StateGraph(RowState)
    builder.add_node("researcher", researcher)
    builder.add_node("validator", validator)
    builder.add_node("writer", writer)
    builder.add_edge(START, "researcher")
    builder.add_edge("researcher", "validator")
    builder.add_conditional_edges(
        "validator", route, {"retry": "researcher", "done": "writer"}
    )
    builder.add_edge("writer", END)
    return builder.compile(checkpointer=MemorySaver())


def _final_status(state: RowState) -> str:
    """Підсумковий статус рядка.

    Якщо значення так і не знайдено, показуємо найінформативнішу причину:
    «поза межами» пояснює більше, ніж «не знайдено» від наступної спроби.
    """
    status = state.get("status", "not_found")
    if status in ("ok", "ambiguous"):
        return status
    history = state.get("statuses", [])
    for informative in ("network_error", "api_key_error", "out_of_bounds", "unconfirmed"):
        if informative in history:
            return informative
    return status


def _next_tool(primary: str, tried: list[str]) -> str | None:
    """Основний інструмент, далі ланцюжок відкату, без повторів."""
    for candidate in [primary, *FALLBACK_CHAIN.get(primary, [])]:
        if candidate not in tried:
            return candidate
    return None


def _cross_check(
    value: Any, outcome: dict[str, Any], row: dict[str, Any], context: ToolContext
) -> tuple[str, str]:
    """Політика достовірності за рівнем джерела.

    Рівень 1 (структуроване джерело або розрахунок) приймається одразу.
    Рівень 2 (пошукова видача) перевіряється другим джерелом. Рівень 3
    (пам'ять моделі) без зовнішнього підтвердження не приймається.
    """
    level = outcome.get("confidence_level", 0)
    base_message = outcome.get("message", "")
    if level == 1:
        return "ok", base_message
    if context.llm is None:
        if level >= 3:
            return "unconfirmed", f"{base_message}; підтвердити нічим"
        return "ok", base_message

    check_tool = "llm_knowledge" if level == 2 else "web_search_extract"
    control = run_tool(check_tool, row, context)
    if not control.found or control.value is None:
        if level >= 3:
            return "unconfirmed", f"{base_message}; підтвердження не знайдено"
        return "ok", f"{base_message}; контрольне джерело мовчить"

    try:
        control_value = validate(control.value, context.plan, None)
    except ValidationError as error:
        return "ok", f"{base_message}; контрольне значення відкинуто ({error})"

    if _differs(value, control_value):
        return (
            "ambiguous",
            f"{base_message}; розбіжність джерел: {value} проти {control_value} "
            f"({check_tool})",
        )
    return "ok", f"{base_message}; підтверджено через {check_tool}"


def _differs(first: Any, second: Any) -> bool:
    """Розбіжність понад поріг. Для нечислових значень порівняння точне."""
    if isinstance(first, (int, float)) and isinstance(second, (int, float)):
        if first == 0:
            return second != 0
        return abs(first - second) / abs(first) > DISAGREEMENT_THRESHOLD
    return str(first).strip().lower() != str(second).strip().lower()
