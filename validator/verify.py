"""Доверенная обвязка: сравнение восстановленного с эталоном.

Только здесь встречаются публичный снимок и ``truth``. Разделение держится
структурой: ``reconstruct`` принимает снимок и не имеет доступа к эталону, а
эта функция сравнивает два уже готовых результата.

Вердикт по эпизоду отвечает на четыре вопроса критерия «Данные и эталон»:

1. держатся ли бухгалтерские равенства (``invariant_violations``);
2. выводится ли каждое объявленное расхождение из публичных записей
   (``unreconstructed_issue_ids``);
3. нет ли в данных расхождений, о которых эталон молчит
   (``undeclared_discrepancies``);
4. достижим и достаточен ли каждый объявленный набор доказательств
   (``evidence_problems``).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from evaluator import MAX_EVIDENCE_IDS, build_oracle_submission, score

from .invariants import Violation, check_invariants
from .reconstruction import Discrepancy, reconstruct
from .snapshot import Snapshot, public_snapshot, reachable_ids

PROBLEM_NO_EVIDENCE_SETS = "evidence_sets_missing"
PROBLEM_EMPTY_EVIDENCE_SET = "evidence_set_empty"
PROBLEM_UNREACHABLE_ID = "evidence_id_unreachable"
PROBLEM_SET_TOO_LARGE = "evidence_set_exceeds_limit"
PROBLEM_SET_NOT_SUFFICIENT = "evidence_set_covers_no_derivation"


@dataclass(frozen=True)
class EvidenceProblem:
    issue_id: str
    code: str
    detail: str

    def to_dict(self) -> dict:
        return {"issue_id": self.issue_id, "code": self.code, "detail": self.detail}


@dataclass(frozen=True)
class EpisodeVerdict:
    episode_id: str
    ok: bool
    invariant_violations: tuple[Violation, ...] = ()
    reconstructed: tuple[Discrepancy, ...] = ()
    matched_issue_ids: tuple[str, ...] = ()
    unreconstructed_issue_ids: tuple[str, ...] = ()
    undeclared_discrepancies: tuple[Discrepancy, ...] = ()
    evidence_problems: tuple[EvidenceProblem, ...] = ()
    oracle_reward: float = 0.0
    declared_issue_count: int = 0
    notes: tuple[str, ...] = field(default=())

    def to_dict(self) -> dict:
        return {
            "episode_id": self.episode_id,
            "ok": self.ok,
            "declared_issue_count": self.declared_issue_count,
            "oracle_reward": self.oracle_reward,
            "invariant_violations": [item.to_dict() for item in self.invariant_violations],
            "reconstructed": [item.to_dict() for item in self.reconstructed],
            "matched_issue_ids": list(self.matched_issue_ids),
            "unreconstructed_issue_ids": list(self.unreconstructed_issue_ids),
            "undeclared_discrepancies": [
                item.to_dict() for item in self.undeclared_discrepancies
            ],
            "evidence_problems": [item.to_dict() for item in self.evidence_problems],
            "notes": list(self.notes),
        }


def _issue_signature(issue: dict) -> tuple:
    return (
        issue.get("type"),
        frozenset(issue.get("affected_ids") or ()),
        issue.get("expected_amount_minor"),
        issue.get("currency"),
    )


def _check_evidence(
    issue: dict,
    discrepancy: Discrepancy | None,
    reachable: dict[str, str],
) -> list[EvidenceProblem]:
    issue_id = str(issue.get("issue_id"))
    problems: list[EvidenceProblem] = []

    sets = issue.get("acceptable_evidence_sets") or []
    if not sets:
        return [
            EvidenceProblem(
                issue_id,
                PROBLEM_NO_EVIDENCE_SETS,
                "эталон не объявляет ни одного набора доказательств",
            )
        ]

    for index, group in enumerate(sets):
        declared = set(group or ())
        if not declared:
            problems.append(
                EvidenceProblem(
                    issue_id, PROBLEM_EMPTY_EVIDENCE_SET, f"набор {index} пуст"
                )
            )
            continue

        if len(declared) > MAX_EVIDENCE_IDS:
            # Иначе oracle собрал бы структурно невалидную заявку.
            problems.append(
                EvidenceProblem(
                    issue_id,
                    PROBLEM_SET_TOO_LARGE,
                    f"набор {index} содержит {len(declared)} ID при лимите "
                    f"{MAX_EVIDENCE_IDS}",
                )
            )

        for evidence_id in sorted(declared - set(reachable)):
            problems.append(
                EvidenceProblem(
                    issue_id,
                    PROBLEM_UNREACHABLE_ID,
                    f"{evidence_id} нельзя получить ни get_record, ни "
                    "get_document, ни как запись политики",
                )
            )

        if discrepancy is not None and discrepancy.support_variants:
            if not any(
                variant <= declared for variant in discrepancy.support_variants
            ):
                problems.append(
                    EvidenceProblem(
                        issue_id,
                        PROBLEM_SET_NOT_SUFFICIENT,
                        f"набор {index} не покрывает ни один найденный вывод "
                        f"эффекта; минимальные варианты: "
                        f"{[sorted(v) for v in discrepancy.support_variants]}",
                    )
                )

    return problems


def verify_snapshot_and_truth(snapshot: Snapshot, truth: dict) -> EpisodeVerdict:
    """Сверить публичный снимок с эталоном."""
    episode_id = truth.get("episode_id", snapshot.episode_id)
    issues = list(truth.get("issues") or [])
    reachable = reachable_ids(snapshot)

    violations = tuple(check_invariants(snapshot))
    discrepancies = tuple(reconstruct(snapshot))

    # Сопоставление один к одному по канонической подписи.
    available: dict[tuple, list[Discrepancy]] = {}
    for item in discrepancies:
        available.setdefault(item.signature(), []).append(item)

    matched: list[str] = []
    unreconstructed: list[str] = []
    evidence_problems: list[EvidenceProblem] = []

    for issue in issues:
        signature = _issue_signature(issue)
        bucket = available.get(signature) or []
        paired = bucket.pop(0) if bucket else None
        if paired is None:
            unreconstructed.append(str(issue.get("issue_id")))
        else:
            matched.append(str(issue.get("issue_id")))
        evidence_problems.extend(_check_evidence(issue, paired, reachable))

    undeclared = tuple(
        item for bucket in available.values() for item in bucket
    )

    notes: list[str] = []

    # Сквозная проверка: заявка oracle обязана дать ровно 1.0. Если эталон
    # внутренне противоречив, это видно здесь, а не на защите.
    #
    # Oracle намеренно падает на недоказуемом эталоне, но валидатор обязан
    # такой эталон диагностировать, а не падать вместе с ним: ровно это он и
    # проверяет.
    try:
        oracle_reward = score(
            build_oracle_submission(truth),
            truth,
            0,
            available_evidence_ids=frozenset(reachable),
        ).reward
    except ValueError as error:
        oracle_reward = 0.0
        notes.append(f"oracle не может собрать заявку: {error}")

    if not issues and not discrepancies:
        notes.append("чистый эпизод: расхождений нет и эталон пуст")

    ok = (
        not violations
        and not unreconstructed
        and not undeclared
        and not evidence_problems
        and oracle_reward == 1.0
    )

    return EpisodeVerdict(
        episode_id=episode_id,
        ok=ok,
        invariant_violations=violations,
        reconstructed=discrepancies,
        matched_issue_ids=tuple(matched),
        unreconstructed_issue_ids=tuple(unreconstructed),
        undeclared_discrepancies=undeclared,
        evidence_problems=tuple(evidence_problems),
        oracle_reward=oracle_reward,
        declared_issue_count=len(issues),
        notes=tuple(notes),
    )


def verify_episode(episode: dict) -> EpisodeVerdict:
    """Сверить эпизод целиком: снимок берётся из него без закрытой части."""
    return verify_snapshot_and_truth(public_snapshot(episode), episode["truth"])


def verify_many(episodes: dict[str, dict]) -> dict:
    """Отчёт по набору эпизодов в форме критерия «Данные и эталон»."""
    verdicts = [verify_episode(episode) for _, episode in sorted(episodes.items())]
    correct = sum(1 for verdict in verdicts if verdict.ok)

    return {
        "episode_count": len(verdicts),
        "correct_episode_count": correct,
        # Жюри считает 25 * корректных / 20. Здесь та же доля, чтобы её можно
        # было смотреть до прогона.
        "correct_share": round(correct / len(verdicts), 6) if verdicts else 0.0,
        "verdicts": [verdict.to_dict() for verdict in verdicts],
    }
