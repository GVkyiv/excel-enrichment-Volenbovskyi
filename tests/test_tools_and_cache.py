"""Розрахунки, шаблони запитів і кеш.

Формула відстані перевіряється на парах, для яких відома правильна
відповідь, тому цей тест ловить помилку в математиці незалежно від того,
що відповідає Wikidata.
"""

from __future__ import annotations

import pytest

from src.cache import Cache
from src.tools import render_template
from src.tools.geo import haversine_km

KYIV = (50.4501, 30.5234)
PARIS = (48.8566, 2.3522)
VIENNA = (48.2082, 16.3738)
BUDAPEST = (47.4979, 19.0402)


@pytest.mark.parametrize(
    "point_from, point_to, expected",
    [
        (KYIV, PARIS, 2023),
        (VIENNA, BUDAPEST, 214),
    ],
)
def test_відстань_по_великому_колу(point_from, point_to, expected):
    assert round(haversine_km(point_from, point_to)) == pytest.approx(expected, abs=2)


def test_відстань_до_самої_себе_нульова():
    assert haversine_km(KYIV, KYIV) == pytest.approx(0, abs=0.001)


def test_відстань_симетрична():
    assert haversine_km(KYIV, PARIS) == pytest.approx(haversine_km(PARIS, KYIV))


def test_шаблон_підставляє_значення_колонок():
    query = render_template(
        "distance between {Capital_From} and {Capital_To} in km",
        {"Capital_From": "Kyiv", "Capital_To": "Paris"},
    )
    assert query == "distance between Kyiv and Paris in km"


def test_відсутня_колонка_не_валить_шаблон():
    """Порожнє місце видно в логу за самим запитом, і це краще за аварію."""
    query = render_template("height of {Mountain} in {Country}", {"Mountain": "K2"})
    assert query == "height of K2 in"


def test_кеш_повертає_збережене(tmp_path):
    cache = Cache(tmp_path / "c.sqlite")
    cache.set("wikidata", "P2044|Everest", {"value": "8848"})
    assert cache.get("wikidata", "P2044|Everest") == {"value": "8848"}
    cache.close()


def test_кеш_нормалізує_ключ(tmp_path):
    """«Kyiv » і «kyiv» це той самий запит, а не два різних."""
    cache = Cache(tmp_path / "c.sqlite")
    cache.set("search", "Height of  K2", [1])
    assert cache.get("search", "height of k2") == [1]
    cache.close()


def test_кеш_відрізняє_порожню_відповідь_від_відсутньої(tmp_path):
    """Порожній словник означає «шукали, не знайшли», None означає «не шукали»."""
    cache = Cache(tmp_path / "c.sqlite")
    cache.set("wikidata", "P2044|Atlantis", {})
    assert cache.get("wikidata", "P2044|Atlantis") == {}
    assert cache.get("wikidata", "P2044|Невідоме") is None
    cache.close()


def test_кеш_рахує_влучання(tmp_path):
    cache = Cache(tmp_path / "c.sqlite")
    cache.set("osrm", "a;b", 244)
    cache.get("osrm", "a;b")
    cache.get("osrm", "немає")
    assert (cache.hits, cache.misses) == (1, 1)
    cache.close()
