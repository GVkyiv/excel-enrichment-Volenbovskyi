"""Кеш відповідей зовнішніх джерел у sqlite.

Ключ це пара «інструмент плюс нормалізований запит». Повторний прогін не
витрачає ні мережу, ні гроші, а стрес-тест можна чесно поміряти двічі:
на холодному кеші і на теплому.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import CACHE_PATH


class Cache:
    """Потокобезпечна обгортка над sqlite.

    Одне з'єднання із `check_same_thread=False` плюс замок: пул потоків
    працює з кешем інтенсивно, а sqlite не любить паралельний запис.
    """

    def __init__(self, path: Path | str = CACHE_PATH) -> None:
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cache (
                key        TEXT PRIMARY KEY,
                tool       TEXT NOT NULL,
                payload    TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        self._conn.commit()
        self.hits = 0
        self.misses = 0

    @staticmethod
    def make_key(tool: str, query: str) -> str:
        """Нормалізує запит, щоб «Kyiv » і «kyiv» не були різними ключами."""
        return f"{tool}::{' '.join(query.lower().split())}"

    def get(self, tool: str, query: str) -> Any | None:
        key = self.make_key(tool, query)
        with self._lock:
            row = self._conn.execute(
                "SELECT payload FROM cache WHERE key = ?", (key,)
            ).fetchone()
        if row is None:
            self.misses += 1
            return None
        self.hits += 1
        return json.loads(row[0])

    def set(self, tool: str, query: str, payload: Any) -> None:
        key = self.make_key(tool, query)
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO cache (key, tool, payload, created_at)"
                " VALUES (?, ?, ?, ?)",
                (
                    key,
                    tool,
                    json.dumps(payload, ensure_ascii=False),
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                ),
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
