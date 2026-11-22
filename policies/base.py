"""Общий протокол базовых политик.

Политика — генератор: она отдаёт одно JSON-действие и получает следующее
наблюдение через ``send``. Это ровно контракт ``step`` из задания, но код
политики читается линейно, без ручного автомата состояний.

Правила зоны:

- политика видит только наблюдения; ``truth``, ``provenance`` и seed ей
  недоступны;
- oracle здесь не живёт: он собирает заявку на стороне оценщика;
- последний шаг резервируется под ``submit``, иначе эпизод усекается и
  оценивается пустая заявка.
"""

from __future__ import annotations

from typing import Any, Generator, Iterator

#: Сколько шагов политика держит в запасе под submit и финальные уточнения.
STEP_RESERVE = 2

Action = dict[str, Any]
Observation = dict[str, Any]
PolicyRun = Generator[Action, Observation, None]


# --- конструкторы действий ----------------------------------------------------

def list_records(table: str, cursor: str | None = None, limit: int = 50) -> Action:
    action: Action = {"name": "list_records", "table": table, "limit": limit}
    action["cursor"] = cursor
    return action


def get_record(table: str, record_id: str) -> Action:
    return {"name": "get_record", "table": table, "id": record_id}


def get_document(doc_id: str) -> Action:
    return {"name": "get_document", "doc_id": doc_id}


def calculator(expression: str) -> Action:
    return {"name": "calculator", "expression": expression}


def submit(episode_id: str, findings: list[dict]) -> Action:
    return {
        "name": "submit",
        "findings": {"episode_id": episode_id, "findings": findings},
    }


# --- вспомогательное ----------------------------------------------------------

def page_records(result: dict) -> list[dict]:
    """Строки страницы из ответа ``list_records``.

    Протокол жюри называет их ``records``, внутренний плоский вид ядра —
    ``rows``. Политика обязана работать через обе формы: через ``records`` её
    запускает жюри и контейнер изоляции, через ``rows`` — тесты и матрица
    базовых линий. Разбирать это в каждой политике отдельно значило бы, что
    однажды одна из них перестанет видеть данные молча, без падения — ровно
    так и случилось в контейнере, где политика находила ноль расхождений.
    """
    records = result.get("records")
    if isinstance(records, list):
        return records
    rows = result.get("rows")
    return rows if isinstance(rows, list) else []


def remaining_steps(observation: Observation, default: int = 0) -> int:
    value = observation.get("remaining_steps", default)
    return value if type(value) is int else default


def episode_id_of(observation: Observation) -> str:
    manifest = observation.get("manifest") or {}
    return manifest.get("episode_id", "")


def base_currency_of(observation: Observation) -> str:
    manifest = observation.get("manifest") or {}
    return manifest.get("base_currency", "USD")


def currency_exponents_of(observation: Observation) -> dict[str, int]:
    manifest = observation.get("manifest") or {}
    exponents = manifest.get("currency_exponents") or {}
    return {code: int(value) for code, value in exponents.items()}


class Policy:
    """База для базовых политик."""

    name = "policy"

    def run(self, observation: Observation) -> PolicyRun:
        raise NotImplementedError

    # --- общие шаги -----------------------------------------------------------

    def fetch_table(
        self, table: str, observation: Observation, limit: int = 50
    ) -> Iterator[Action]:
        """Постранично собрать таблицу.

        Возвращает ``(rows, observation)``, поэтому вызывается как
        ``rows, obs = yield from self.fetch_table(table, obs)``. Последнее
        наблюдение возвращается вместе со строками: без него вызывающий код не
        знает остаток бюджета и не может решить, хватает ли шагов дальше.

        Останавливается, если бюджет подходит к концу: шаг под ``submit``
        важнее лишней страницы.
        """
        rows: list[dict] = []
        cursor: str | None = None

        while True:
            if remaining_steps(observation) <= STEP_RESERVE:
                return rows, observation
            observation = yield list_records(table, cursor, limit)
            result = observation.get("result")
            if not isinstance(result, dict):
                # Ограниченная ошибка: шаг израсходован, страницу не получили.
                return rows, observation
            rows.extend(page_records(result))
            cursor = result.get("next_cursor")
            if cursor is None:
                return rows, observation

    def fetch_document(
        self, doc_id: str, observation: Observation
    ) -> Iterator[Action]:
        """Получить один публичный документ, если есть бюджет.

        Возвращает ``(document_or_None, observation)``.
        """
        if remaining_steps(observation) <= STEP_RESERVE:
            return None, observation
        observation = yield get_document(doc_id)
        result = observation.get("result")
        return (result if isinstance(result, dict) else None), observation
