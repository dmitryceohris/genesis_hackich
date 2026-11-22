"""Р”РѕРІРµСЂРµРЅРЅР°СЏ РѕР±РІСЏР·РєР°: СЃСЂР°РІРЅРµРЅРёРµ РІРѕСЃСЃС‚Р°РЅРѕРІР»РµРЅРЅРѕРіРѕ СЃ СЌС‚Р°Р»РѕРЅРѕРј.

РўРѕР»СЊРєРѕ Р·РґРµСЃСЊ РІСЃС‚СЂРµС‡Р°СЋС‚СЃСЏ РїСѓР±Р»РёС‡РЅС‹Р№ СЃРЅРёРјРѕРє Рё ``truth``. Р Р°Р·РґРµР»РµРЅРёРµ РґРµСЂР¶РёС‚СЃСЏ
СЃС‚СЂСѓРєС‚СѓСЂРѕР№: ``reconstruct`` РїСЂРёРЅРёРјР°РµС‚ СЃРЅРёРјРѕРє Рё РЅРµ РёРјРµРµС‚ РґРѕСЃС‚СѓРїР° Рє СЌС‚Р°Р»РѕРЅСѓ, Р°
СЌС‚Р° С„СѓРЅРєС†РёСЏ СЃСЂР°РІРЅРёРІР°РµС‚ РґРІР° СѓР¶Рµ РіРѕС‚РѕРІС‹С… СЂРµР·СѓР»СЊС‚Р°С‚Р°.

Р’РµСЂРґРёРєС‚ РїРѕ СЌРїРёР·РѕРґСѓ РѕС‚РІРµС‡Р°РµС‚ РЅР° С‡РµС‚С‹СЂРµ РІРѕРїСЂРѕСЃР° РєСЂРёС‚РµСЂРёСЏ В«Р”Р°РЅРЅС‹Рµ Рё СЌС‚Р°Р»РѕРЅВ»:

1. РґРµСЂР¶Р°С‚СЃСЏ Р»Рё Р±СѓС…РіР°Р»С‚РµСЂСЃРєРёРµ СЂР°РІРµРЅСЃС‚РІР° (``invariant_violations``);
2. РІС‹РІРѕРґРёС‚СЃСЏ Р»Рё РєР°Р¶РґРѕРµ РѕР±СЉСЏРІР»РµРЅРЅРѕРµ СЂР°СЃС…РѕР¶РґРµРЅРёРµ РёР· РїСѓР±Р»РёС‡РЅС‹С… Р·Р°РїРёСЃРµР№
   (``unreconstructed_issue_ids``);
3. РЅРµС‚ Р»Рё РІ РґР°РЅРЅС‹С… СЂР°СЃС…РѕР¶РґРµРЅРёР№, Рѕ РєРѕС‚РѕСЂС‹С… СЌС‚Р°Р»РѕРЅ РјРѕР»С‡РёС‚
   (``undeclared_discrepancies``);
4. РґРѕСЃС‚РёР¶РёРј Рё РґРѕСЃС‚Р°С‚РѕС‡РµРЅ Р»Рё РєР°Р¶РґС‹Р№ РѕР±СЉСЏРІР»РµРЅРЅС‹Р№ РЅР°Р±РѕСЂ РґРѕРєР°Р·Р°С‚РµР»СЊСЃС‚РІ
   (``evidence_problems``).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from evaluator_official import MAX_EVIDENCE_IDS, build_oracle_submission, score

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
                "СЌС‚Р°Р»РѕРЅ РЅРµ РѕР±СЉСЏРІР»СЏРµС‚ РЅРё РѕРґРЅРѕРіРѕ РЅР°Р±РѕСЂР° РґРѕРєР°Р·Р°С‚РµР»СЊСЃС‚РІ",
            )
        ]

    for index, group in enumerate(sets):
        declared = set(group or ())
        if not declared:
            problems.append(
                EvidenceProblem(
                    issue_id, PROBLEM_EMPTY_EVIDENCE_SET, f"РЅР°Р±РѕСЂ {index} РїСѓСЃС‚"
                )
            )
            continue

        if len(declared) > MAX_EVIDENCE_IDS:
            # РРЅР°С‡Рµ oracle СЃРѕР±СЂР°Р» Р±С‹ СЃС‚СЂСѓРєС‚СѓСЂРЅРѕ РЅРµРІР°Р»РёРґРЅСѓСЋ Р·Р°СЏРІРєСѓ.
            problems.append(
                EvidenceProblem(
                    issue_id,
                    PROBLEM_SET_TOO_LARGE,
                    f"РЅР°Р±РѕСЂ {index} СЃРѕРґРµСЂР¶РёС‚ {len(declared)} ID РїСЂРё Р»РёРјРёС‚Рµ "
                    f"{MAX_EVIDENCE_IDS}",
                )
            )

        for evidence_id in sorted(declared - set(reachable)):
            problems.append(
                EvidenceProblem(
                    issue_id,
                    PROBLEM_UNREACHABLE_ID,
                    f"{evidence_id} РЅРµР»СЊР·СЏ РїРѕР»СѓС‡РёС‚СЊ РЅРё get_record, РЅРё "
                    "get_document, РЅРё РєР°Рє Р·Р°РїРёСЃСЊ РїРѕР»РёС‚РёРєРё",
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
                        f"РЅР°Р±РѕСЂ {index} РЅРµ РїРѕРєСЂС‹РІР°РµС‚ РЅРё РѕРґРёРЅ РЅР°Р№РґРµРЅРЅС‹Р№ РІС‹РІРѕРґ "
                        f"СЌС„С„РµРєС‚Р°; РјРёРЅРёРјР°Р»СЊРЅС‹Рµ РІР°СЂРёР°РЅС‚С‹: "
                        f"{[sorted(v) for v in discrepancy.support_variants]}",
                    )
                )

    return problems


def verify_snapshot_and_truth(snapshot: Snapshot, truth: dict) -> EpisodeVerdict:
    """РЎРІРµСЂРёС‚СЊ РїСѓР±Р»РёС‡РЅС‹Р№ СЃРЅРёРјРѕРє СЃ СЌС‚Р°Р»РѕРЅРѕРј."""
    episode_id = truth.get("episode_id", snapshot.episode_id)
    issues = list(truth.get("issues") or [])
    reachable = reachable_ids(snapshot)

    violations = tuple(check_invariants(snapshot))
    discrepancies = tuple(reconstruct(snapshot))

    # РЎРѕРїРѕСЃС‚Р°РІР»РµРЅРёРµ РѕРґРёРЅ Рє РѕРґРЅРѕРјСѓ РїРѕ РєР°РЅРѕРЅРёС‡РµСЃРєРѕР№ РїРѕРґРїРёСЃРё.
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

    # РЎРєРІРѕР·РЅР°СЏ РїСЂРѕРІРµСЂРєР°: Р·Р°СЏРІРєР° oracle РѕР±СЏР·Р°РЅР° РґР°С‚СЊ СЂРѕРІРЅРѕ 1.0. Р•СЃР»Рё СЌС‚Р°Р»РѕРЅ
    # РІРЅСѓС‚СЂРµРЅРЅРµ РїСЂРѕС‚РёРІРѕСЂРµС‡РёРІ, СЌС‚Рѕ РІРёРґРЅРѕ Р·РґРµСЃСЊ, Р° РЅРµ РЅР° Р·Р°С‰РёС‚Рµ.
    #
    # Oracle РЅР°РјРµСЂРµРЅРЅРѕ РїР°РґР°РµС‚ РЅР° РЅРµРґРѕРєР°Р·СѓРµРјРѕРј СЌС‚Р°Р»РѕРЅРµ, РЅРѕ РІР°Р»РёРґР°С‚РѕСЂ РѕР±СЏР·Р°РЅ
    # С‚Р°РєРѕР№ СЌС‚Р°Р»РѕРЅ РґРёР°РіРЅРѕСЃС‚РёСЂРѕРІР°С‚СЊ, Р° РЅРµ РїР°РґР°С‚СЊ РІРјРµСЃС‚Рµ СЃ РЅРёРј: СЂРѕРІРЅРѕ СЌС‚Рѕ РѕРЅ Рё
    # РїСЂРѕРІРµСЂСЏРµС‚.
    try:
        oracle_reward = score(
            build_oracle_submission(truth),
            truth,
            0,
            available_evidence_ids=frozenset(reachable),
        ).reward
    except ValueError as error:
        oracle_reward = 0.0
        notes.append(f"oracle РЅРµ РјРѕР¶РµС‚ СЃРѕР±СЂР°С‚СЊ Р·Р°СЏРІРєСѓ: {error}")

    if not issues and not discrepancies:
        notes.append("С‡РёСЃС‚С‹Р№ СЌРїРёР·РѕРґ: СЂР°СЃС…РѕР¶РґРµРЅРёР№ РЅРµС‚ Рё СЌС‚Р°Р»РѕРЅ РїСѓСЃС‚")

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
    """РЎРІРµСЂРёС‚СЊ СЌРїРёР·РѕРґ С†РµР»РёРєРѕРј: СЃРЅРёРјРѕРє Р±РµСЂС‘С‚СЃСЏ РёР· РЅРµРіРѕ Р±РµР· Р·Р°РєСЂС‹С‚РѕР№ С‡Р°СЃС‚Рё."""
    return verify_snapshot_and_truth(public_snapshot(episode), episode["truth"])


def verify_many(episodes: dict[str, dict]) -> dict:
    """РћС‚С‡С‘С‚ РїРѕ РЅР°Р±РѕСЂСѓ СЌРїРёР·РѕРґРѕРІ РІ С„РѕСЂРјРµ РєСЂРёС‚РµСЂРёСЏ В«Р”Р°РЅРЅС‹Рµ Рё СЌС‚Р°Р»РѕРЅВ»."""
    verdicts = [verify_episode(episode) for _, episode in sorted(episodes.items())]
    correct = sum(1 for verdict in verdicts if verdict.ok)

    return {
        "episode_count": len(verdicts),
        "correct_episode_count": correct,
        # Р–СЋСЂРё СЃС‡РёС‚Р°РµС‚ 25 * РєРѕСЂСЂРµРєС‚РЅС‹С… / 20. Р—РґРµСЃСЊ С‚Р° Р¶Рµ РґРѕР»СЏ, С‡С‚РѕР±С‹ РµС‘ РјРѕР¶РЅРѕ
        # Р±С‹Р»Рѕ СЃРјРѕС‚СЂРµС‚СЊ РґРѕ РїСЂРѕРіРѕРЅР°.
        "correct_share": round(correct / len(verdicts), 6) if verdicts else 0.0,
        "verdicts": [verdict.to_dict() for verdict in verdicts],
    }


