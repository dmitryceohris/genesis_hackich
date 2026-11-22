"""Часовой пояс эпизода без обязательной базы таймзон.

``zoneinfo`` входит в стандартную библиотеку, но сама база данных — нет. В
``python:3.11-slim`` её нет, и ``ZoneInfo("Asia/Almaty")`` там падает с
``ZoneInfoNotFoundError``. Обязательная проверка идёт офлайн, поэтому генератор
не может зависеть от пакета, который нужно доустанавливать.

Решение: для поясов без переходов на летнее время хранится постоянное
смещение, и результат совпадает с ``ZoneInfo`` до секунды. Для поясов с
переходами подмена смещением дала бы другие данные по разные стороны границы
перехода, то есть разные эпизоды на разных машинах при одном seed. Такое молча
допускать нельзя, поэтому они требуют установленной базы и об этом говорится
в ошибке.
"""

from __future__ import annotations

from datetime import timedelta, timezone, tzinfo

#: Пояса с постоянным смещением в пределах периодов, которые строит генератор.
#: Казахстан с марта 2024 года живёт в едином поясе UTC+5 и переходов не делает.
FIXED_OFFSET_SECONDS: dict[str, int] = {
    "Asia/Almaty": 5 * 3600,
    "Asia/Aqtobe": 5 * 3600,
    "UTC": 0,
}


def resolve(name: str) -> tzinfo:
    """Вернуть пояс по имени IANA.

    Сначала пробуется ``ZoneInfo``: если база есть, берутся её данные. Если
    базы нет, работает запасной путь для поясов без переходов.
    """
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:  # ZoneInfoNotFoundError и отсутствие модуля
        seconds = FIXED_OFFSET_SECONDS.get(name)
        if seconds is None:
            raise RuntimeError(
                f"Пояс {name!r} имеет переходы на летнее время, и база таймзон "
                "не найдена. Либо поставьте пакет tzdata, либо задайте в "
                "config.company.timezone пояс из "
                f"{sorted(FIXED_OFFSET_SECONDS)}."
            ) from None
        return timezone(timedelta(seconds=seconds), name)
