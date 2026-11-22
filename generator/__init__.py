"""Генератор эпизодов: точка входа протокола жюри.

Внутри две части. ``generator.generator`` строит компанию, счёта, платежи,
книгу и фиксинги и вносит четыре типа дефектов, отдавая вложенную структуру со
своими именами полей. ``integration.episode_adapter`` переводит её в схему
контракта оценщика (``docs/evaluator-contract.md``). Здесь они соединены и
результат пишется на диск в формате ``evaluator/episode_io.py``.

Подпись совпадает с той, которую ждёт ``judge_adapter.generate_episode``:
``generate_episode(seed, config, output_dir)``. Пока этого модуля не было,
адаптер жюри работал на фикстурах и сообщал об этом флагом
``GENERATOR_IS_PLACEHOLDER``.

ГРАНИЦА ДОСТУПА. Этот пакет — доверенная сторона: он знает seed, config,
``truth`` и ``provenance``. Политика агента его не импортирует и каталог
эпизода не видит.
"""

from __future__ import annotations

from pathlib import Path

from generator.generator import generate_episode as _build_raw_episode

__all__ = ["generate_episode", "build_episode", "ERROR_TYPES", "TYPE_MAP"]

#: Имена типов дефектов внутри генератора и их официальные соответствия.
#: Генератор исторически назвал два типа иначе, перевод делает адаптер.
TYPE_MAP = {
    "duplicate_invoice": "duplicate_invoice",
    "payment_allocation": "payment_allocation",
    "fx_rate": "fx_conversion",
    "accounting_period": "period_cutoff",
}

ERROR_TYPES = tuple(TYPE_MAP)

#: Типы, включённые по умолчанию.
#:
#: ``fx_rate`` намеренно выключен. Генератор строит одновалютную книгу: счёта,
#: платежи и проводки все в базовой валюте, а таблица фиксингов ни одной
#: проводкой не используется. Поэтому искажение курса не порождает искажённой
#: суммы, независимая реконструкция такое расхождение не выводит (проверено на
#: 20 сидах, см. DESIGN.md), а по контракту необъявляемую ошибку в эталон
#: вносить нельзя. Включать обратно имеет смысл вместе с валютным плечом
#: платежа. Передаётся через ``config["error_types"]``.
DEFAULT_ERROR_TYPES = (
    "duplicate_invoice",
    "payment_allocation",
    "accounting_period",
)


def build_episode(seed: int, config: dict | None = None) -> dict:
    """Собрать эпизод в схеме контракта, ничего не записывая на диск.

    Возвращает словарь с ключами ``manifest``, ``ledger``, ``invoices``,
    ``payments``, ``fx``, ``policy``, ``truth``, ``provenance``.
    """
    from integration.episode_adapter import adapt_episode

    config = dict(config or {})
    config.setdefault("error_types", list(DEFAULT_ERROR_TYPES))

    return adapt_episode(_build_raw_episode(seed, config))


def generate_episode(
    seed: int, config: dict | None = None, output_dir: str | Path | None = None
) -> dict:
    """Сгенерировать эпизод и записать его каталогом.

    ``output_dir`` получает восемь файлов: шесть публичных и закрытые
    ``truth.json`` с ``provenance.json``. Агент этот каталог не читает — он
    ходит через среду.
    """
    from evaluator.episode_io import write_episode

    episode = build_episode(seed, config)
    if output_dir is not None:
        write_episode(episode, output_dir)
    return episode
