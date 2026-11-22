"""TP/FP/FN, precision, recall, F1.

F1 считается прямой формулой из задания ``2TP / (2TP + FP + FN)``, а не как
``2PR / (P + R)``. Вторая форма даёт 0/0 там, где задание требует конкретное
значение, и ломает проверку «молчание на чистой книге».
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction


@dataclass(frozen=True)
class Counts:
    """Счётчики сопоставления."""

    tp: int
    fp: int
    fn: int

    def __post_init__(self) -> None:
        if self.tp < 0 or self.fp < 0 or self.fn < 0:
            raise ValueError("counts must be non-negative")

    @property
    def claimed(self) -> int:
        """Сколько выводов было в заявке."""
        return self.tp + self.fp

    @property
    def expected(self) -> int:
        """Сколько ошибок было в эталоне."""
        return self.tp + self.fn


def precision(counts: Counts) -> float:
    """P = TP / (TP + FP). При нулевом знаменателе 0 (задание, раздел 05)."""
    denominator = counts.tp + counts.fp
    if denominator == 0:
        return 0.0
    return counts.tp / denominator


def recall(counts: Counts) -> float:
    """R = TP / (TP + FN). При нулевом знаменателе 0 (задание, раздел 05)."""
    denominator = counts.tp + counts.fn
    if denominator == 0:
        return 0.0
    return counts.tp / denominator


def f1_fraction(counts: Counts) -> Fraction:
    """Точный F1 как рациональное число.

    Единственный случай нулевого знаменателя — пустой эталон и пустая заявка.
    Задание задаёт для него F1 = 1. Остальные края формула закрывает сама:
    пустой эталон с непустой заявкой даёт 0/FP = 0, непустой эталон с пустой
    заявкой даёт 0/FN = 0.
    """
    denominator = 2 * counts.tp + counts.fp + counts.fn
    if denominator == 0:
        return Fraction(1)
    return Fraction(2 * counts.tp, denominator)


def f1(counts: Counts) -> float:
    return float(f1_fraction(counts))
