"""Розпізнавання неоднозначних назв.

Тести побудовані на двох реальних випадках, заміряних під час роботи:
«Annapurna» (масив проти вершини) і «Madrid» (столиця проти тезки).
"""

from __future__ import annotations

from src.config import TYPE_HINT_MIN_SHARE
from src.tools.wikidata import _choose, _pick_value


def _item(value, links, typed=False, extra=None):
    return {"values": [value, *(extra or [])], "links": links, "typed": typed}


def test_annapurna_підказка_типу_виграє():
    """Вершина менш відома за масив, але саме вона потрібна завданню."""
    chosen = _choose(
        {
            "wd:Q159621": _item("7756", 92, typed=False, extra=["8091"]),
            "wd:Q16466024": _item("8091", 26, typed=True),
        }
    )
    assert chosen["value"] == "8091"
    assert chosen["item"] == "wd:Q16466024"


def test_madrid_хибна_підказка_ігнорується():
    """Справжній Мадрид не позначений як Q515, тезка позначений."""
    chosen = _choose(
        {
            "wd:Q2807": _item("Point(-3.7 40.4)", 305, typed=False),
            "wd:Q1934324": _item("Point(-74.2 4.7)", 39, typed=True),
        }
    )
    assert chosen["item"] == "wd:Q2807"


def test_поріг_підказки_типу_саме_між_двома_випадками():
    """13 відсотків це хибна підказка, 28 відсотків правильна."""
    assert 0.13 < TYPE_HINT_MIN_SHARE < 0.28


def test_без_підказки_виграє_найвідоміший():
    chosen = _choose(
        {
            "wd:A": _item("100", 5),
            "wd:B": _item("200", 50),
        }
    )
    assert chosen["value"] == "200"


def test_розбіжність_кандидатів_позначається():
    chosen = _choose({"wd:A": _item("8611", 90), "wd:B": _item("3253", 4)})
    assert chosen["ambiguous"] is True
    assert chosen["alternatives"][0]["value"] == "3253"


def test_близькі_значення_не_вважаються_розбіжністю():
    """Різниця в межах 10 відсотків це уточнення, а не інший об'єкт."""
    chosen = _choose({"wd:A": _item("8848", 90), "wd:B": _item("8849", 4)})
    assert "ambiguous" not in chosen


def test_кілька_значень_беруть_підтверджене_іншим_джерелом():
    value, note = _pick_value(["7756", "8091"], others=["8091"])
    assert value == "8091"
    assert "підтверджене" in note


def test_кілька_значень_без_підтвердження_беруть_перше():
    value, note = _pick_value(["7756", "8091"], others=[])
    assert value == "7756"
    assert "перше" in note
