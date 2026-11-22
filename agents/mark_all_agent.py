from agents.reconciliation_agent import collect_public_data


def run(env, seed=42):
    """Intentionally overinclusive baseline for comparison."""
    observation, _ = env.reset(seed=seed)
    data = collect_public_data(env)

    findings = []

    # Deliberately labels invoice pairs as duplicates, even without proof.
    invoices = data["invoices"]
    for index in range(0, len(invoices) - 1, 2):
        findings.append({
            "type": "duplicate_invoice",
            "affected_ids": [
                invoices[index]["invoice_id"],
                invoices[index + 1]["invoice_id"],
            ],
            "evidence_ids": [
                invoices[index]["invoice_id"],
                invoices[index + 1]["invoice_id"],
            ],
            "explanation": "Mark-all baseline guess.",
        })

        if len(findings) >= 10:
            break

    # Labels the first payment-allocation candidates indiscriminately.
    for payment in data["payments"][:10]:
        allocations = payment.get("allocations", [])
        if allocations and len(findings) < 20:
            findings.append({
                "type": "payment_allocation",
                "affected_ids": [
                    payment["payment_id"],
                    allocations[0]["invoice_id"],
                ],
                "evidence_ids": [
                    payment["payment_id"],
                    allocations[0]["invoice_id"],
                ],
                "explanation": "Mark-all baseline guess.",
            })

    # Adds arbitrary FX candidates.
    for record in data["fx"][:10]:
        if len(findings) >= 30:
            break

        findings.append({
            "type": "fx_rate",
            "affected_ids": [record["fx_id"]],
            "evidence_ids": [record["fx_id"]],
            "explanation": "Mark-all baseline guess.",
        })

    return env.step({
        "type": "submit",
        "findings": findings,
    })[-1]
