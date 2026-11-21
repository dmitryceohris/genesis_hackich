"""Атака «пометить всё».

Политика существует, чтобы проверить штраф за ложные обвинения. Она обязана
набрать как можно больше структурно валидных выводов: заявка из 31 вывода
завершилась бы с итогом −1, и тест проверял бы валидацию, а не стоимость FP.

Отдельный параметр ``max_findings`` позволяет построить и заведомо невалидную
заявку — но это другой тест.
"""

from __future__ import annotations

from evaluator.contract import ISSUE_TYPES, MAX_FINDINGS

from .base import Policy, base_currency_of, episode_id_of, submit


class MarkAllAgent(Policy):
    name = "flag_all"

    def __init__(self, max_findings: int = MAX_FINDINGS) -> None:
        self.max_findings = max_findings

    def run(self, observation):
        episode_id = episode_id_of(observation)
        base_currency = base_currency_of(observation)

        ledger, observation = yield from self.fetch_table("ledger", observation)
        invoices, observation = yield from self.fetch_table("invoices", observation)
        payments, observation = yield from self.fetch_table("payments", observation)

        findings = self._build(ledger, invoices, payments, base_currency)
        yield submit(episode_id, findings[: self.max_findings])

    def _build(self, ledger, invoices, payments, base_currency) -> list[dict]:
        findings: list[dict] = []
        row_ids = [row.get("row_id") for row in ledger if row.get("row_id")]

        # По каждому счёту обвинение каждого типа: максимально широкая разметка
        # из того, что видно в наблюдениях.
        for invoice in invoices:
            invoice_id = invoice.get("invoice_id")
            doc_id = invoice.get("doc_id")
            if not invoice_id:
                continue
            related = [
                row.get("row_id")
                for row in ledger
                if row.get("invoice_id") == invoice_id and row.get("row_id")
            ]
            anchor = related[0] if related else (row_ids[0] if row_ids else invoice_id)
            amount = invoice.get("total_minor")
            if type(amount) is not int:
                amount = 0
            for issue_type in ISSUE_TYPES:
                findings.append(
                    {
                        "type": issue_type,
                        "affected_ids": [invoice_id, anchor],
                        "claimed_amount_minor": amount,
                        "currency": base_currency,
                        "evidence_ids": [value for value in (doc_id, anchor) if value],
                        "explanation": "flag_all baseline: обвинение без проверки",
                    }
                )

        for payment in payments:
            payment_id = payment.get("payment_id")
            if not payment_id:
                continue
            amount = payment.get("amount_minor")
            if type(amount) is not int:
                amount = 0
            related = [
                row.get("row_id")
                for row in ledger
                if row.get("payment_id") == payment_id and row.get("row_id")
            ]
            anchor = related[0] if related else payment_id
            findings.append(
                {
                    "type": "payment_allocation",
                    "affected_ids": [payment_id, anchor],
                    "claimed_amount_minor": amount,
                    "currency": base_currency,
                    "evidence_ids": [
                        value for value in (payment.get("doc_id"), anchor) if value
                    ],
                    "explanation": "flag_all baseline: обвинение без проверки",
                }
            )

        return findings
