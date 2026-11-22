"""Инварианты публичного снимка.

Задание требует проверять бухгалтерские равенства и отдельно отличать
«сложность» от «противоречивых или неразрешимых данных»: вторые не считаются
сложностью и просто теряют баллы.

Инварианты — то, что обязано держаться **и до, и после** внесения дефектов.
Внесённые дефекты по замыслу сдвигают даты, курсы и распределения, но не ломают
двойную запись: журнал остаётся сбалансированным. Поэтому нарушение инварианта
означает дефект генератора, а не спрятанную ошибку для агента.
"""

from __future__ import annotations

from dataclasses import dataclass

from .arithmetic import company_timezone, local_date
from .snapshot import Snapshot, find_private_keys

CODE_PRIVATE_FIELD = "private_field_in_snapshot"
CODE_JOURNAL_UNBALANCED = "journal_unbalanced"
CODE_INVOICE_TOTAL_MISMATCH = "invoice_total_mismatch"
CODE_DUPLICATE_PUBLIC_ID = "duplicate_public_id"
CODE_DANGLING_REFERENCE = "dangling_reference"
CODE_NON_INTEGER_MONEY = "non_integer_money"
CODE_UNKNOWN_CURRENCY = "unknown_currency_exponent"
CODE_MISSING_FX_FIXING = "missing_fx_fixing"
CODE_RECORD_COUNT_MISMATCH = "record_count_mismatch"
CODE_PERIOD_BOUNDS = "period_bounds_invalid"
CODE_BOTH_SIDES_SET = "row_has_both_debit_and_credit"
CODE_RULE_ID_UNREACHABLE = "policy_rule_id_unreachable"


@dataclass(frozen=True)
class Violation:
    code: str
    detail: str
    ids: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {"code": self.code, "detail": self.detail, "ids": list(self.ids)}


def _is_money(value: object) -> bool:
    return type(value) is int and value >= 0


def check_invariants(snapshot: Snapshot) -> list[Violation]:
    """Все нарушения инвариантов снимка, в детерминированном порядке."""
    violations: list[Violation] = []
    violations += _check_no_private_fields(snapshot)
    violations += _check_period_bounds(snapshot)
    violations += _check_money_fields(snapshot)
    violations += _check_journal_balance(snapshot)
    violations += _check_invoice_totals(snapshot)
    violations += _check_unique_public_ids(snapshot)
    violations += _check_references(snapshot)
    violations += _check_currencies(snapshot)
    violations += _check_fx_coverage(snapshot)
    violations += _check_record_counts(snapshot)
    violations += _check_rule_ids_reachable(snapshot)
    return violations


def _check_no_private_fields(snapshot: Snapshot) -> list[Violation]:
    payload = {
        "manifest": snapshot.manifest,
        "ledger": list(snapshot.ledger),
        "invoices": list(snapshot.invoices),
        "payments": list(snapshot.payments),
        "fx": list(snapshot.fx),
        "policy": list(snapshot.policy),
    }
    return [
        Violation(CODE_PRIVATE_FIELD, f"закрытое поле в публичной выгрузке: {path}")
        for path in sorted(find_private_keys(payload))
    ]


def _check_period_bounds(snapshot: Snapshot) -> list[Violation]:
    if not snapshot.period_start or not snapshot.period_end:
        return [Violation(CODE_PERIOD_BOUNDS, "период не задан в manifest")]
    if snapshot.period_start >= snapshot.period_end:
        return [
            Violation(
                CODE_PERIOD_BOUNDS,
                f"period_start {snapshot.period_start} не раньше period_end "
                f"{snapshot.period_end}",
            )
        ]
    return []


def _check_money_fields(snapshot: Snapshot) -> list[Violation]:
    violations: list[Violation] = []

    for row in snapshot.ledger:
        row_id = str(row.get("row_id"))
        for field in ("debit_minor", "credit_minor"):
            if not _is_money(row.get(field)):
                violations.append(
                    Violation(
                        CODE_NON_INTEGER_MONEY,
                        f"{field}={row.get(field)!r} в строке журнала",
                        (row_id,),
                    )
                )
        if row.get("debit_minor") and row.get("credit_minor"):
            violations.append(
                Violation(
                    CODE_BOTH_SIDES_SET,
                    "строка имеет обе стороны проводки одновременно",
                    (row_id,),
                )
            )

    for invoice in snapshot.invoices:
        if not _is_money(invoice.get("total_minor")):
            violations.append(
                Violation(
                    CODE_NON_INTEGER_MONEY,
                    f"total_minor={invoice.get('total_minor')!r}",
                    (str(invoice.get("invoice_id")),),
                )
            )

    for payment in snapshot.payments:
        if not _is_money(payment.get("amount_minor")):
            violations.append(
                Violation(
                    CODE_NON_INTEGER_MONEY,
                    f"amount_minor={payment.get('amount_minor')!r}",
                    (str(payment.get("payment_id")),),
                )
            )
        for reference in payment.get("invoice_refs") or []:
            if not _is_money(reference.get("share_minor")):
                violations.append(
                    Violation(
                        CODE_NON_INTEGER_MONEY,
                        f"share_minor={reference.get('share_minor')!r}",
                        (str(payment.get("payment_id")),),
                    )
                )

    return violations


def _check_journal_balance(snapshot: Snapshot) -> list[Violation]:
    """Двойная запись: внутри каждого journal_id дебет равен кредиту."""
    totals: dict[str, list[int]] = {}
    for row in snapshot.ledger:
        journal_id = row.get("journal_id")
        if type(journal_id) is not str:
            continue
        debit = row.get("debit_minor") or 0
        credit = row.get("credit_minor") or 0
        if type(debit) is not int or type(credit) is not int:
            continue
        bucket = totals.setdefault(journal_id, [0, 0])
        bucket[0] += debit
        bucket[1] += credit

    return [
        Violation(
            CODE_JOURNAL_UNBALANCED,
            f"дебет {debit} против кредита {credit}",
            (journal_id,),
        )
        for journal_id, (debit, credit) in sorted(totals.items())
        if debit != credit
    ]


def _check_invoice_totals(snapshot: Snapshot) -> list[Violation]:
    violations: list[Violation] = []
    for invoice in snapshot.invoices:
        line_items = invoice.get("line_items") or []
        if not line_items:
            continue
        amounts = [item.get("amount_minor") for item in line_items]
        if any(type(value) is not int for value in amounts):
            continue
        total = sum(amounts)
        if total != invoice.get("total_minor"):
            violations.append(
                Violation(
                    CODE_INVOICE_TOTAL_MISMATCH,
                    f"сумма позиций {total} против total_minor "
                    f"{invoice.get('total_minor')}",
                    (str(invoice.get("invoice_id")),),
                )
            )
    return violations


def _check_unique_public_ids(snapshot: Snapshot) -> list[Violation]:
    violations: list[Violation] = []
    for table, field in (
        ("ledger", "row_id"),
        ("invoices", "invoice_id"),
        ("payments", "payment_id"),
        ("fx", "fx_id"),
        ("policy", "policy_id"),
    ):
        seen: set[str] = set()
        rows = getattr(snapshot, table)
        for row in rows:
            value = row.get(field)
            if type(value) is not str:
                continue
            if value in seen:
                violations.append(
                    Violation(
                        CODE_DUPLICATE_PUBLIC_ID,
                        f"{field} повторяется в таблице {table}",
                        (value,),
                    )
                )
            seen.add(value)

    documents: set[str] = set()
    for collection in (snapshot.invoices, snapshot.payments):
        for record in collection:
            doc_id = record.get("doc_id")
            if type(doc_id) is not str:
                continue
            if doc_id in documents:
                violations.append(
                    Violation(
                        CODE_DUPLICATE_PUBLIC_ID, "doc_id повторяется", (doc_id,)
                    )
                )
            documents.add(doc_id)
    return violations


def _check_references(snapshot: Snapshot) -> list[Violation]:
    """Отсутствующая ссылка — явный null, а не несуществующий ID."""
    invoice_ids = {
        invoice.get("invoice_id")
        for invoice in snapshot.invoices
        if type(invoice.get("invoice_id")) is str
    }
    payment_ids = {
        payment.get("payment_id")
        for payment in snapshot.payments
        if type(payment.get("payment_id")) is str
    }
    doc_ids = {
        record.get("doc_id")
        for collection in (snapshot.invoices, snapshot.payments)
        for record in collection
        if type(record.get("doc_id")) is str
    }

    violations: list[Violation] = []

    for row in snapshot.ledger:
        row_id = str(row.get("row_id"))
        for field, known in (
            ("invoice_id", invoice_ids),
            ("payment_id", payment_ids),
            ("source_doc_id", doc_ids),
        ):
            value = row.get(field)
            if value is None:
                continue
            if value not in known:
                violations.append(
                    Violation(
                        CODE_DANGLING_REFERENCE,
                        f"{field}={value!r} не существует",
                        (row_id,),
                    )
                )

    for payment in snapshot.payments:
        payment_id = str(payment.get("payment_id"))
        original = payment.get("original_payment_id")
        if original is not None and original not in payment_ids:
            violations.append(
                Violation(
                    CODE_DANGLING_REFERENCE,
                    f"original_payment_id={original!r} не существует",
                    (payment_id,),
                )
            )
        for reference in payment.get("invoice_refs") or []:
            invoice_id = reference.get("invoice_id")
            if invoice_id is not None and invoice_id not in invoice_ids:
                violations.append(
                    Violation(
                        CODE_DANGLING_REFERENCE,
                        f"invoice_refs ссылается на {invoice_id!r}",
                        (payment_id,),
                    )
                )

    return violations


def _check_currencies(snapshot: Snapshot) -> list[Violation]:
    declared = set((snapshot.manifest.get("currency_exponents") or {}).keys())
    if not declared:
        return [
            Violation(CODE_UNKNOWN_CURRENCY, "currency_exponents отсутствует в manifest")
        ]

    used: set[str] = {snapshot.base_currency}
    for row in snapshot.ledger:
        for field in ("currency", "source_currency"):
            value = row.get(field)
            if type(value) is str:
                used.add(value)
    for collection in (snapshot.invoices, snapshot.payments):
        for record in collection:
            value = record.get("currency")
            if type(value) is str:
                used.add(value)
    for row in snapshot.fx:
        for field in ("source_currency", "target_currency"):
            value = row.get(field)
            if type(value) is str:
                used.add(value)

    return [
        Violation(CODE_UNKNOWN_CURRENCY, f"разрядность валюты {code} не объявлена")
        for code in sorted(used - declared)
    ]


def _check_fx_coverage(snapshot: Snapshot) -> list[Violation]:
    """Для каждой валютной строки платежа нужен фиксинг на дату платежа."""
    if not snapshot.period_start:
        return []
    tz = company_timezone(snapshot.period_start)
    payment_by_id = {
        payment.get("payment_id"): payment for payment in snapshot.payments
    }

    violations: list[Violation] = []
    for row in snapshot.ledger:
        source_currency = row.get("source_currency")
        if type(source_currency) is not str:
            continue
        if source_currency == snapshot.base_currency:
            continue
        payment = payment_by_id.get(row.get("payment_id"))
        timestamp = payment["timestamp"] if payment else row.get("timestamp")
        if type(timestamp) is not str:
            continue
        day = local_date(timestamp, tz)
        if snapshot.fx_rate(source_currency, snapshot.base_currency, day.isoformat()):
            continue
        violations.append(
            Violation(
                CODE_MISSING_FX_FIXING,
                f"нет фиксинга {source_currency}->{snapshot.base_currency} "
                f"на {day.isoformat()}",
                (str(row.get("row_id")),),
            )
        )
    return violations


def _check_record_counts(snapshot: Snapshot) -> list[Violation]:
    declared = snapshot.manifest.get("record_counts") or {}
    actual = {
        "ledger": len(snapshot.ledger),
        "invoices": len(snapshot.invoices),
        "payments": len(snapshot.payments),
    }
    return [
        Violation(
            CODE_RECORD_COUNT_MISMATCH,
            f"manifest обещает {declared[table]} записей в {table}, фактически "
            f"{actual[table]}",
        )
        for table in sorted(actual)
        if table in declared and declared[table] != actual[table]
    ]


def _check_rule_ids_reachable(snapshot: Snapshot) -> list[Violation]:
    """ID правил политики должны быть получаемы через get_record."""
    available = {
        record.get("policy_id")
        for record in snapshot.policy
        if type(record.get("policy_id")) is str
    }
    return [
        Violation(
            CODE_RULE_ID_UNREACHABLE,
            f"правило {name} объявлено как {rule_id}, но записи с таким "
            "policy_id нет",
            (rule_id,),
        )
        for name, rule_id in sorted(snapshot.rule_ids.items())
        if rule_id not in available
    ]
