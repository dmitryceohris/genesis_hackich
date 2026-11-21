"""Базовые политики.

Три политики, которые видят только наблюдения:

- ``RandomExplorer`` — нижняя точка сравнения и проверка устойчивости среды;
- ``ReconciliationAgent`` — простой алгоритм сверки, доказывает решаемость;
- ``MarkAllAgent`` — атака «пометить всё», проверяет штраф за ложные обвинения.

Четвёртый адаптер — oracle — намеренно НЕ здесь. Задание требует, чтобы он
существовал только для оценщика, поэтому он живёт в
``evaluator.oracle.build_oracle_submission`` и вызывается доверенным процессом
вне контейнера агента. Политика, читающая ``truth.json``, — это канал утечки
эталона, а утечка блокирует оценивание целиком.
"""

from .base import Policy
from .mark_all_agent import MarkAllAgent
from .random_agent import RandomExplorer
from .reconciliation_agent import ReconciliationAgent

__all__ = [
    "MarkAllAgent",
    "Policy",
    "RandomExplorer",
    "ReconciliationAgent",
]
