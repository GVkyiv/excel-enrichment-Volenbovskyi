"""Виклики мовної моделі.

Модель відповідає лише за те, що справді потребує розуміння природної
мови: розбір завдання в план і витягання значення з тексту знайдених
сніпетів. Розрахунки і звернення до структурованих джерел робить код.

Модель викликається напряму через OpenAI API, не через OpenRouter:
у ДЗ11 цього ж курсу зафіксовано непередбачуваний час відповіді
безкоштовних маршрутів, від 95 до 1105 секунд на одній комбінації.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, TypeVar

from pydantic import BaseModel

from ..config import (
    LLM_MODEL,
    LLM_PRICE_INPUT,
    LLM_PRICE_OUTPUT,
    OPENAI_API_KEY,
)

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class MissingApiKeyError(RuntimeError):
    """Ключ моделі не заданий. Повідомлення має бути зрозумілим людині."""


class LLMClient:
    """Тонка обгортка: структурований вихід плюс облік токенів і вартості."""

    def __init__(self, model: str = LLM_MODEL, api_key: str | None = OPENAI_API_KEY):
        if not api_key:
            raise MissingApiKeyError(
                "Не задано OPENAI_API_KEY. Створіть файл .env на основі "
                ".env.example і впишіть ключ, або працюйте лише з "
                "детермінованими джерелами (Wikidata, розрахунок за координатами)."
            )
        from openai import OpenAI  # імпорт усередині, щоб модуль вантажився без ключа

        self._client = OpenAI(api_key=api_key)
        self.model = model
        self._lock = threading.Lock()
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0

    @property
    def cost_usd(self) -> float:
        """Оцінка вартості прогону за цінами з налаштувань."""
        return (
            self.input_tokens / 1_000_000 * LLM_PRICE_INPUT
            + self.output_tokens / 1_000_000 * LLM_PRICE_OUTPUT
        )

    def parse(self, system: str, user: str, schema: type[T]) -> T:
        """Структурована відповідь у вигляді моделі Pydantic."""
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        try:
            response = self._client.responses.parse(
                model=self.model, input=messages, text_format=schema
            )
            self._account(response)
            return response.output_parsed
        except (AttributeError, TypeError):  # старіші версії SDK
            completion = self._client.chat.completions.parse(
                model=self.model, messages=messages, response_format=schema
            )
            self._account(completion)
            return completion.choices[0].message.parsed

    def _account(self, response: Any) -> None:
        usage = getattr(response, "usage", None)
        with self._lock:
            self.calls += 1
            if usage is None:
                return
            self.input_tokens += getattr(usage, "input_tokens", 0) or getattr(
                usage, "prompt_tokens", 0
            )
            self.output_tokens += getattr(usage, "output_tokens", 0) or getattr(
                usage, "completion_tokens", 0
            )


class ExtractedValue(BaseModel):
    """Те, що модель має повернути, витягуючи значення з тексту."""

    value: float | str | None
    unit: str | None = None
    source_url: str = ""
    found: bool
    comment: str = ""


EXTRACT_SYSTEM = (
    "Ти витягуєш одне конкретне значення з наведених результатів пошуку. "
    "Відповідай лише тим, що прямо підтверджено текстом. Якщо потрібного "
    "значення в тексті немає, став found=false і не вигадуй число. "
    "Приводь значення до одиниць, які просить завдання."
)

KNOWLEDGE_SYSTEM = (
    "Ти відповідаєш значенням з власних знань. Якщо не впевнений, став "
    "found=false. Не вигадуй правдоподібні числа."
)


def extract_from_snippets(
    client: LLMClient, question: str, unit: str | None, snippets: list[dict[str, str]]
) -> ExtractedValue:
    """Рівень 2: значення з тексту пошукової видачі."""
    rendered = "\n\n".join(
        f"[{index + 1}] {item.get('title', '')}\nURL: {item.get('url', '')}\n"
        f"{item.get('content', '')}"
        for index, item in enumerate(snippets)
    )
    user = (
        f"Питання: {question}\n"
        f"Потрібні одиниці: {unit or 'як у питанні'}\n\n"
        f"Результати пошуку:\n{rendered}"
    )
    return client.parse(EXTRACT_SYSTEM, user, ExtractedValue)


def ask_knowledge(
    client: LLMClient, question: str, unit: str | None
) -> ExtractedValue:
    """Рівень 3: пам'ять моделі. Приймається лише з підтвердженням."""
    user = f"Питання: {question}\nПотрібні одиниці: {unit or 'як у питанні'}"
    return client.parse(KNOWLEDGE_SYSTEM, user, ExtractedValue)
