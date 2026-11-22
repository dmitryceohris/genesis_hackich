"""Независимая проверка данных и эталона.

Модуль получает только публичный снимок эпизода и политику, строит свои
бухгалтерские сверки и перечисляет все нарушения тождеств. Доверенная обвязка
затем сравнивает результат с ``truth``.

Три вещи, которые делают проверку независимой:

- ``reconstruct`` принимает ``Snapshot`` и не имеет доступа к эталону;
- арифметика и работа с датами продублированы в ``validator/arithmetic.py``
  вторым маршрутом (точные дроби вместо ``Decimal``), поэтому ошибка в правиле
  не подтверждает сама себя;
- перечисляются и расхождения, о которых эталон молчит: по критериям
  противоречивые данные не считаются сложностью.

Границы: валидатор и политика сверки читают одни и те же опубликованные
правила, поэтому они не являются статистически независимыми реализациями
предметной модели. Что проверка действительно добавляет — инварианты по всему
снимку, поиск необъявленных расхождений, достижимость и достаточность
доказательств и тесты с внесением дефектов. Сами правила стоит отдать на
вычитку третьему человеку.
"""

from .arithmetic import convert_minor, in_period, local_date, round_half_even
from .invariants import Violation, check_invariants
from .reconstruction import Discrepancy, reconstruct
from .snapshot import Snapshot, public_snapshot, reachable_ids
from .verify import (
    EpisodeVerdict,
    EvidenceProblem,
    verify_episode,
    verify_many,
    verify_snapshot_and_truth,
)

__all__ = [
    "Discrepancy",
    "EpisodeVerdict",
    "EvidenceProblem",
    "Snapshot",
    "Violation",
    "check_invariants",
    "convert_minor",
    "in_period",
    "local_date",
    "public_snapshot",
    "reachable_ids",
    "reconstruct",
    "round_half_even",
    "verify_episode",
    "verify_many",
    "verify_snapshot_and_truth",
]
