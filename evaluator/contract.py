"""Константы контракта оценщика.

Источник значений — задание, разделы 03 и 05. Всё, что здесь лежит, обязано
совпадать с docs/evaluator-contract.md. Если генератор или среда расходятся с
этим файлом, правится одна из сторон, но не обе молча.
"""

from __future__ import annotations

import re
from decimal import Decimal

#: Версия контракта оценщика. Входит в отчёт, чтобы прогоны были сравнимы.
EVALUATOR_CONTRACT_VERSION = "1.0.0"

#: Четыре независимо настраиваемых типа ошибок (задание, раздел 02).
ISSUE_TYPES: tuple[str, ...] = (
    "duplicate_invoice",
    "payment_allocation",
    "fx_conversion",
    "period_cutoff",
)

ISSUE_TYPE_SET = frozenset(ISSUE_TYPES)

# --- Лимиты заявки (задание, раздел 05) ---------------------------------------

MAX_FINDINGS = 30
MAX_EVIDENCE_IDS = 10
MAX_EXPLANATION_CHARS = 1000

# --- Сопоставление ------------------------------------------------------------

#: Допуск по сумме в минимальных единицах. Объявлен явно, как требует задание.
AMOUNT_TOLERANCE_MINOR = 0

#: Формат валюты. Сравнение регистрозависимое, как и для всех ID.
CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")

# --- Награда ------------------------------------------------------------------

#: Максимум шагов в эпизоде, включая submit.
MAX_STEPS = 100

#: Цена одного исследовательского шага.
STEP_COST = Decimal("0.002")

REWARD_MIN = Decimal("-1")
REWARD_MAX = Decimal("1")

#: Итог структурно неверной заявки (задание, раздел 05).
INVALID_SUBMISSION_REWARD = Decimal("-1")


def is_strict_int(value: object) -> bool:
    """True только для настоящего int.

    В Python ``bool`` — подкласс ``int``, поэтому ``isinstance(True, int)``
    возвращает True и ``true`` в поле денег прошёл бы как 1. Задание требует
    считать такую заявку структурно неверной, поэтому проверка строгая.
    """
    return type(value) is int


def is_strict_str(value: object) -> bool:
    return type(value) is str
