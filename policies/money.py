"""Деньги и даты: независимая реализация опубликованных правил.

Политика сверки обязана считать по тем же правилам, что генератор, но своим
кодом. Это и есть смысл независимой проверки: если обе стороны вызывают одну
функцию, ошибка в правиле не обнаруживается.

Правило конвертации из задания и политики эпизода:

    round_half_even(m × rate × 10^(expT − expS))

Decimal строится из строки, а не из float: ``Decimal(1.25)`` даёт двоичное
приближение и ломает полуцелое округление.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_EVEN, Decimal


def convert_minor(
    source_minor: int,
    rate: str | Decimal,
    source_exponent: int,
    target_exponent: int,
) -> int:
    """Перевести сумму в минимальных единицах из одной валюты в другую."""
    decimal_rate = rate if isinstance(rate, Decimal) else Decimal(str(rate))
    scale = Decimal(10) ** (target_exponent - source_exponent)
    product = Decimal(source_minor) * decimal_rate * scale
    return int(product.quantize(Decimal(1), rounding=ROUND_HALF_EVEN))


def parse_timestamp(value: str) -> datetime:
    """Разобрать ISO-8601 со смещением."""
    return datetime.fromisoformat(value)


def company_timezone(period_start: str) -> timezone:
    """Смещение компании, выведенное из границы периода.

    Намеренно не используется ``zoneinfo``: база часовых поясов может
    отсутствовать в контейнере, а офлайн-прогон не должен от неё зависеть.
    Эпизоды задают период со смещением, и его достаточно, чтобы получить
    календарную дату компании.
    """
    parsed = parse_timestamp(period_start)
    offset = parsed.utcoffset() or timedelta(0)
    return timezone(offset)


def local_date(timestamp: str, tz: timezone) -> date:
    """Календарная дата компании для момента времени.

    Сначала момент переводится в зону компании, затем берётся дата: обратный
    порядок даёт сдвиг на сутки на границе периода.
    """
    return parse_timestamp(timestamp).astimezone(tz).date()


def in_period(day: date, period_start: str, period_end: str, tz: timezone) -> bool:
    """Соглашение [start, end): момент окончания принадлежит следующему периоду."""
    start = parse_timestamp(period_start).astimezone(tz).date()
    end = parse_timestamp(period_end).astimezone(tz).date()
    return start <= day < end


def row_amount_minor(row: dict) -> int:
    """Сумма строки журнала по той стороне, которая заполнена."""
    debit = row.get("debit_minor") or 0
    credit = row.get("credit_minor") or 0
    return debit if debit else credit
