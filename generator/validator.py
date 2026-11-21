
from datetime import date, datetime
from decimal import Decimal, InvalidOperation


def _require(condition: bool, message: str):
    if not condition:
        raise ValueError(message)


def _parse_date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid date in {field}: {value}")


def _parse_timestamp(value: str, field: str) -> datetime:
    try:
        result = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid timestamp in {field}: {value}")

    _require(
        result.tzinfo is not None and result.utcoffset() is not None,
        f"Timestamp must include timezone: {field}",
    )
    return result


def _unique(values: list, label: str):
    _require(
        len(values) == len(set(values)),
        f"Duplicate {label}",
    )


def _check_ledger_balance(ledger: list[dict]):
    transactions = {}

    for row in ledger:
        debit = row["debit_minor"]
        credit = row["credit_minor"]

        _require(
            isinstance(debit, int) and not isinstance(debit, bool),
            f"Invalid debit in {row['entry_id']}",
        )
        _require(
            isinstance(credit, int) and not isinstance(credit, bool),
            f"Invalid credit in {row['entry_id']}",
        )
        _require(debit >= 0 and credit >= 0, "Negative ledger amount")
        _require(
            (debit > 0) != (credit > 0),
            f"Entry must have exactly one non-zero side: {row['entry_id']}",
        )

        key = (row["transaction_id"], row["currency"])
        totals = transactions.setdefault(
            key,
            {"debit": 0, "credit": 0},
        )
        totals["debit"] += debit
        totals["credit"] += credit

    for key, totals in transactions.items():
        _require(
            totals["debit"] == totals["credit"],
            f"Unbalanced transaction: {key}",
        )


def validate_clean_data(
    manifest: dict,
    ledger: list[dict],
    invoices: list[dict],
    payments: list[dict],
    fx: list[dict],
):
    start = _parse_date(manifest["period_start"], "period_start")
    end = _parse_date(manifest["period_end"], "period_end")

    _require(start <= end, "Invalid reporting period")
    _require(200 <= len(ledger) <= 2000, "Ledger must contain 200-2000 rows")
    _require(
        20 <= len(invoices) + len(payments) <= 200,
        "Documents must contain 20-200 records",
    )

    invoice_ids = [item["invoice_id"] for item in invoices]
    payment_ids = [item["payment_id"] for item in payments]
    entry_ids = [item["entry_id"] for item in ledger]

    _unique(invoice_ids, "invoice IDs")
    _unique(payment_ids, "payment IDs")
    _unique(entry_ids, "ledger entry IDs")

    invoice_map = {
        item["invoice_id"]: item
        for item in invoices
    }
    payment_map = {
        item["payment_id"]: item
        for item in payments
    }

    # Validate invoices
    for invoice in invoices:
        invoice_date = _parse_date(
            invoice["invoice_date"],
            "invoice_date",
        )
        due_date = _parse_date(
            invoice["due_date"],
            "due_date",
        )

        _require(start <= invoice_date <= end, "Invoice outside reporting period")
        _require(due_date >= invoice_date, "Due date precedes invoice date")
        _require(
            invoice["subtotal_minor"] ==
            sum(line["line_total_minor"] for line in invoice["line_items"]),
            f"Invoice line total mismatch: {invoice['invoice_id']}",
        )
        _require(
            invoice["total_minor"] ==
            invoice["subtotal_minor"] + invoice["tax_minor"],
            f"Invoice total mismatch: {invoice['invoice_id']}",
        )

        expected_tax = (
            invoice["subtotal_minor"] * invoice["tax_rate_bps"] + 5000
        ) // 10000

        _require(
            invoice["tax_minor"] == expected_tax,
            f"Invoice tax mismatch: {invoice['invoice_id']}",
        )

    # Validate payments and allocations
    for payment in payments:
        timestamp = _parse_timestamp(
            payment["timestamp"],
            "payment timestamp",
        )
        _require(
            start <= timestamp.date() <= end,
            f"Payment outside reporting period: {payment['payment_id']}",
        )

        _require(
            isinstance(payment["amount_minor"], int)
            and payment["amount_minor"] > 0,
            f"Invalid payment amount: {payment['payment_id']}",
        )

        allocation_total = 0

        for allocation in payment["allocations"]:
            invoice_id = allocation["invoice_id"]
            _require(invoice_id in invoice_map, f"Unknown invoice: {invoice_id}")

            invoice = invoice_map[invoice_id]
            _require(
                payment["currency"] == invoice["currency"],
                f"Payment currency mismatch: {payment['payment_id']}",
            )
            _require(
                allocation["allocated_minor"] > 0,
                f"Invalid allocation: {payment['payment_id']}",
            )
            allocation_total += allocation["allocated_minor"]

        _require(
            allocation_total == payment["amount_minor"],
            f"Payment allocation mismatch: {payment['payment_id']}",
        )

    # Validate ledger references and timestamps
    for row in ledger:
        timestamp = _parse_timestamp(
            row["timestamp"],
            "ledger timestamp",
        )

        _require(
            start <= timestamp.date() <= end,
            f"Ledger entry outside reporting period: {row['entry_id']}",
        )

        if row["invoice_id"] is not None:
            _require(
                row["invoice_id"] in invoice_map,
                f"Unknown ledger invoice: {row['invoice_id']}",
            )

        if row["payment_id"] is not None:
            _require(
                row["payment_id"] in payment_map,
                f"Unknown ledger payment: {row['payment_id']}",
            )

    _check_ledger_balance(ledger)

    # Check invoice postings and payment postings against source documents
    invoice_postings = {}
    payment_postings = {}

    for row in ledger:
        if row["payment_id"] is None and row["invoice_id"] is not None:
            totals = invoice_postings.setdefault(
                row["invoice_id"],
                {"debit": 0, "credit": 0},
            )
            totals["debit"] += row["debit_minor"]
            totals["credit"] += row["credit_minor"]

        if row["payment_id"] is not None:
            totals = payment_postings.setdefault(
                row["payment_id"],
                {"debit": 0, "credit": 0},
            )
            totals["debit"] += row["debit_minor"]
            totals["credit"] += row["credit_minor"]

    for invoice_id, invoice in invoice_map.items():
        totals = invoice_postings.get(invoice_id)
        _require(totals is not None, f"Missing invoice posting: {invoice_id}")
        _require(
            totals["debit"] == invoice["total_minor"]
            and totals["credit"] == invoice["total_minor"],
            f"Invoice posting amount mismatch: {invoice_id}",
        )

    for payment_id, payment in payment_map.items():
        totals = payment_postings.get(payment_id)
        _require(totals is not None, f"Missing payment posting: {payment_id}")
        _require(
            totals["debit"] == payment["amount_minor"]
            and totals["credit"] == payment["amount_minor"],
            f"Payment posting amount mismatch: {payment_id}",
        )

    # Validate FX records
    fx_keys = []

    for record in fx:
        fx_date = _parse_date(record["date"], "FX date")
        _require(start <= fx_date <= end, "FX date outside reporting period")

        try:
            rate = Decimal(record["rate"])
        except (InvalidOperation, TypeError):
            raise ValueError("Invalid FX rate")

        _require(rate.is_finite() and rate > 0, "FX rate must be positive and finite")
        _require(
            record["base_currency"] == manifest["base_currency"],
            "FX base currency mismatch",
        )

        fx_keys.append((
            record["date"],
            record["base_currency"],
            record["quote_currency"],
        ))

    _unique(fx_keys, "FX date/currency combinations")

    return True


def validate_public_data(
    manifest: dict,
    ledger: list[dict],
    invoices: list[dict],
    payments: list[dict],
    fx: list[dict],
):
    # Structural validation after deliberate mutations.
    # Intentional allocation and period errors are not rejected here.

    _unique(
        [item["invoice_id"] for item in invoices],
        "public invoice IDs",
    )
    _unique(
        [item["payment_id"] for item in payments],
        "public payment IDs",
    )
    _unique(
        [item["entry_id"] for item in ledger],
        "public ledger entry IDs",
    )

    invoice_ids = {item["invoice_id"] for item in invoices}
    payment_ids = {item["payment_id"] for item in payments}

    for row in ledger:
        _parse_timestamp(row["timestamp"], "public ledger timestamp")

        if row["invoice_id"] is not None:
            _require(
                row["invoice_id"] in invoice_ids,
                f"Unknown public invoice: {row['invoice_id']}",
            )

        if row["payment_id"] is not None:
            _require(
                row["payment_id"] in payment_ids,
                f"Unknown public payment: {row['payment_id']}",
            )

    _check_ledger_balance(ledger)

    for record in fx:
        try:
            rate = Decimal(record["rate"])
        except (InvalidOperation, TypeError):
            raise ValueError("Invalid public FX rate")

        _require(rate.is_finite() and rate > 0, "Invalid public FX rate")

    return True
