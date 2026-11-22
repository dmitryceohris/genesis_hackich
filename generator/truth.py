
from generator.error_injection import ERROR_TYPES


def validate_truth(
    truth: list[dict],
    provenance: list[dict],
    ledger: list[dict],
    invoices: list[dict],
    payments: list[dict],
    fx: list[dict],
) -> bool:

    if len(truth) > 30:
        raise ValueError("Truth cannot contain more than 30 findings")

    if len(truth) != len(provenance):
        raise ValueError("Truth and provenance counts differ")

    evidence_index = set()

    for invoice in invoices:
        evidence_index.add(invoice["invoice_id"])

    for payment in payments:
        evidence_index.add(payment["payment_id"])

    for row in ledger:
        evidence_index.add(row["entry_id"])

    for record in fx:
        if "fx_id" in record:
            evidence_index.add(record["fx_id"])

    truth_ids = set()
    provenance_ids = set()

    for finding in truth:
        required = {
            "error_id",
            "type",
            "affected_ids",
            "claimed_amount_minor",
            "currency",
            "evidence_ids",
            "explanation",
        }

        missing = required - set(finding)

        if missing:
            raise ValueError(
                f"Truth finding missing fields: {missing}"
            )

        error_id = finding["error_id"]

        if error_id in truth_ids:
            raise ValueError(f"Duplicate truth ID: {error_id}")

        truth_ids.add(error_id)

        if finding["type"] not in ERROR_TYPES:
            raise ValueError(
                f"Unknown truth error type: {finding['type']}"
            )

        if len(finding["evidence_ids"]) > 10:
            raise ValueError(
                f"Too many evidence IDs in {error_id}"
            )

        if len(finding["explanation"]) > 1000:
            raise ValueError(
                f"Explanation too long in {error_id}"
            )

        if not finding["evidence_ids"]:
            raise ValueError(
                f"Finding has no evidence: {error_id}"
            )

        for evidence_id in finding["evidence_ids"]:
            if evidence_id not in evidence_index:
                raise ValueError(
                    f"Unknown evidence ID: {evidence_id}"
                )

        for affected_id in finding["affected_ids"]:
            if affected_id not in evidence_index:
                raise ValueError(
                    f"Unknown affected ID: {affected_id}"
                )

        amount = finding["claimed_amount_minor"]

        if amount is not None:
            if not isinstance(amount, int) or isinstance(amount, bool):
                raise ValueError(
                    f"Invalid amount in {error_id}"
                )

            if amount < 0:
                raise ValueError(
                    f"Negative amount in {error_id}"
                )

    for record in provenance:
        required = {
            "error_id",
            "type",
            "operation",
            "source_ids",
            "generated_ids",
        }

        missing = required - set(record)

        if missing:
            raise ValueError(
                f"Provenance record missing fields: {missing}"
            )

        error_id = record["error_id"]

        if error_id in provenance_ids:
            raise ValueError(
                f"Duplicate provenance ID: {error_id}"
            )

        provenance_ids.add(error_id)

    if truth_ids != provenance_ids:
        raise ValueError(
            "Truth and provenance IDs do not match"
        )

    return True
