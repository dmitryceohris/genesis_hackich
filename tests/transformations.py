"""Безвредные преобразования эпизода для парных проверок.

Жюри прогоняет 20 парных проверок: перестановка порядка и смена ID обязаны
сохранять ответ oracle и награду с учётом новых ID. Здесь две операции:

- ``permute_records`` меняет порядок строк и документов, не меняя сути;
- ``rename_ids`` заменяет все идентификаторы по биекции, включая ссылки внутри
  эталона и правил политики.

Порядок документации не является хозяйственным событием, поэтому перестановка
обязана быть семантически нейтральной. Карта замены остаётся у проверяющего.
"""

from __future__ import annotations

import random
from typing import Any

#: Ключи, значения которых являются публичными или эталонными ID.
ID_KEYS = frozenset(
    {
        "row_id",
        "journal_id",
        "invoice_id",
        "payment_id",
        "doc_id",
        "fx_id",
        "entity_id",
        "line_id",
        "obligation_id",
        "source_doc_id",
        "original_payment_id",
        "policy_id",
        "issue_id",
        "episode_id",
    }
)

#: Ключи со списком ID.
ID_LIST_KEYS = frozenset({"affected_ids", "evidence_ids"})

#: Ключи со списком списков ID.
ID_SET_LIST_KEYS = frozenset({"acceptable_evidence_sets"})

#: Словари, все значения которых — ID правил.
ID_MAP_KEYS = frozenset({"rule_ids"})


def collect_ids(episode: dict) -> list[str]:
    """Все идентификаторы эпизода в детерминированном порядке."""
    found: dict[str, None] = {}

    def walk(node: Any, key: str | None = None) -> None:
        if isinstance(node, dict):
            for child_key, child in node.items():
                walk(child, child_key)
            return
        if isinstance(node, list):
            if key in ID_LIST_KEYS:
                for item in node:
                    if type(item) is str:
                        found[item] = None
                return
            if key in ID_SET_LIST_KEYS:
                for group in node:
                    for item in group or []:
                        if type(item) is str:
                            found[item] = None
                return
            for item in node:
                walk(item, key)
            return
        if type(node) is str and key in ID_KEYS:
            found[node] = None

    def walk_rule_maps(node: Any) -> None:
        if isinstance(node, dict):
            for child_key, child in node.items():
                if child_key in ID_MAP_KEYS and isinstance(child, dict):
                    for value in child.values():
                        if type(value) is str:
                            found[value] = None
                else:
                    walk_rule_maps(child)
        elif isinstance(node, list):
            for item in node:
                walk_rule_maps(item)

    walk(episode)
    walk_rule_maps(episode)
    return sorted(found)


def build_id_map(episode: dict, *, prefix: str = "X") -> dict[str, str]:
    """Биекция старый ID → новый ID.

    Новые ID непрозрачны и не содержат подсказок о типе записи: иначе
    переименование само стало бы каналом информации.
    """
    ids = collect_ids(episode)
    width = max(4, len(str(len(ids))))
    return {
        old: f"{prefix}-{index:0{width}d}" for index, old in enumerate(ids, start=1)
    }


def apply_id_map(value: Any, id_map: dict[str, str], key: str | None = None) -> Any:
    """Применить карту замены ко всей структуре."""
    if isinstance(value, dict):
        result = {}
        for child_key, child in value.items():
            if child_key in ID_MAP_KEYS and isinstance(child, dict):
                result[child_key] = {
                    rule: id_map.get(rule_id, rule_id)
                    for rule, rule_id in child.items()
                }
            else:
                result[child_key] = apply_id_map(child, id_map, child_key)
        return result
    if isinstance(value, list):
        if key in ID_LIST_KEYS:
            return [id_map.get(item, item) for item in value]
        if key in ID_SET_LIST_KEYS:
            return [[id_map.get(item, item) for item in group or []] for group in value]
        return [apply_id_map(item, id_map, key) for item in value]
    if type(value) is str and key in ID_KEYS:
        return id_map.get(value, value)
    return value


def rename_ids(episode: dict, *, prefix: str = "X") -> tuple[dict, dict[str, str]]:
    """Вернуть эпизод с переименованными ID и карту замены."""
    id_map = build_id_map(episode, prefix=prefix)
    return apply_id_map(episode, id_map), id_map


def permute_records(episode: dict, *, seed: int = 7) -> dict:
    """Перемешать порядок строк и документов.

    Содержание записей не меняется, поэтому и эталон не меняется: обе части
    пары описывают одну и ту же сделку, валюту, сумму и число ошибок.
    """
    rng = random.Random(seed)
    permuted = {key: value for key, value in episode.items()}
    for table in ("ledger", "invoices", "payments", "fx"):
        rows = list(episode.get(table) or [])
        rng.shuffle(rows)
        permuted[table] = rows
    permuted["truth"] = episode["truth"]
    permuted["manifest"] = episode["manifest"]
    permuted["policy"] = episode["policy"]
    return permuted
