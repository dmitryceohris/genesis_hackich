"""Совместимость: ядро среды переехало в ``environment/engine.py``.

Тесты и базовые политики писались против этого модуля, пока зоны среды не
существовало. Поведение не изменилось, поэтому модуль остался как реэкспорт, а
не как вторая копия: две копии среды неизбежно разошлись бы, и тесты проверяли
бы не то, что запускает жюри.
"""

from environment.engine import (  # noqa: F401
    ERR_EPISODE_FINISHED,
    ERR_INVALID_ARGUMENTS,
    ERR_INVALID_CURSOR,
    ERR_INVALID_EXPRESSION,
    ERR_INVALID_LIMIT,
    ERR_NOT_FOUND,
    ERR_UNKNOWN_ACTION,
    ERR_UNKNOWN_TABLE,
    MAX_PAGE_LIMIT,
    PUBLIC_TABLES,
    TABLE_ID_FIELD,
    AuditEnv,
    FakeEnv,
    evaluate_expression,
    run_policy,
)
