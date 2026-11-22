"""РЎРІРѕСЏ Р°СЂРёС„РјРµС‚РёРєР° РІР°Р»РёРґР°С‚РѕСЂР°.

РќР°РјРµСЂРµРЅРЅРѕРµ РґСѓР±Р»РёСЂРѕРІР°РЅРёРµ ``policies/money.py``. Р•СЃР»Рё РѕР±Рµ СЃС‚РѕСЂРѕРЅС‹ РІС‹Р·С‹РІР°СЋС‚ РѕРґРЅСѓ
С„СѓРЅРєС†РёСЋ, РѕС€РёР±РєР° РІ РїСЂР°РІРёР»Рµ РєРѕРЅРІРµСЂС‚Р°С†РёРё РЅРµ РѕР±РЅР°СЂСѓР¶РёРІР°РµС‚СЃСЏ: РїСЂРѕРІРµСЂРєР° РїРѕРґС‚РІРµСЂРґРёС‚
СЃР°РјР° СЃРµР±СЏ. РџРѕСЌС‚РѕРјСѓ Р·РґРµСЃСЊ РІС‚РѕСЂРѕР№ РјР°СЂС€СЂСѓС‚ Рє С‚РѕРјСѓ Р¶Рµ СЂРµР·СѓР»СЊС‚Р°С‚Сѓ вЂ” С‚РѕС‡РЅР°СЏ
СЂР°С†РёРѕРЅР°Р»СЊРЅР°СЏ Р°СЂРёС„РјРµС‚РёРєР° Рё РїРѕР»СѓС†РµР»РѕРµ РѕРєСЂСѓРіР»РµРЅРёРµ РІСЂСѓС‡РЅСѓСЋ, Р±РµР· ``Decimal``.

РЎРѕРІРїР°РґРµРЅРёРµ РґРІСѓС… СЂРµР°Р»РёР·Р°С†РёР№ РЅР° РІСЃРµС… СЌРїРёР·РѕРґР°С… Рё РµСЃС‚СЊ РґРѕРєР°Р·Р°С‚РµР»СЊСЃС‚РІРѕ, С‡С‚Рѕ РїСЂР°РІРёР»Рѕ
РїСЂРѕС‡РёС‚Р°РЅРѕ РѕРґРёРЅР°РєРѕРІРѕ. Р Р°СЃС…РѕР¶РґРµРЅРёРµ вЂ” РїРѕРІРѕРґ СЂР°Р·Р±РёСЂР°С‚СЊСЃСЏ, Р° РЅРµ РїРѕРґРіРѕРЅСЏС‚СЊ.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from fractions import Fraction


def parse_decimal_string(value: str) -> Fraction:
    """Р”РµСЃСЏС‚РёС‡РЅР°СЏ СЃС‚СЂРѕРєР° РІ С‚РѕС‡РЅСѓСЋ РґСЂРѕР±СЊ.

    ``Fraction("1.25")`` СЂР°Р·Р±РёСЂР°РµС‚ СЃС‚СЂРѕРєСѓ СЃР°Рј Рё РЅРµ С‚РµСЂСЏРµС‚ С‚РѕС‡РЅРѕСЃС‚СЊ, РІ РѕС‚Р»РёС‡РёРµ
    РѕС‚ ``float("1.25")``.
    """
    return Fraction(str(value))


def round_half_even(value: Fraction) -> int:
    """РџРѕР»СѓС†РµР»РѕРµ РѕРєСЂСѓРіР»РµРЅРёРµ Рє Р±Р»РёР¶Р°Р№С€РµРјСѓ С‡С‘С‚РЅРѕРјСѓ, РІСЂСѓС‡РЅСѓСЋ.

    РќСѓР¶РЅРѕ РёРјРµРЅРЅРѕ Р±Р°РЅРєРѕРІСЃРєРѕРµ РѕРєСЂСѓРіР»РµРЅРёРµ: РїСЂРё ``round_half_up`` СЃСѓРјРјС‹
    СЂР°СЃС…РѕРґРёР»РёСЃСЊ Р±С‹ СЃ РіРµРЅРµСЂР°С‚РѕСЂРѕРј РЅР° РѕРґРЅСѓ РјРёРЅРёРјР°Р»СЊРЅСѓСЋ РµРґРёРЅРёС†Сѓ СЂРѕРІРЅРѕ РІ
    РїРѕР»РѕРІРёРЅРЅС‹С… СЃР»СѓС‡Р°СЏС…, Рё С‚Р°РєРёРµ СЌРїРёР·РѕРґС‹ РІС‹РіР»СЏРґРµР»Рё Р±С‹ РєР°Рє РґРµС„РµРєС‚ РґР°РЅРЅС‹С….
    """
    floor_value = value.numerator // value.denominator
    remainder = value - floor_value

    if remainder < Fraction(1, 2):
        return floor_value
    if remainder > Fraction(1, 2):
        return floor_value + 1
    # Р РѕРІРЅРѕ РїРѕР»РѕРІРёРЅР°: РІС‹Р±РёСЂР°РµРј С‡С‘С‚РЅРѕРµ.
    return floor_value if floor_value % 2 == 0 else floor_value + 1


def convert_minor(
    source_minor: int,
    rate: str,
    source_exponent: int,
    target_exponent: int,
) -> int:
    """round_half_even(m * rate * 10^(expT - expS)) РЅР° С‚РѕС‡РЅС‹С… РґСЂРѕР±СЏС…."""
    scale = Fraction(10) ** (target_exponent - source_exponent)
    return round_half_even(Fraction(source_minor) * parse_decimal_string(rate) * scale)


def company_timezone(period_start: str) -> timezone:
    """РЎРјРµС‰РµРЅРёРµ РєРѕРјРїР°РЅРёРё РёР· РіСЂР°РЅРёС†С‹ РїРµСЂРёРѕРґР°, Р±РµР· Р±Р°Р·С‹ С‡Р°СЃРѕРІС‹С… РїРѕСЏСЃРѕРІ."""
    offset = datetime.fromisoformat(period_start).utcoffset() or timedelta(0)
    return timezone(offset)


def local_date(timestamp: str, tz: timezone) -> date:
    """РЎРЅР°С‡Р°Р»Р° РїРµСЂРµРІРѕРґ РјРѕРјРµРЅС‚Р° РІ Р·РѕРЅСѓ РєРѕРјРїР°РЅРёРё, Р·Р°С‚РµРј РєР°Р»РµРЅРґР°СЂРЅР°СЏ РґР°С‚Р°."""
    return datetime.fromisoformat(timestamp).astimezone(tz).date()


def in_period(day: date, period_start: str, period_end: str, tz: timezone) -> bool:
    """РЎРѕРіР»Р°С€РµРЅРёРµ [start, end)."""
    start = datetime.fromisoformat(period_start).astimezone(tz).date()
    end = datetime.fromisoformat(period_end).astimezone(tz).date()
    return start <= day < end


def row_amount_minor(row: dict) -> int:
    debit = row.get("debit_minor") or 0
    credit = row.get("credit_minor") or 0
    return debit if debit else credit


