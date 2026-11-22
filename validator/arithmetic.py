"""Своя арифметика валидатора.

Намеренное дублирование ``policies/money.py``. Если обе стороны вызывают одну
функцию, ошибка в правиле конвертации не обнаруживается: проверка подтвердит
сама себя. Поэтому здесь второй маршрут к тому же результату — точная
рациональная арифметика и полуцелое округление вручную, без ``Decimal``.

Совпадение двух реализаций на всех эпизодах и есть доказательство, что правило
прочитано одинаково. Расхождение — повод разбираться, а не подгонять.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from fractions import Fraction


def parse_decimal_string(value: str) -> Fraction:
    """Десятичная строка в точную дробь.

    ``Fraction("1.25")`` разбирает строку сам и не теряет точность, в отличие
    от ``float("1.25")``.
    """
    return Fraction(str(value))


def round_half_even(value: Fraction) -> int:
    """Полуцелое округление к ближайшему чётному, вручную.

    Нужно именно банковское округление: при ``round_half_up`` суммы
    расходились бы с генератором на одну минимальную единицу ровно в
    половинных случаях, и такие эпизоды выглядели бы как дефект данных.
    """
    floor_value = value.numerator // value.denominator
    remainder = value - floor_value

    if remainder < Fraction(1, 2):
        return floor_value
    if remainder > Fraction(1, 2):
        return floor_value + 1
    # Ровно половина: выбираем чётное.
    return floor_value if floor_value % 2 == 0 else floor_value + 1


def convert_minor(
    source_minor: int,
    rate: str,
    source_exponent: int,
    target_exponent: int,
) -> int:
    """round_half_even(m * rate * 10^(expT - expS)) на точных дробях."""
    scale = Fraction(10) ** (target_exponent - source_exponent)
    return round_half_even(Fraction(source_minor) * parse_decimal_string(rate) * scale)


def company_timezone(period_start: str) -> timezone:
    """Смещение компании из границы периода, без базы часовых поясов."""
    offset = datetime.fromisoformat(period_start).utcoffset() or timedelta(0)
    return timezone(offset)


def local_date(timestamp: str, tz: timezone) -> date:
    """Сначала перевод момента в зону компании, затем календарная дата."""
    return datetime.fromisoformat(timestamp).astimezone(tz).date()


def in_period(day: date, period_start: str, period_end: str, tz: timezone) -> bool:
    """Соглашение [start, end)."""
    start = datetime.fromisoformat(period_start).astimezone(tz).date()
    end = datetime.fromisoformat(period_end).astimezone(tz).date()
    return start <= day < end


def row_amount_minor(row: dict) -> int:
    debit = row.get("debit_minor") or 0
    credit = row.get("credit_minor") or 0
    return debit if debit else credit
