"""Терминальная награда и сводный отчёт оценщика.

    return = clip(2*F1 - 1 - 0.002*inspection_steps, -1, 1)

``inspection_steps`` — число исследовательских действий, шаг самого ``submit``
в него не входит. Счётчик авторитетно ведёт среда и передаёт сюда; оценщик его
не пересчитывает по журналу.

Функция чистая: повторный вызов на тех же входах даёт тот же отчёт. Повторная
отправка заявки не может изменить оценку.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from fractions import Fraction

from .contract import (
    AMOUNT_TOLERANCE_MINOR,
    EVALUATOR_CONTRACT_VERSION,
    INVALID_SUBMISSION_REWARD,
    REWARD_MAX,
    REWARD_MIN,
    STEP_COST,
)
from .matching import match, normalize_truth
from .metrics import Counts, f1_fraction, precision, recall
from .validation import validate_submission

EMPTY_SUBMISSION_REASON = "truncated_empty_submission"


def clip(value: Decimal, low: Decimal = REWARD_MIN, high: Decimal = REWARD_MAX) -> Decimal:
    if value < low:
        return low
    if value > high:
        return high
    return value


def reward_from_f1(score: Fraction, inspection_steps: int) -> Decimal:
    """Терминальная награда по общей формуле задания.

    F1 передаётся точным рациональным числом, чтобы разница в один шаг
    составляла ровно 0.002 и проверка стоимости шага была честной.
    """
    if inspection_steps < 0:
        raise ValueError("inspection_steps must be non-negative")
    exact_f1 = Decimal(score.numerator) / Decimal(score.denominator)
    raw = 2 * exact_f1 - Decimal(1) - STEP_COST * Decimal(inspection_steps)
    return clip(raw)


@dataclass(frozen=True)
class ScoreReport:
    """Полный приватный отчёт по одному эпизоду.

    В закрытом режиме агенту не передаётся ничего из этого отчёта: он получает
    нейтральный терминальный ответ, а числовая награда интерфейса равна 0.
    """

    episode_id: str
    valid: bool
    reward: float
    tp: int
    fp: int
    fn: int
    precision: float
    recall: float
    f1: float
    inspection_steps: int
    truncated: bool
    matched_pairs: tuple[tuple[int, str], ...] = ()
    unmatched_finding_indexes: tuple[int, ...] = ()
    missed_issue_ids: tuple[str, ...] = ()
    invalid_reason: str | None = None
    invalid_detail: str | None = None
    invalid_finding_index: int | None = None
    contract_version: str = EVALUATOR_CONTRACT_VERSION

    def to_dict(self) -> dict:
        return asdict(self)

    def to_judge_dict(self) -> dict:
        """Ровно те семь полей, которые ждёт ``score_episode`` адаптера.

        Определения проверок: валидный submit возвращает
        ``{"tp", "fp", "fn", "precision", "recall", "f1", "return"}``;
        невалидный — ``return=-1``, а **остальные поля равны null**, и эти
        null-метрики не используются для ранжирования.

        Поэтому внутренний отчёт и ответ жюри — разные вещи: внутри остаются
        диагностика и счётчики для приватного журнала, наружу уходит только
        контрактная семёрка. Ключ называется ``return``, а не ``reward``.
        """
        if not self.valid:
            return {
                "tp": None,
                "fp": None,
                "fn": None,
                "precision": None,
                "recall": None,
                "f1": None,
                "return": float(INVALID_SUBMISSION_REWARD),
            }
        return {
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "return": self.reward,
        }


def score(
    payload: object,
    truth: dict,
    inspection_steps: int,
    *,
    truncated: bool = False,
    tolerance_minor: int = AMOUNT_TOLERANCE_MINOR,
    available_evidence_ids: frozenset[str] | None = None,
) -> ScoreReport:
    """Оценить заявку относительно эталона.

    ``payload`` — то, что агент передал в ``submit``. ``None`` означает, что
    заявки не было: эпизод усечён по шагам или времени, и оценивается пустая
    заявка. Этот итог отличается от структурно неверного ``submit``.

    ``available_evidence_ids`` — публичные ID, которые агент действительно
    может получить инструментами. Нужны, чтобы выдуманное доказательство не
    приносило TP (пример M04). На пути реального эпизода передаются всегда;
    ``None`` оставлен для модульных тестов формулы, где эпизода нет.
    """
    episode_id = truth["episode_id"]
    issues = normalize_truth(truth)

    if payload is None:
        payload = {"episode_id": episode_id, "findings": []}

    validation = validate_submission(payload, episode_id)
    if not validation.ok:
        # Метрики не считаются: задание задаёт итог -1 напрямую.
        return ScoreReport(
            episode_id=episode_id,
            valid=False,
            reward=float(INVALID_SUBMISSION_REWARD),
            tp=0,
            fp=0,
            fn=len(issues),
            precision=0.0,
            recall=0.0,
            f1=0.0,
            inspection_steps=inspection_steps,
            truncated=truncated,
            missed_issue_ids=tuple(issue["issue_id"] for issue in issues),
            invalid_reason=validation.reason,
            invalid_detail=validation.detail,
            invalid_finding_index=validation.finding_index,
        )

    findings = validation.findings
    result = match(findings, issues, tolerance_minor, available_evidence_ids)

    counts = Counts(
        tp=result.tp,
        fp=len(findings) - result.tp,
        fn=len(issues) - result.tp,
    )
    exact_f1 = f1_fraction(counts)

    return ScoreReport(
        episode_id=episode_id,
        valid=True,
        reward=float(reward_from_f1(exact_f1, inspection_steps)),
        tp=counts.tp,
        fp=counts.fp,
        fn=counts.fn,
        precision=precision(counts),
        recall=recall(counts),
        f1=float(exact_f1),
        inspection_steps=inspection_steps,
        truncated=truncated,
        matched_pairs=result.matched_pairs,
        unmatched_finding_indexes=result.unmatched_finding_indexes,
        missed_issue_ids=result.missed_issue_ids,
    )
