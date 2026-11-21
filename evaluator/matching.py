"""Сопоставление выводов с эталоном.

Задание требует взаимно однозначного сопоставления. Жадный проход по выводам
занижает TP: вывод, подходящий к двум эталонным ошибкам, может забрать ту,
которая больше ни с чем не сопоставима. Поэтому строится двудольный граф и
ищется максимальное паросочетание.

При нескольких паросочетаниях одинакового размера выбор обязан быть
детерминированным, иначе ломается критерий воспроизводимости. Здесь выбирается
лексикографически первое решение по отсортированному списку пар
(индекс вывода, issue_id).
"""

from __future__ import annotations

from dataclasses import dataclass

from .contract import AMOUNT_TOLERANCE_MINOR

Edge = tuple[int, str]


def canonical_ids(ids: object) -> frozenset[str]:
    """Канонический вид списка ID.

    Порядок не значим, повторы не значимы, регистр значим, пробелы не
    обрезаются: ID — непрозрачные строки.
    """
    return frozenset(ids)


def normalize_issue(issue: dict) -> dict:
    """Привести эталонную ошибку к внутреннему виду.

    ``acceptable_evidence_sets`` — список наборов, каждый достаточен целиком.
    Отсутствие наборов означает, что ошибку нельзя подтвердить: такой эталон
    недопустим, и независимый валидатор обязан поймать это до прогона.
    """
    raw_sets = issue.get("acceptable_evidence_sets") or []
    evidence_sets = tuple(sorted(
        (frozenset(group) for group in raw_sets),
        key=lambda group: tuple(sorted(group)),
    ))
    return {
        "issue_id": issue["issue_id"],
        "type": issue["type"],
        "affected_ids": canonical_ids(issue["affected_ids"]),
        "expected_amount_minor": issue["expected_amount_minor"],
        "currency": issue["currency"],
        "acceptable_evidence_sets": evidence_sets,
    }


def normalize_truth(truth: dict) -> tuple[dict, ...]:
    issues = truth.get("issues") or []
    return tuple(normalize_issue(issue) for issue in issues)


def evidence_is_sufficient(
    evidence_ids: object, acceptable_evidence_sets: tuple[frozenset[str], ...]
) -> bool:
    """True, если хотя бы один допустимый набор целиком покрыт заявкой.

    Проверка подмножества, а не равенства и не пересечения. Лишние ID не мешают
    совпадению, но и не заменяют недостающие. Пустой набор доказательств в
    эталоне не бывает: такая ошибка считалась бы подтверждённой чем угодно.
    """
    claimed = canonical_ids(evidence_ids)
    for group in acceptable_evidence_sets:
        if group and group <= claimed:
            return True
    return False


def finding_matches_issue(
    finding: dict,
    issue: dict,
    tolerance_minor: int = AMOUNT_TOLERANCE_MINOR,
) -> bool:
    """Условие ребра «вывод ↔ эталонная ошибка».

    Все пять условий обязательны. ``explanation`` на совпадение не влияет.
    """
    if finding["type"] != issue["type"]:
        return False
    if canonical_ids(finding["affected_ids"]) != issue["affected_ids"]:
        return False
    if finding["currency"] != issue["currency"]:
        return False
    delta = abs(finding["claimed_amount_minor"] - issue["expected_amount_minor"])
    if delta > tolerance_minor:
        return False
    return evidence_is_sufficient(
        finding["evidence_ids"], issue["acceptable_evidence_sets"]
    )


def build_edges(
    findings: tuple[dict, ...],
    issues: tuple[dict, ...],
    tolerance_minor: int = AMOUNT_TOLERANCE_MINOR,
) -> list[Edge]:
    """Рёбра двудольного графа: (индекс вывода, issue_id)."""
    edges: list[Edge] = []
    for index, finding in enumerate(findings):
        for issue in issues:
            if finding_matches_issue(finding, issue, tolerance_minor):
                edges.append((index, issue["issue_id"]))
    return sorted(set(edges))


def _matching_size(edges: list[Edge]) -> int:
    """Размер максимального паросочетания (алгоритм Куна).

    Глубина рекурсии ограничена числом выводов (не более 30), поэтому
    рекурсивная реализация безопасна.
    """
    adjacency: dict[int, list[str]] = {}
    for left, right in edges:
        adjacency.setdefault(left, []).append(right)
    for neighbours in adjacency.values():
        neighbours.sort()

    matched_right: dict[str, int] = {}

    def augment(left: int, visited: set[str]) -> bool:
        for right in adjacency.get(left, ()):
            if right in visited:
                continue
            visited.add(right)
            if right not in matched_right or augment(matched_right[right], visited):
                matched_right[right] = left
                return True
        return False

    size = 0
    for left in sorted(adjacency):
        if augment(left, set()):
            size += 1
    return size


def lexicographic_maximum_matching(edges: list[Edge]) -> list[Edge]:
    """Лексикографически первое максимальное паросочетание.

    Рёбра перебираются в возрастающем порядке. Ребро принимается, если после
    его фиксации максимальное паросочетание остатка всё ещё даёт нужный общий
    размер. Это даёт в точности лексикографически минимальный отсортированный
    список пар, а не просто какое-то детерминированное решение.
    """
    ordered = sorted(set(edges))
    target = _matching_size(ordered)

    chosen: list[Edge] = []
    used_left: set[int] = set()
    used_right: set[str] = set()

    for left, right in ordered:
        if left in used_left or right in used_right:
            continue
        remaining = [
            (a, b)
            for a, b in ordered
            if a != left and b != right and a not in used_left and b not in used_right
        ]
        if len(chosen) + 1 + _matching_size(remaining) == target:
            chosen.append((left, right))
            used_left.add(left)
            used_right.add(right)
            if len(chosen) == target:
                break

    return chosen


@dataclass(frozen=True)
class MatchResult:
    matched_pairs: tuple[Edge, ...]
    unmatched_finding_indexes: tuple[int, ...]
    missed_issue_ids: tuple[str, ...]

    @property
    def tp(self) -> int:
        return len(self.matched_pairs)


def match(
    findings: tuple[dict, ...],
    issues: tuple[dict, ...],
    tolerance_minor: int = AMOUNT_TOLERANCE_MINOR,
) -> MatchResult:
    """Сопоставить заявку с эталоном."""
    edges = build_edges(findings, issues, tolerance_minor)
    pairs = lexicographic_maximum_matching(edges)

    matched_left = {left for left, _ in pairs}
    matched_right = {right for _, right in pairs}

    return MatchResult(
        matched_pairs=tuple(pairs),
        unmatched_finding_indexes=tuple(
            index for index in range(len(findings)) if index not in matched_left
        ),
        missed_issue_ids=tuple(
            issue["issue_id"]
            for issue in issues
            if issue["issue_id"] not in matched_right
        ),
    )
