"""Случайный исследователь с фиксированным seed.

Нижняя точка сравнения и проверка устойчивости среды: политика намеренно
посылает и неизвестные ID, и неверные лимиты, и мусорные выражения, чтобы
ограниченные ошибки и расход шагов проверялись на практике.

Seed политики отделён от seed эпизода: иначе поведение базовой линии менялось
бы вместе с данными и прогоны стали бы несравнимыми.
"""

from __future__ import annotations

import random

from .base import (
    Policy,
    calculator,
    episode_id_of,
    get_document,
    get_record,
    list_records,
    page_records,
    remaining_steps,
    submit,
)

TABLES = ("ledger", "invoices", "payments", "fx", "policy")

TABLE_ID_FIELD = {
    "ledger": "row_id",
    "invoices": "invoice_id",
    "payments": "payment_id",
    "fx": "fx_id",
    "policy": "policy_id",
}


class RandomExplorer(Policy):
    name = "random"

    def __init__(self, seed: int = 20261122, budget: int = 40) -> None:
        self.seed = seed
        self.budget = budget

    def run(self, observation):
        rng = random.Random(self.seed)
        episode_id = episode_id_of(observation)

        seen_ids: dict[str, list[str]] = {table: [] for table in TABLES}
        seen_docs: list[str] = []

        steps_taken = 0
        while steps_taken < self.budget and remaining_steps(observation) > 1:
            action = self._pick_action(rng, seen_ids, seen_docs)
            observation = yield action
            steps_taken += 1
            self._remember(action, observation, seen_ids, seen_docs)

        # Шаг под submit зарезервирован всегда: усечение на чистой книге дало бы
        # положительный возврат по формуле, и базовая линия выглядела бы лучше,
        # чем она есть.
        yield submit(episode_id, [])

    def _pick_action(self, rng, seen_ids, seen_docs):
        choice = rng.random()
        table = rng.choice(TABLES)

        if choice < 0.45:
            limit = rng.choice([1, 5, 50, 51])  # 51 даёт ограниченную ошибку
            return list_records(table, None, limit)
        if choice < 0.70:
            known = seen_ids.get(table) or []
            record_id = rng.choice(known) if known and rng.random() < 0.7 else "ID-UNKNOWN"
            return get_record(table, record_id)
        if choice < 0.90:
            doc_id = rng.choice(seen_docs) if seen_docs and rng.random() < 0.7 else "D-UNKNOWN"
            return get_document(doc_id)
        expression = rng.choice(
            ["1 + 2", "(3.50 - 1.25) * 4", "10 / 4", "7 / 0", "import os"]
        )
        return calculator(expression)

    def _remember(self, action, observation, seen_ids, seen_docs):
        result = observation.get("result")
        if not isinstance(result, dict):
            return
        rows = page_records(result) or None
        if not isinstance(rows, list):
            return
        table = result.get("table")
        field = TABLE_ID_FIELD.get(table)
        if not field:
            return
        for row in rows:
            value = row.get(field)
            if type(value) is str:
                seen_ids.setdefault(table, []).append(value)
            doc_id = row.get("doc_id")
            if type(doc_id) is str:
                seen_docs.append(doc_id)
