"""Оценщик: валидация заявки, сопоставление с эталоном, метрики, награда.

Границы зоны:

- этот пакет работает в доверенном процессе вне контейнера агента;
- он никогда не пишет в наблюдения, ``info`` или траектории;
- ``oracle`` живёт здесь, а не в ``policies/``.

Контракт описан в ``docs/evaluator-contract.md``.
"""

from .contract import (
    AMOUNT_TOLERANCE_MINOR,
    EVALUATOR_CONTRACT_VERSION,
    ISSUE_TYPES,
    MAX_EVIDENCE_IDS,
    MAX_EXPLANATION_CHARS,
    MAX_FINDINGS,
    MAX_STEPS,
    STEP_COST,
)
from .matching import (
    MatchResult,
    build_edges,
    evidence_is_sufficient,
    finding_matches_issue,
    lexicographic_maximum_matching,
    match,
    normalize_truth,
)
from .metrics import Counts, f1, f1_fraction, precision, recall
from .oracle import build_oracle_submission
from .scoring import ScoreReport, clip, reward_from_f1, score
from .validation import Validation, validate_submission

__all__ = [
    "AMOUNT_TOLERANCE_MINOR",
    "EVALUATOR_CONTRACT_VERSION",
    "ISSUE_TYPES",
    "MAX_EVIDENCE_IDS",
    "MAX_EXPLANATION_CHARS",
    "MAX_FINDINGS",
    "MAX_STEPS",
    "STEP_COST",
    "Counts",
    "MatchResult",
    "ScoreReport",
    "Validation",
    "build_edges",
    "build_oracle_submission",
    "clip",
    "evidence_is_sufficient",
    "f1",
    "f1_fraction",
    "finding_matches_issue",
    "lexicographic_maximum_matching",
    "match",
    "normalize_truth",
    "precision",
    "recall",
    "reward_from_f1",
    "score",
    "validate_submission",
]
