"""Поведінка графа: цикл відкату, статуси, політика достовірності.

Інструменти підмінені заглушками, тому тести перевіряють саме логіку
графа, а не доступність Wikidata чи пошуку.
"""

from __future__ import annotations

import pytest

from src import tools
from src.graph import build_graph
from src.models import RowResult


@pytest.fixture
def run(context, monkeypatch):
    """Прогін одного рядка через граф із підміненим реєстром інструментів."""

    def _run(registry: dict, row: dict | None = None) -> RowResult:
        monkeypatch.setattr(tools, "REGISTRY", registry)
        graph = build_graph(context)
        state = graph.invoke(
            {
                "row": row or {"Mountain": "Everest", "__row__": 2},
                "row_index": 2,
                "attempt": 0,
                "tools_tried": [],
            },
            config={"configurable": {"thread_id": "test"}},
        )
        return RowResult.model_validate(state["result"])

    return _run


def _outcome(**kwargs) -> tools.ToolOutcome:
    return tools.ToolOutcome(**kwargs)


def test_значення_зі_структурованого_джерела_приймається_одразу(run):
    result = run(
        {
            "wikidata_lookup": lambda row, ctx: _outcome(
                found=True, value=8848, confidence_level=1, message="Wikidata"
            )
        }
    )
    assert result.status == "ok"
    assert result.value == 8848


def test_значення_поза_межами_не_записується(run):
    result = run(
        {
            "wikidata_lookup": lambda row, ctx: _outcome(
                found=True, value=21229, confidence_level=1
            ),
            "web_search_extract": lambda row, ctx: _outcome(found=False),
            "llm_knowledge": lambda row, ctx: _outcome(found=False),
        }
    )
    assert result.value is None
    assert result.status == "out_of_bounds"


def test_відкат_на_інший_інструмент_після_невдачі(run):
    """Перший інструмент мовчить, значення дістає другий."""
    result = run(
        {
            "wikidata_lookup": lambda row, ctx: _outcome(found=False, message="нема"),
            "web_search_extract": lambda row, ctx: _outcome(
                found=True, value=8516, confidence_level=2
            ),
            "llm_knowledge": lambda row, ctx: _outcome(found=True, value=8516),
        }
    )
    assert result.value == 8516
    assert result.tool == "web_search_extract"


def test_причини_всіх_спроб_потрапляють_у_лог(run):
    result = run(
        {
            "wikidata_lookup": lambda row, ctx: _outcome(found=True, value=21229, confidence_level=1),
            "web_search_extract": lambda row, ctx: _outcome(found=False, message="нічого"),
            "llm_knowledge": lambda row, ctx: _outcome(found=False),
        }
    )
    assert "верхню межу" in result.message
    assert "нічого" in result.message


def test_помилка_мережі_дає_власний_статус(run):
    result = run(
        {
            "wikidata_lookup": lambda row, ctx: _outcome(
                found=False, error_kind="network", message="джерело не відповіло"
            ),
            "web_search_extract": lambda row, ctx: _outcome(found=False),
            "llm_knowledge": lambda row, ctx: _outcome(found=False),
        }
    )
    assert result.status == "network_error"


def test_відповідь_моделі_без_підтвердження_не_записується(run, context):
    """Рівень 3 приймається тільки з підтвердженням ззовні."""
    context.llm = object()  # достатньо, щоб гілка перевірки увімкнулась
    context.plan.tool = "llm_knowledge"
    result = run(
        {
            "llm_knowledge": lambda row, ctx: _outcome(
                found=True, value=8000, confidence_level=3
            ),
            "web_search_extract": lambda row, ctx: _outcome(found=False),
        }
    )
    assert result.value is None
    assert result.status == "unconfirmed"


def test_значення_з_пошуку_без_підтвердження_лишається_з_позначкою(run, context):
    """Регресія аудиту: раніше такий рядок мав статус ok."""
    context.llm = object()
    result = run(
        {
            "wikidata_lookup": lambda row, ctx: _outcome(found=False),
            "web_search_extract": lambda row, ctx: _outcome(
                found=True, value=4267, confidence_level=2, source_url="http://example"
            ),
            "llm_knowledge": lambda row, ctx: _outcome(found=False),
        }
    )
    assert result.value == 4267
    assert result.status == "unconfirmed"


def test_розбіжність_джерел_позначається_але_значення_лишається(run, context):
    context.llm = object()
    result = run(
        {
            "wikidata_lookup": lambda row, ctx: _outcome(found=False),
            "web_search_extract": lambda row, ctx: _outcome(
                found=True, value=8000, confidence_level=2
            ),
            "llm_knowledge": lambda row, ctx: _outcome(found=True, value=5000),
        }
    )
    assert result.value == 8000
    assert result.status == "ambiguous"
    assert "розбіжність" in result.message


def test_кількість_спроб_обмежена(run):
    calls = {"count": 0}

    def failing(row, ctx):
        calls["count"] += 1
        return _outcome(found=False)

    run(
        {
            "wikidata_lookup": failing,
            "web_search_extract": failing,
            "llm_knowledge": failing,
        }
    )
    assert calls["count"] <= 2
