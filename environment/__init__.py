"""Среда эпизода: точка входа протокола жюри.

``make_env()`` отдаёт объект с ``reset(seed, config)`` и ``step(action)`` в
оболочке протокола. Пока этого модуля не было, ``judge_adapter.make_env``
возвращал свою заглушку и сообщал об этом флагом
``ENVIRONMENT_IS_PLACEHOLDER``.

Два режима:

- ``closed`` (по умолчанию) — числовая награда интерфейса всегда 0, включая
  последний шаг. Итог забирает доверенная сторона через ``score_episode``.
- ``train`` — на ``submit`` возвращается терминальная награда, посчитанная
  официальным оценщиком.

ГРАНИЦА ДОСТУПА. Среда читает эпизод и отдаёт наблюдения. Эталон она не
показывает, награду сама не выдумывает, каталог эпизода агенту не передаёт.
"""

from __future__ import annotations

from environment.engine import (
    EPISODE_TIME_LIMIT_SECONDS,
    MAX_PAGE_LIMIT,
    PUBLIC_TABLES,
    AuditEnv,
    evaluate_expression,
    run_policy,
)
from environment.protocol import MODE_CLOSED, MODE_TRAIN, ProtocolEnv

__all__ = [
    "make_env",
    "ProtocolEnv",
    "AuditEnv",
    "MODE_CLOSED",
    "MODE_TRAIN",
    "EPISODE_TIME_LIMIT_SECONDS",
    "MAX_PAGE_LIMIT",
    "PUBLIC_TABLES",
    "evaluate_expression",
    "run_policy",
]


def make_env(mode: str = MODE_CLOSED, **kwargs):
    """Создать среду в оболочке протокола."""
    return ProtocolEnv(mode=mode, **kwargs)
