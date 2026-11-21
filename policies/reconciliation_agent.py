"""Простой алгоритм сверки.

Задача политики — не быть сильным аудитором, а доказать две вещи:

1. каждый дефект восстанавливается из публичных наблюдений, то есть эпизод
   решаем и эталон не требует недоступного факта;
2. достаточный набор доказательств действительно достижим через инструменты в
   пределах бюджета шагов.

Поэтому здесь нет эвристик «похоже на подозрительное»: четыре проверки
повторяют опубликованные правила политики своим кодом и прикладывают те записи,
которыми вывод подтверждается.
"""

from __future__ import annotations

from datetime import date

from evaluator.contract import MAX_FINDINGS

from .base import (
    Policy,
    base_currency_of,
    currency_exponents_of,
    episode_id_of,
    submit,
)
from .money import company_timezone, convert_minor, in_period, local_date, row_amount_minor

DEFAULT_RULE_IDS = {
    "fx": "POLICY-FX",
    "period": "POLICY-PERIOD",
    "allocation": "POLICY-ALLOC",
    "duplicate": "POLICY-DUP",
}


class ReconciliationAgent(Policy):
    name = "reconcile"

    def run(self, observation):
        episode_id = episode_id_of(observation)
        manifest = observation.get("manifest") or {}
        policy_doc = observation.get("policy") or {}
        base_currency = base_currency_of(observation)
        exponents = currency_exponents_of(observation)
        rule_ids = {**DEFAULT_RULE_IDS, **(policy_doc.get("rule_ids") or {})}

        period_start = manifest.get("period_start")
        period_end = manifest.get("period_end")
        if not period_start or not period_end:
            yield submit(episode_id, [])
            return
        tz = company_timezone(period_start)

        ledger, observation = yield from self.fetch_table("ledger", observation)
        invoices, observation = yield from self.fetch_table("invoices", observation)
        payments, observation = yield from self.fetch_table("payments", observation)
        fx_rows, observation = yield from self.fetch_table("fx", observation)

        # Если среда не отдаёт позиции счёта в листинге, они берутся из
        # документа. Обе формы допустимы контрактом, поэтому поддержаны обе.
        detailed: list[dict] = []
        for invoice in invoices:
            if invoice.get("line_items"):
                detailed.append(invoice)
                continue
            doc_id = invoice.get("doc_id")
            if not doc_id:
                continue
            document, observation = yield from self.fetch_document(doc_id, observation)
            detailed.append(document or invoice)

        context = _Context(
            ledger=ledger,
            invoices=detailed,
            payments=payments,
            fx_rows=fx_rows,
            base_currency=base_currency,
            exponents=exponents,
            rule_ids=rule_ids,
            period_start=period_start,
            period_end=period_end,
            tz=tz,
        )

        findings = (
            _detect_period_cutoff(context)
            + _detect_duplicate_invoices(context)
            + _detect_payment_allocation(context)
            + _detect_fx_conversion(context)
        )

        yield submit(episode_id, findings[:MAX_FINDINGS])


class _Context:
    def __init__(
        self,
        ledger,
        invoices,
        payments,
        fx_rows,
        base_currency,
        exponents,
        rule_ids,
        period_start,
        period_end,
        tz,
    ) -> None:
        self.ledger = ledger
        self.invoices = invoices
        self.payments = payments
        self.fx_rows = fx_rows
        self.base_currency = base_currency
        self.exponents = exponents
        self.rule_ids = rule_ids
        self.period_start = period_start
        self.period_end = period_end
        self.tz = tz

        self.rows_by_invoice: dict[str, list[dict]] = {}
        for row in ledger:
            invoice_id = row.get("invoice_id")
            if invoice_id:
                self.rows_by_invoice.setdefault(invoice_id, []).append(row)

        self.payment_by_id = {
            payment.get("payment_id"): payment for payment in payments
        }
        self.invoice_by_id = {
            invoice.get("invoice_id"): invoice for invoice in invoices
        }

    def exponent(self, currency: str) -> int:
        return self.exponents.get(currency, 2)

    def expense_rows(self, invoice_id: str) -> list[dict]:
        return [
            row
            for row in self.rows_by_invoice.get(invoice_id, [])
            if row.get("role") == "expense"
        ]

    def fx_rate(self, source: str, target: str, day: date) -> dict | None:
        """Фиксинг на требуемую дату. Курс иной даты не подставляется."""
        wanted = day.isoformat()
        for row in self.fx_rows:
            if (
                row.get("source_currency") == source
                and row.get("target_currency") == target
                and row.get("date") == wanted
            ):
                return row
        return None


def _finding(issue_type, affected_ids, amount_minor, currency, evidence_ids, explanation):
    return {
        "type": issue_type,
        "affected_ids": list(affected_ids),
        "claimed_amount_minor": int(amount_minor),
        "currency": currency,
        "evidence_ids": [value for value in evidence_ids if value],
        "explanation": explanation[:1000],
    }


def _detect_period_cutoff(context: _Context) -> list[dict]:
    """Услуга внутри периода, а признание расхода — за его границей."""
    findings = []
    for invoice in context.invoices:
        invoice_id = invoice.get("invoice_id")
        line_items = invoice.get("line_items") or []
        service_days = [
            date.fromisoformat(item["service_date"])
            for item in line_items
            if item.get("service_date")
        ]
        if not invoice_id or not service_days:
            continue
        service_day = max(service_days)
        if not in_period(service_day, context.period_start, context.period_end, context.tz):
            continue

        for row in context.expense_rows(invoice_id):
            recognition_day = local_date(row["timestamp"], context.tz)
            if in_period(recognition_day, context.period_start, context.period_end, context.tz):
                continue
            findings.append(
                _finding(
                    "period_cutoff",
                    [invoice_id, row["row_id"]],
                    row_amount_minor(row),
                    row.get("currency") or context.base_currency,
                    [invoice.get("doc_id"), row["row_id"], context.rule_ids["period"]],
                    (
                        f"Услуга оказана {service_day.isoformat()}, расход проведён "
                        f"{recognition_day.isoformat()}. По политике признание "
                        "относится к отчётному периоду услуги."
                    ),
                )
            )
    return findings


def _detect_duplicate_invoices(context: _Context) -> list[dict]:
    """Одно обязательство выставлено и проведено дважды."""
    groups: dict[tuple, list[dict]] = {}
    for invoice in context.invoices:
        obligations = frozenset(
            item.get("obligation_id")
            for item in invoice.get("line_items") or []
            if item.get("obligation_id")
        )
        if not obligations:
            continue
        groups.setdefault((invoice.get("entity_id"), obligations), []).append(invoice)

    findings = []
    for key in sorted(groups, key=lambda item: (str(item[0]), tuple(sorted(item[1])))):
        group = groups[key]
        if len(group) < 2:
            continue
        ordered = sorted(
            group,
            key=lambda invoice: (
                invoice.get("issued_at") or "",
                invoice.get("invoice_id") or "",
            ),
        )
        original = ordered[0]
        for duplicate in ordered[1:]:
            rows = context.expense_rows(duplicate.get("invoice_id"))
            if not rows:
                # Второй счёт выставлен, но не проведён: расхода нет.
                continue
            row = rows[0]
            findings.append(
                _finding(
                    "duplicate_invoice",
                    [duplicate["invoice_id"], row["row_id"]],
                    row_amount_minor(row),
                    row.get("currency") or context.base_currency,
                    [
                        original.get("doc_id"),
                        duplicate.get("doc_id"),
                        row["row_id"],
                        context.rule_ids["duplicate"],
                    ],
                    (
                        f"Обязательство из {original.get('invoice_id')} повторно "
                        f"выставлено счётом {duplicate.get('invoice_id')} и проведено "
                        "второй раз."
                    ),
                )
            )
    return findings


def _detect_payment_allocation(context: _Context) -> list[dict]:
    """Назначение платежа в документе расходится с распределением в журнале."""
    findings = []
    for payment in context.payments:
        payment_id = payment.get("payment_id")
        if not payment_id:
            continue
        payment_day = local_date(payment["timestamp"], context.tz)

        for reference in payment.get("invoice_refs") or []:
            invoice_id = reference.get("invoice_id")
            stated = reference.get("share_minor")
            if not invoice_id or type(stated) is not int:
                continue
            share_currency = reference.get("currency") or payment.get("currency")

            allocation_rows = [
                row
                for row in context.ledger
                if row.get("payment_id") == payment_id
                and row.get("invoice_id") == invoice_id
                and row.get("role") == "allocation"
            ]
            allocated = sum(
                row.get("source_minor")
                if row.get("source_minor") is not None
                else row_amount_minor(row)
                for row in allocation_rows
            )
            missing = stated - allocated
            if missing <= 0:
                continue

            # Недостающая доля переоценивается по верному курсу, а не по тому,
            # который применён в журнале: иначе ошибка FX исказит эту сумму.
            if share_currency == context.base_currency:
                amount = missing
                fx_row = None
            else:
                fx_row = context.fx_rate(share_currency, context.base_currency, payment_day)
                if fx_row is None:
                    continue
                amount = convert_minor(
                    missing,
                    fx_row["rate"],
                    context.exponent(share_currency),
                    context.exponent(context.base_currency),
                )

            suspense_rows = [
                row
                for row in context.ledger
                if row.get("payment_id") == payment_id and row.get("role") == "suspense"
            ]
            evidence = [payment.get("doc_id")]
            evidence += [row["row_id"] for row in allocation_rows]
            evidence += [row["row_id"] for row in suspense_rows]
            evidence.append(context.rule_ids["allocation"])

            findings.append(
                _finding(
                    "payment_allocation",
                    [invoice_id, payment_id],
                    amount,
                    context.base_currency,
                    evidence,
                    (
                        f"По документу на {invoice_id} отнесено {stated} минимальных "
                        f"единиц, в журнале распределено {allocated}. Недостающая "
                        "доля осталась вне счёта."
                    ),
                )
            )
    return findings


def _detect_fx_conversion(context: _Context) -> list[dict]:
    """Денежная строка оценена не по тому курсу или не на ту дату.

    Проверяются только строки с ролью ``cash``: по соглашению эпизода FX-ошибка
    объявляется один раз и ключуется платежом и денежной строкой, а не каждой
    переоценённой строкой журнала.
    """
    findings = []
    for row in context.ledger:
        if row.get("role") != "cash":
            continue
        source_currency = row.get("source_currency")
        source_minor = row.get("source_minor")
        if not source_currency or source_currency == context.base_currency:
            continue
        if type(source_minor) is not int:
            continue

        payment = context.payment_by_id.get(row.get("payment_id"))
        rate_day = local_date(
            payment["timestamp"] if payment else row["timestamp"], context.tz
        )
        fx_row = context.fx_rate(source_currency, context.base_currency, rate_day)
        if fx_row is None:
            continue

        expected = convert_minor(
            source_minor,
            fx_row["rate"],
            context.exponent(source_currency),
            context.exponent(context.base_currency),
        )
        recorded = row_amount_minor(row)
        difference = abs(expected - recorded)
        if difference == 0:
            continue

        findings.append(
            _finding(
                "fx_conversion",
                [row.get("payment_id"), row["row_id"]],
                difference,
                context.base_currency,
                [
                    payment.get("doc_id") if payment else None,
                    row["row_id"],
                    fx_row.get("fx_id"),
                    context.rule_ids["fx"],
                ],
                (
                    f"По фиксингу на {rate_day.isoformat()} сумма составляет "
                    f"{expected} минимальных единиц, в журнале отражено {recorded}."
                ),
            )
        )
    return findings
