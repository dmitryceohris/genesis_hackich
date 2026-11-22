"""Oracle: эталонная заявка, собираемая на стороне оценщика.

Задание: «Oracle только для оценщика». Поэтому это не политика и это не живёт
в ``policies/``: функция вызывается доверенным процессом вне контейнера агента
и проверяет максимум награды, а не способность агента.

Политика, которая читает ``truth.json``, — ровно та архитектура, из которой
эталон утекает в процесс агента, а утечка закрытых данных по критериям
блокирует оценивание целиком.
"""

from __future__ import annotations

from .matching import normalize_truth


def build_oracle_submission(truth: dict, *, evidence_set_index: int = 0) -> dict:
    """Собрать заявку, которая обязана дать TP по каждой эталонной ошибке.

    Для каждой ошибки берётся один полный допустимый набор доказательств.
    Наборы отсортированы в ``normalize_truth``, поэтому выбор детерминирован и
    не зависит от порядка ключей в файле эталона.

    ``evidence_set_index`` позволяет прогнать oracle по альтернативным наборам:
    если ошибка подтверждается двумя разными способами, оба обязаны давать
    одинаковую награду.
    """
    issues = normalize_truth(truth)
    findings = []

    for issue in issues:
        evidence_sets = issue["acceptable_evidence_sets"]
        if not evidence_sets:
            raise ValueError(
                f"issue {issue['issue_id']!r} has no acceptable evidence sets: "
                "такой эталон недоказуем и не должен попадать в прогон"
            )
        chosen = evidence_sets[evidence_set_index % len(evidence_sets)]
        findings.append(
            {
                "type": issue["type"],
                "affected_ids": sorted(issue["affected_ids"]),
                "claimed_amount_minor": issue["expected_amount_minor"],
                "currency": issue["currency"],
                "evidence_ids": sorted(chosen),
                "explanation": f"oracle: {issue['type']}",
            }
        )

    return {"episode_id": truth["episode_id"], "findings": findings}
