
import copy
import random
import hashlib

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo


ERROR_TYPES = [
    "duplicate_invoice",
    "payment_allocation",
    "fx_rate",
    "accounting_period",
]


def inject_errors(
    seed: int,
    manifest: dict,
    ledger: list[dict],
    invoices: list[dict],
    payments: list[dict],
    fx: list[dict],
    config: dict | None = None,
) -> dict:

    config = config or {}

    enabled_errors = config.get("error_types", ERROR_TYPES)

    unknown_errors = set(enabled_errors) - set(ERROR_TYPES)
    if unknown_errors:
        raise ValueError(f"Unknown error types: {unknown_errors}")

    if not invoices:
        raise ValueError("Invoices cannot be empty")

    rng = random.Random(seed + 4004)

    token = hashlib.sha256(
        str(seed).encode()
    ).hexdigest()[:12].upper()

    result_ledger = copy.deepcopy(ledger)
    result_invoices = copy.deepcopy(invoices)
    result_payments = copy.deepcopy(payments)
    result_fx = copy.deepcopy(fx)

    truth = []
    provenance = []

    interaction_scenario = config.get("interaction_scenario")

    valid_scenarios = {
        None,
        "duplicate_period",
        "payment_period",
    }

    if interaction_scenario not in valid_scenarios:
        raise ValueError(
            f"Unknown interaction scenario: {interaction_scenario}"
        )

    if interaction_scenario == "duplicate_period":
        required = {"duplicate_invoice", "accounting_period"}
        if not required.issubset(set(enabled_errors)):
            raise ValueError(
                "duplicate_period requires duplicate_invoice and accounting_period"
            )

    if interaction_scenario == "payment_period":
        required = {"payment_allocation", "accounting_period"}
        if not required.issubset(set(enabled_errors)):
            raise ValueError(
                "payment_period requires payment_allocation and accounting_period"
            )

    duplicate_source_invoice_id = None
    payment_allocation_invoice_id = None

    def register_error(
        error_type,
        affected_ids,
        amount,
        currency,
        evidence_ids,
        explanation,
        operation,
        source_ids,
        generated_ids,
    ):
        error_id = f"ERR-{len(truth) + 1:04d}"

        truth.append({
            "error_id": error_id,
            "type": error_type,
            "affected_ids": affected_ids,
            "claimed_amount_minor": amount,
            "currency": currency,
            "evidence_ids": evidence_ids,
            "explanation": explanation,
        })

        provenance.append({
            "error_id": error_id,
            "type": error_type,
            "operation": operation,
            "source_ids": source_ids,
            "generated_ids": generated_ids,
        })

    # -------------------------------------------------
    # 1. DUPLICATE INVOICE
    # -------------------------------------------------

    if "duplicate_invoice" in enabled_errors:
        purchase_invoices = [
            invoice for invoice in result_invoices
            if invoice.get("direction") == "purchase"
        ]
        if not purchase_invoices:
            raise ValueError("No purchase invoice available for duplicate injection")
        original = rng.choice(purchase_invoices)
        original_id = original["invoice_id"]

        duplicate_source_invoice_id = original_id

        if "document_number" not in original:
            original["document_number"] = f"DOC-{original_id}"

        duplicate = copy.deepcopy(original)

        duplicate_id = f"INV-DUP-{token}-0001"
        duplicate["invoice_id"] = duplicate_id

        result_invoices.append(duplicate)

        original_entries = [
            row for row in result_ledger
            if row["invoice_id"] == original_id
            and row["payment_id"] is None
        ]

        generated_entry_ids = []

        for index, original_entry in enumerate(original_entries):
            cloned = copy.deepcopy(original_entry)

            cloned["invoice_id"] = duplicate_id
            cloned["transaction_id"] = f"DUP-POST-{duplicate_id}"
            cloned["entry_id"] = (
                f"{duplicate_id}-ENTRY-{index:03d}"
            )

            generated_entry_ids.append(cloned["entry_id"])
            result_ledger.append(cloned)

        register_error(
            error_type="duplicate_invoice",
            affected_ids=[original_id, duplicate_id],
            amount=original["total_minor"],
            currency=original["currency"],
            evidence_ids=[
                original_id,
                duplicate_id,
                *generated_entry_ids,
            ],
            explanation=(
                "Two invoices share the same document number "
                "and financial details. The duplicate invoice "
                "has also been posted to the ledger."
            ),
            operation="duplicate_invoice_and_postings",
            source_ids=[original_id],
            generated_ids=[
                duplicate_id,
                *generated_entry_ids,
            ],
        )

    # -------------------------------------------------
    # 2. PAYMENT ALLOCATION ERROR
    # -------------------------------------------------

    if "payment_allocation" in enabled_errors:
        eligible_payments = [
            payment for payment in result_payments
            if payment["allocations"]
            and payment["amount_minor"] > 1
        ]

        if eligible_payments:
            payment = rng.choice(eligible_payments)

            original_allocated = sum(
                item["allocated_minor"]
                for item in payment["allocations"]
            )

            missing_amount = max(1, original_allocated // 4)

            allocation = payment["allocations"][0]

            if allocation["allocated_minor"] <= missing_amount:
                raise ValueError(
                    "Cannot create partial allocation"
                )

            allocation["allocated_minor"] -= missing_amount

            payment_id = payment["payment_id"]
            invoice_id = allocation["invoice_id"]

            payment_allocation_invoice_id = invoice_id

            related_entries = [
                row for row in result_ledger
                if row["payment_id"] == payment_id
            ]

            register_error(
                error_type="payment_allocation",
                affected_ids=[payment_id, invoice_id],
                amount=missing_amount,
                currency=payment["currency"],
                evidence_ids=[
                    payment_id,
                    invoice_id,
                    *[
                        row["entry_id"]
                        for row in related_entries
                    ],
                ],
                explanation=(
                    "The payment amount exceeds the sum of "
                    "its invoice allocations. Part of the "
                    "payment remains unallocated."
                ),
                operation="reduce_payment_allocation",
                source_ids=[payment_id, invoice_id],
                generated_ids=[],
            )

    # -------------------------------------------------
    # 3. WRONG FX RATE
    # -------------------------------------------------

    if "fx_rate" in enabled_errors:
        eligible_fx = [
            record for record in result_fx
            if record["quote_currency"] != record["base_currency"]
        ]

        if eligible_fx:
            record = rng.choice(eligible_fx)

            fx_id = record["fx_id"]
            original_rate = Decimal(record["rate"])

            incorrect_rate = (
                original_rate * Decimal("1.10")
            ).quantize(Decimal("0.000001"))

            record["rate"] = str(incorrect_rate)

            register_error(
                error_type="fx_rate",
                affected_ids=[fx_id],
                amount=None,
                currency=record["quote_currency"],
                evidence_ids=[fx_id],
                explanation=(
                    "The recorded exchange rate differs from "
                    "the independent reference rate for the "
                    "same date and currency."
                ),
                operation="increase_fx_rate_by_10_percent",
                source_ids=[fx_id],
                generated_ids=[],
            )

    # -------------------------------------------------
    # 4. ACCOUNTING PERIOD ERROR
    # -------------------------------------------------

    if "accounting_period" in enabled_errors:
        eligible_invoices = [
            invoice for invoice in result_invoices
            if invoice.get("direction") == "purchase"
            and not invoice["invoice_id"].startswith("INV-DUP-")
            and any(
                row["invoice_id"] == invoice["invoice_id"]
                and row["payment_id"] is None
                for row in result_ledger
            )
        ]

        target_invoice_id = None

        if interaction_scenario == "duplicate_period":
            target_invoice_id = duplicate_source_invoice_id

        elif interaction_scenario == "payment_period":
            target_invoice_id = payment_allocation_invoice_id

        if target_invoice_id is not None:
            eligible_invoices = [
                invoice for invoice in eligible_invoices
                if invoice["invoice_id"] == target_invoice_id
            ]

        if not eligible_invoices:
            if interaction_scenario is not None:
                raise ValueError(
                    f"Could not find target invoice for {interaction_scenario}"
                )
        else:
            invoice = rng.choice(eligible_invoices)
            invoice_id = invoice["invoice_id"]

            related_entries = [
                row for row in result_ledger
                if row["invoice_id"] == invoice_id
                and row["payment_id"] is None
            ]

            period_end = date.fromisoformat(
                manifest["period_end"]
            )

            next_day = period_end + timedelta(days=1)

            timezone = ZoneInfo(manifest["timezone"])

            incorrect_timestamp = datetime.combine(
                next_day,
                time.min,
                tzinfo=timezone,
            ).isoformat()

            for row in related_entries:
                row["timestamp"] = incorrect_timestamp

            register_error(
                error_type="accounting_period",
                affected_ids=[
                    invoice_id,
                    *[
                        row["entry_id"]
                        for row in related_entries
                    ],
                ],
                amount=invoice["total_minor"],
                currency=invoice["currency"],
                evidence_ids=[
                    invoice_id,
                    *[
                        row["entry_id"]
                        for row in related_entries
                    ],
                ],
                explanation=(
                    "The invoice belongs to the reporting "
                    "period, but its ledger postings are "
                    "dated after the reporting period ends."
                ),
                operation="move_postings_after_period_end",
                source_ids=[invoice_id],
                generated_ids=[],
            )

    return {
        "ledger": result_ledger,
        "invoices": result_invoices,
        "payments": result_payments,
        "fx": result_fx,
        "truth": truth,
        "provenance": provenance,
    }
