"""Валютное плечо платежа: пересчёт суммы по фиксингу на дату.

Книга ведётся в базовой валюте, но часть платежей уходит в банк в
иностранной. Тогда у денежной строки журнала две суммы: та, что списана со
счёта (``source_minor`` в ``source_currency``), и та, что отражена в книге
(``debit_minor``/``credit_minor`` в базовой валюте). Связь между ними — курс на
дату платежа.

Это и делает ошибку ``fx_conversion`` денежной: пересчёт по неверному курсу
искажает ровно отражённую сумму, и разница вычисляется из публичных записей.
Пока плеча не было, искажение курса в таблице фиксингов не меняло ни одной
суммы и доказать его было нечем.

Округление — банковское, как во всём проекте: ``ROUND_HALF_EVEN`` над
``Decimal``. Отдельная реализация здесь не нужна, формула одна строка, но
правило округления обязано совпадать с оценщиком и валидатором, иначе
расхождение в одну минимальную единицу породило бы ложную ошибку.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal

#: Сколько знаков в минимальной единице. Генератор работает с валютами, где
#: их два; иное значение потребовало бы масштабирования и здесь, и в оценщике.
MINOR_EXPONENT = 2


def rate_on(fx: list[dict], currency: str, day: str) -> dict | None:
    """Фиксинг для ``currency`` к базовой валюте на дату ``day``."""
    for row in fx:
        if row["quote_currency"] == currency and row["date"] == day:
            return row
    return None


def quote_currencies(fx: list[dict]) -> list[str]:
    """Валюты, для которых в эпизоде есть фиксинги, в устойчивом порядке."""
    seen: list[str] = []
    for row in fx:
        currency = row["quote_currency"]
        if currency not in seen:
            seen.append(currency)
    return seen


def to_base_minor(source_minor: int, rate: str | Decimal) -> int:
    """Пересчитать сумму в иностранной валюте в базовую."""
    value = Decimal(source_minor) * Decimal(str(rate))
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_EVEN))


def from_base_minor(base_minor: int, rate: str | Decimal) -> int:
    """Обратный пересчёт: сколько иностранной валюты даёт базовую сумму.

    Точного обратного хода у округления нет, поэтому
    ``to_base_minor(from_base_minor(x)) != x`` — это нормально. Разницу
    журнал относит на счёт курсовой разницы, как и положено в учёте, а не
    подгоняет суммы.
    """
    rate_value = Decimal(str(rate))
    if rate_value <= 0:
        raise ValueError("курс должен быть положительным")
    value = Decimal(base_minor) / rate_value
    return max(1, int(value.quantize(Decimal(1), rounding=ROUND_HALF_EVEN)))
