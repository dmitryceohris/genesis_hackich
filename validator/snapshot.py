"""Публичный снимок эпизода и то, что из него достижимо.

Валидатор обязан работать только с тем, что видит агент. Разделение снимка и
эталона здесь не соглашение, а структура: функции восстановления принимают
``snapshot`` и физически не получают ``truth``.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Ключи, которых в публичной выгрузке быть не должно.
PRIVATE_KEYS = frozenset(
    {
        "truth",
        "provenance",
        "seed",
        "issue_id",
        "expected_amount_minor",
        "acceptable_evidence_sets",
        "affected_ids",
        "canary",
    }
)

PUBLIC_TABLES = ("ledger", "invoices", "payments", "fx", "policy")

#: Как публичный ID достаётся через инструменты.
KIND_LEDGER_ROW = "ledger_row"
KIND_INVOICE = "invoice"
KIND_PAYMENT = "payment"
KIND_FX = "fx"
KIND_POLICY = "policy"
KIND_DOCUMENT = "document"


@dataclass(frozen=True)
class Snapshot:
    """То, что доступно агенту: записи, документы и политика."""

    manifest: dict
    ledger: tuple[dict, ...]
    invoices: tuple[dict, ...]
    payments: tuple[dict, ...]
    fx: tuple[dict, ...]
    policy: tuple[dict, ...]

    @property
    def episode_id(self) -> str:
        return self.manifest.get("episode_id", "")

    @property
    def base_currency(self) -> str:
        return self.manifest.get("base_currency", "USD")

    @property
    def period_start(self) -> str:
        return self.manifest.get("period_start", "")

    @property
    def period_end(self) -> str:
        return self.manifest.get("period_end", "")

    @property
    def policy_base(self) -> dict:
        return self.policy[0] if self.policy else {}

    @property
    def rule_ids(self) -> dict[str, str]:
        return dict(self.policy_base.get("rule_ids") or {})

    def exponent(self, currency: str) -> int:
        exponents = self.manifest.get("currency_exponents") or {}
        value = exponents.get(currency)
        return int(value) if value is not None else 2

    def fx_rate(self, source: str, target: str, day: str) -> dict | None:
        for row in self.fx:
            if (
                row.get("source_currency") == source
                and row.get("target_currency") == target
                and row.get("date") == day
            ):
                return row
        return None


def public_snapshot(episode: dict) -> Snapshot:
    """Снять публичную часть эпизода, выбросив всё закрытое."""
    return Snapshot(
        manifest=dict(episode.get("manifest") or {}),
        ledger=tuple(episode.get("ledger") or ()),
        invoices=tuple(episode.get("invoices") or ()),
        payments=tuple(episode.get("payments") or ()),
        fx=tuple(episode.get("fx") or ()),
        policy=tuple(episode.get("policy") or ()),
    )


def reachable_ids(snapshot: Snapshot) -> dict[str, str]:
    """ID, которые агент действительно может получить инструментом.

    Намеренно не включены ``journal_id``, ``entity_id``, ``obligation_id`` и
    ``line_id``: они встречаются в записях, но ни ``get_record``, ни
    ``get_document`` не принимают их как ключ. Эталон, который ссылается на
    такой ID как на доказательство, требует недоступного факта.
    """
    index: dict[str, str] = {}

    for row in snapshot.ledger:
        row_id = row.get("row_id")
        if type(row_id) is str:
            index[row_id] = KIND_LEDGER_ROW

    for invoice in snapshot.invoices:
        invoice_id = invoice.get("invoice_id")
        if type(invoice_id) is str:
            index[invoice_id] = KIND_INVOICE
        doc_id = invoice.get("doc_id")
        if type(doc_id) is str:
            index[doc_id] = KIND_DOCUMENT

    for payment in snapshot.payments:
        payment_id = payment.get("payment_id")
        if type(payment_id) is str:
            index[payment_id] = KIND_PAYMENT
        doc_id = payment.get("doc_id")
        if type(doc_id) is str:
            index[doc_id] = KIND_DOCUMENT

    for row in snapshot.fx:
        fx_id = row.get("fx_id")
        if type(fx_id) is str:
            index[fx_id] = KIND_FX

    for record in snapshot.policy:
        policy_id = record.get("policy_id")
        if type(policy_id) is str:
            index[policy_id] = KIND_POLICY

    return index


def find_private_keys(value, path: str = "") -> list[str]:
    """Найти закрытые ключи в публичной структуре."""
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            where = f"{path}.{key}" if path else str(key)
            if key in PRIVATE_KEYS:
                found.append(where)
            found.extend(find_private_keys(child, where))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(find_private_keys(child, f"{path}[{index}]"))
    return found
