from datetime import date


def collect_records(env, record_type):
    """Collect every public record using the environment action API."""
    records = []
    offset = 0

    while True:
        observation, _, terminated, truncated, _ = env.step({
            "type": "list_records",
            "record_type": record_type,
            "offset": offset,
            "limit": 50,
        })

        if terminated or truncated:
            break

        result = observation.get("result", {})
        page = result.get("records", [])
        records.extend(page)

        if not result.get("has_more"):
            break

        offset += 50

    return records


def collect_public_data(env):
    return {
        "ledger": collect_records(env, "ledger"),
        "invoices": collect_records(env, "invoices"),
        "payments": collect_records(env, "payments"),
        "fx": collect_records(env, "fx"),
    }


def detect_findings(data, manifest):
    findings = []

    # 1. Duplicate invoices: same document number.
    groups = {}
    for invoice in data["invoices"]:
        number = invoice.get("document_number")
        if number:
            groups.setdefault(number, []).append(invoice)

    for group in groups.values():
        if len(group) < 2:
            continue

        first = group[0]
        for duplicate in group[1:]:
            same_details = all(
                first.get(field) == duplicate.get(field)
                for field in (
                    "entity_id", "counterparty", "direction",
                    "invoice_date", "currency", "total_minor",
                )
            )

            if same_details:
                findings.append({
                    "type": "duplicate_invoice",
                    "affected_ids": [
                        first["invoice_id"],
                        duplicate["invoice_id"],
                    ],
                    "evidence_ids": [
                        first["invoice_id"],
                        duplicate["invoice_id"],
                    ],
                    "explanation": "Matching document number and financial details.",
                })

    # 2. Payment allocation: amount must reconcile to allocations.
    for payment in data["payments"]:
        allocations = payment.get("allocations", [])
        if not allocations:
            continue

        allocated = sum(
            item.get("allocated_minor", 0)
            for item in allocations
        )
        amount = payment.get("amount_minor", 0)

        if amount > allocated:
            for allocation in allocations:
                invoice_id = allocation.get("invoice_id")
                if not invoice_id:
                    continue

                findings.append({
                    "type": "payment_allocation",
                    "affected_ids": [
                        payment["payment_id"],
                        invoice_id,
                    ],
                    "evidence_ids": [
                        payment["payment_id"],
                        invoice_id,
                    ],
                    "explanation": (
                        f"Payment amount {amount} exceeds allocated "
                        f"amount {allocated}."
                    ),
                })

    # 3. FX rate: compare recorded rate with independent reference.
    for record in data["fx"]:
        try:
            rate = float(record["rate"])
            reference = float(record["reference_rate"])
        except (KeyError, TypeError, ValueError):
            continue

        if reference > 0 and abs(rate - reference) / reference > 0.005:
            findings.append({
                "type": "fx_rate",
                "affected_ids": [record["fx_id"]],
                "evidence_ids": [record["fx_id"]],
                "explanation": "Recorded FX rate differs from reference rate.",
            })

    # 4. Accounting period: invoice postings dated after period end.
    period_start = date.fromisoformat(manifest["period_start"])
    period_end = date.fromisoformat(manifest["period_end"])

    invoice_ids = {
        invoice["invoice_id"]
        for invoice in data["invoices"]
        if period_start <= date.fromisoformat(invoice["invoice_date"]) <= period_end
    }

    for invoice_id in invoice_ids:
        related = [
            row for row in data["ledger"]
            if row.get("invoice_id") == invoice_id
            and row.get("payment_id") is None
        ]

        outside = []
        for row in related:
            try:
                posting_date = date.fromisoformat(row["timestamp"][:10])
            except (KeyError, TypeError, ValueError):
                continue

            if posting_date < period_start or posting_date > period_end:
                outside.append(row)

        if outside:
            affected = [invoice_id] + [
                row["entry_id"] for row in outside
            ]

            findings.append({
                "type": "accounting_period",
                "affected_ids": affected,
                "evidence_ids": affected[:10],
                "explanation": "Invoice postings fall outside the reporting period.",
            })

    # The environment allows at most 30 findings.
    return findings[:30]


def run(env, seed=42):
    observation, _ = env.reset(seed=seed)
    data = collect_public_data(env)
    findings = detect_findings(data, observation["manifest"])

    return env.step({
        "type": "submit",
        "findings": findings,
    })[-1]
