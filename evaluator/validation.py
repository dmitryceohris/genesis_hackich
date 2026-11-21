"""Структурная валидация заявки.

Отдельный путь до метрик: задание говорит, что неверная структура завершает
эпизод с наградой -1 и ошибкой в журнале оценщика. Это не F1 = 0.

Лимиты проверяются до удаления повторов внутри списков, иначе заявку из 31
вывода можно было бы «вылечить» дедупликацией.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .contract import (
    CURRENCY_PATTERN,
    ISSUE_TYPE_SET,
    MAX_EVIDENCE_IDS,
    MAX_EXPLANATION_CHARS,
    MAX_FINDINGS,
    is_strict_int,
    is_strict_str,
)

# Коды причин. Попадают только в закрытый журнал оценщика: агент в закрытом
# режиме видит нейтральный терминальный ответ без детализации.
REASON_NOT_AN_OBJECT = "payload_not_an_object"
REASON_EPISODE_ID_MISSING = "episode_id_missing"
REASON_EPISODE_ID_MISMATCH = "episode_id_mismatch"
REASON_FINDINGS_NOT_A_LIST = "findings_not_a_list"
REASON_TOO_MANY_FINDINGS = "too_many_findings"
REASON_FINDING_NOT_AN_OBJECT = "finding_not_an_object"
REASON_UNKNOWN_TYPE = "unknown_type"
REASON_AFFECTED_IDS_INVALID = "affected_ids_invalid"
REASON_AMOUNT_NOT_INT = "claimed_amount_minor_not_int"
REASON_CURRENCY_INVALID = "currency_invalid"
REASON_EVIDENCE_IDS_INVALID = "evidence_ids_invalid"
REASON_TOO_MANY_EVIDENCE_IDS = "too_many_evidence_ids"
REASON_EXPLANATION_INVALID = "explanation_invalid"
REASON_EXPLANATION_TOO_LONG = "explanation_too_long"


@dataclass(frozen=True)
class Validation:
    """Результат структурной проверки."""

    ok: bool
    reason: str | None = None
    detail: str | None = None
    #: Индекс проблемного вывода, если причина локальна.
    finding_index: int | None = None
    #: Заявка, приведённая к внутреннему виду. Заполняется только при ok.
    findings: tuple[dict, ...] = field(default=())


def _invalid(reason: str, detail: str, index: int | None = None) -> Validation:
    return Validation(ok=False, reason=reason, detail=detail, finding_index=index)


def _is_list_of_strings(value: object) -> bool:
    return type(value) is list and all(is_strict_str(item) for item in value)


def validate_submission(payload: object, episode_id: str) -> Validation:
    """Проверить заявку на структуру и лимиты.

    Возвращает Validation. При ok=False вызывающая сторона обязана выдать
    итог -1 и не считать метрики.

    Неизвестные дополнительные ключи игнорируются: задание не требует их
    запрещать, а строгость сверх контракта делает оценщик хрупким.
    """
    if type(payload) is not dict:
        return _invalid(REASON_NOT_AN_OBJECT, f"got {type(payload).__name__}")

    if "episode_id" not in payload:
        return _invalid(REASON_EPISODE_ID_MISSING, "field absent")
    claimed_episode = payload["episode_id"]
    if not is_strict_str(claimed_episode) or claimed_episode != episode_id:
        return _invalid(
            REASON_EPISODE_ID_MISMATCH,
            f"expected {episode_id!r}, got {claimed_episode!r}",
        )

    raw_findings = payload.get("findings")
    if type(raw_findings) is not list:
        return _invalid(
            REASON_FINDINGS_NOT_A_LIST, f"got {type(raw_findings).__name__}"
        )

    # Лимит на число выводов — до любой нормализации.
    if len(raw_findings) > MAX_FINDINGS:
        return _invalid(
            REASON_TOO_MANY_FINDINGS, f"{len(raw_findings)} > {MAX_FINDINGS}"
        )

    normalized: list[dict] = []
    for index, raw in enumerate(raw_findings):
        validation = _validate_finding(raw, index)
        if not validation.ok:
            return validation
        normalized.append(validation.findings[0])

    return Validation(ok=True, findings=tuple(normalized))


def _validate_finding(raw: object, index: int) -> Validation:
    if type(raw) is not dict:
        return _invalid(
            REASON_FINDING_NOT_AN_OBJECT, f"got {type(raw).__name__}", index
        )

    issue_type = raw.get("type")
    if not is_strict_str(issue_type) or issue_type not in ISSUE_TYPE_SET:
        return _invalid(REASON_UNKNOWN_TYPE, f"got {issue_type!r}", index)

    affected_ids = raw.get("affected_ids")
    if not _is_list_of_strings(affected_ids) or len(affected_ids) == 0:
        return _invalid(
            REASON_AFFECTED_IDS_INVALID, "must be a non-empty list of strings", index
        )

    amount = raw.get("claimed_amount_minor")
    if not is_strict_int(amount):
        # bool сюда не проходит: см. contract.is_strict_int.
        return _invalid(REASON_AMOUNT_NOT_INT, f"got {amount!r}", index)

    currency = raw.get("currency")
    if not is_strict_str(currency) or not CURRENCY_PATTERN.match(currency):
        return _invalid(REASON_CURRENCY_INVALID, f"got {currency!r}", index)

    evidence_ids = raw.get("evidence_ids")
    if not _is_list_of_strings(evidence_ids):
        # Пустой список структурно допустим: он просто ничего не подтверждает.
        return _invalid(
            REASON_EVIDENCE_IDS_INVALID, "must be a list of strings", index
        )
    if len(evidence_ids) > MAX_EVIDENCE_IDS:
        return _invalid(
            REASON_TOO_MANY_EVIDENCE_IDS,
            f"{len(evidence_ids)} > {MAX_EVIDENCE_IDS}",
            index,
        )

    explanation = raw.get("explanation")
    if not is_strict_str(explanation):
        return _invalid(REASON_EXPLANATION_INVALID, f"got {explanation!r}", index)
    if len(explanation) > MAX_EXPLANATION_CHARS:
        return _invalid(
            REASON_EXPLANATION_TOO_LONG,
            f"{len(explanation)} > {MAX_EXPLANATION_CHARS}",
            index,
        )

    finding = {
        "type": issue_type,
        "affected_ids": tuple(affected_ids),
        "claimed_amount_minor": amount,
        "currency": currency,
        "evidence_ids": tuple(evidence_ids),
        "explanation": explanation,
    }
    return Validation(ok=True, findings=(finding,))
