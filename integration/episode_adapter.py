from copy import deepcopy
from decimal import Decimal


CURRENCY_EXPONENTS = {
    "USD": 2, "EUR": 2, "GBP": 2, "CHF": 2,
    "KZT": 2, "JPY": 0,
}

RULES = {
    "fx": "POLICY-FX",
    "period": "POLICY-PERIOD",
    "allocation": "POLICY-ALLOC",
    "duplicate": "POLICY-DUP",
}


def adapt_episode(episode):
    """Convert our nested generator episode to the official flat schema."""
    manifest = deepcopy(episode["manifest"])
    public = episode["public"]
    private = episode["private"]

    base = manifest["base_currency"]

    manifest["currency_exponents"] = deepcopy(CURRENCY_EXPONENTS)
    manifest["record_counts"] = {
        "ledger": len(public["ledger"]),
        "invoices": len(public["invoices"]),
        "payments": len(public["payments"]),
        "fx": len(public["fx"]),
        "policy": 5,
    }

    invoice_doc_ids = {
        invoice["invoice_id"]: f"DOC-{invoice['invoice_id']}"
        for invoice in public["invoices"]
    }

    invoices = []
    for invoice in public["invoices"]:
        invoices.append({
            "doc_id": invoice_doc_ids[invoice["invoice_id"]],
            "document_number": invoice.get(
                "document_number", invoice["invoice_id"]
            ),
            "invoice_id": invoice["invoice_id"],
            "entity_id": invoice["entity_id"],
            "issued_at": invoice["invoice_date"],
            "due_at": invoice["due_date"],
            "currency": invoice["currency"],
            "total_minor": invoice["total_minor"],
            "line_items": [
                {
                    "line_id": line["line_id"],
                    "obligation_id": line["line_id"],
                    "description": line["description"],
                    "amount_minor": line["line_total_minor"] + (invoice["tax_minor"] if index == len(invoice["line_items"]) - 1 else 0),
                    "service_date": invoice["invoice_date"],
                }
                for index, line in enumerate(invoice["line_items"])
            ],
        })

    payment_doc_ids = {
        payment["payment_id"]: f"DOC-PAY-{payment['payment_id']}"
        for payment in public["payments"]
    }

    payments = []
    for payment in public["payments"]:
        payments.append({
            "doc_id": payment_doc_ids[payment["payment_id"]],
            "bank_reference": payment["bank_reference"],
            "payment_id": payment["payment_id"],
            "timestamp": payment["timestamp"],
            "currency": payment["currency"],
            "amount_minor": payment["amount_minor"],
            "kind": payment.get("payment_type", "payment"),
            "original_payment_id": payment.get("related_payment_id"),
            "invoice_refs": [
                {
                    "invoice_id": allocation["invoice_id"],
                    "share_minor": allocation["allocated_minor"],
                    "currency": payment["currency"],
                }
                for allocation in payment["allocations"]
            ],
        })

    ledger = []
    for row in public["ledger"]:
        account = row["account"]

        if account == "Operating Expenses":
            role = "expense"
        elif account == "Bank":
            role = "cash"
        elif row["payment_id"] is not None:
            role = "allocation"
        else:
            role = "other"

        amount = row["debit_minor"] or row["credit_minor"]

        ledger.append({
            "row_id": row["entry_id"],
            "journal_id": row["transaction_id"],
            "timestamp": row["timestamp"],
            "account": account,
            "role": role,
            "debit_minor": row["debit_minor"],
            "credit_minor": row["credit_minor"],
            "currency": row["currency"],
            "entity_id": row["entity_id"],
            "invoice_id": row["invoice_id"],
            "payment_id": row["payment_id"],
            "source_doc_id": (
                payment_doc_ids.get(row["payment_id"])
                if row["payment_id"]
                else invoice_doc_ids.get(row["invoice_id"])
            ),
            "source_minor": amount,
            "source_currency": row["currency"],
        })

    fx = [
        {
            "fx_id": row["fx_id"],
            "date": row["date"],
            "source_currency": row["quote_currency"],
            "target_currency": row["base_currency"],
            "rate": row["rate"],
            "reference_rate": row.get("reference_rate", row["rate"]),
        }
        for row in public["fx"]
    ]

    policy = [{
        "policy_id": "POLICY-BASE",
        "accounting_basis": public["policy"]["accounting_basis"],
        "rule_ids": deepcopy(RULES),
    }]

    for key, policy_id in RULES.items():
        policy.append({
            "policy_id": policy_id,
            "rule": key,
            "policy_version": public["policy"]["policy_version"],
        })

    type_map = {
        "duplicate_invoice": "duplicate_invoice",
        "payment_allocation": "payment_allocation",
        "fx_rate": "fx_conversion",
        "accounting_period": "period_cutoff",
    }

    from validator_official.snapshot import public_snapshot
    from validator_official.reconstruction import reconstruct

    public_episode = {
        "manifest": manifest,
        "ledger": ledger,
        "invoices": invoices,
        "payments": payments,
        "fx": fx,
        "policy": policy,
    }

    from itertools import product

    discrepancies = reconstruct(public_snapshot(public_episode))
    remaining = list(discrepancies)
    issues = []

    for item in private["truth"]:
        expected_kind = type_map[item["type"]]
        expected_ids = set(item.get("affected_ids", []))

        if expected_kind == "period_cutoff":
            invoice_id = next(
                (value for value in expected_ids
                 if value.startswith("INV-") and "-POST-" not in value),
                None,
            )
            matched = [
                d for d in remaining
                if d.kind == expected_kind
                and invoice_id is not None
                and invoice_id in d.keys
            ]
        else:
            matched = next(
                ([d] for d in remaining if d.kind == expected_kind),
                [],
            )

        if not matched:
            raise RuntimeError(
                f"Official reconstruction missed generator error: "
                f"{item['error_id']} ({expected_kind})"
            )

        for discrepancy in matched:
            remaining.remove(discrepancy)

        evidence_sets = [
            sorted(set().union(*variants))
            for variants in product(
                *(d.support_variants for d in matched)
            )
        ]

        issues.append({
            "issue_id": item["error_id"],
            "type": expected_kind,
            "affected_ids": sorted(
                set().union(*(d.keys for d in matched))
            ),
            "expected_amount_minor": sum(
                d.amount_minor for d in matched
            ),
            "currency": matched[0].currency,
            "acceptable_evidence_sets": evidence_sets,
        })

    return {
        "manifest": manifest,
        "ledger": ledger,
        "invoices": invoices,
        "payments": payments,
        "fx": fx,
        "policy": policy,
        "truth": {
            "episode_id": manifest["episode_id"],
            "issues": issues,
        },
        "provenance": deepcopy(private.get("provenance", [])),
    }
