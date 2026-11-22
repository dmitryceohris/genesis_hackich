
import copy
import random
import hashlib

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from generator.settlement import rate_on, to_base_minor
from generator.timezones import resolve as _resolve_timezone


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
        # Денежные строки с валютным плечом: только их пересчёт можно
        # исказить так, чтобы искажённой оказалась сумма в книге. Искажение
        # курса в самой таблице фиксингов ни одной суммы не меняет и
        # доказывается лишь сравнением двух чисел в одной строке, поэтому
        # ошибка вносится в проводку, а не в справочник.
        eligible_rows = [
            row for row in result_ledger
            if row.get("source_currency")
            and isinstance(row.get("source_minor"), int)
            and row["account"] == "Bank"
        ]

        if eligible_rows:
            row = rng.choice(eligible_rows)

            day = row["timestamp"][:10]
            correct = rate_on(result_fx, row["source_currency"], day)

            # Берётся курс другой даты — типичная ошибка пересчёта «не на ту
            # дату», а не выдуманное число. Если соседней даты нет, курс
            # сдвигается на 3 процента.
            wrong_row = next(
                (
                    item for item in result_fx
                    if item["quote_currency"] == row["source_currency"]
                    and item["date"] != day
                    and Decimal(item["rate"]) != Decimal(correct["rate"])
                ),
                None,
            )

            if wrong_row is not None:
                wrong_rate = Decimal(wrong_row["rate"])
                operation = "post_cash_row_with_rate_of_another_date"
            else:
                wrong_rate = (
                    Decimal(correct["rate"]) * Decimal("1.03")
                ).quantize(Decimal("0.000001"))
                operation = "post_cash_row_with_rate_shifted_by_3_percent"

            correct_base = to_base_minor(
                row["source_minor"], correct["rate"]
            )
            wrong_base = to_base_minor(row["source_minor"], wrong_rate)

            if wrong_base > 0 and wrong_base != correct_base:
                side = "debit_minor" if row["debit_minor"] else "credit_minor"
                row[side] = wrong_base

                # Двойная запись обязана сойтись: разницу забирает счёт
                # курсовой разницы той же проводки. Без этого эпизод
                # разошёлся бы по балансу и провалил инварианты — то есть
                # стал бы противоречивыми данными, а не задачей.
                _absorb_into_revaluation(
                    result_ledger,
                    row,
                    wrong_base - correct_base,
                )

                register_error(
                    error_type="fx_rate",
                    affected_ids=[row["entry_id"], row["payment_id"]],
                    amount=abs(wrong_base - correct_base),
                    currency=manifest["base_currency"],
                    evidence_ids=[
                        row["entry_id"],
                        correct["fx_id"],
                        row["payment_id"],
                    ],
                    explanation=(
                        "The cash posting converts the settled foreign "
                        "amount at a rate other than the published fixing "
                        "for the payment date."
                    ),
                    operation=operation,
                    source_ids=[row["entry_id"], correct["fx_id"]],
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

            timezone = _resolve_timezone(manifest["timezone"])

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


def _absorb_into_revaluation(ledger: list[dict], cash_row: dict, delta: int) -> None:
    """Отнести ``delta`` на счёт курсовой разницы проводки денежной строки.

    Строка курсовой разницы в проводке может отсутствовать: при точном
    обратном пересчёте разницы нет и строка не создаётся. Тогда она
    добавляется здесь, чтобы двойная запись сошлась.
    """
    if delta == 0:
        return

    transaction_id = cash_row["transaction_id"]
    cash_is_debit = bool(cash_row["debit_minor"])

    # Если денежная строка в дебете и выросла, равновесие требует роста
    # кредита, и наоборот.
    debit_delta = -delta if cash_is_debit else delta

    for row in ledger:
        if (
            row["transaction_id"] == transaction_id
            and row["account"] == "FX Revaluation"
        ):
            value = row["debit_minor"] - row["credit_minor"] + debit_delta
            row["debit_minor"] = max(0, value)
            row["credit_minor"] = max(0, -value)
            return

    position = max(
        index for index, row in enumerate(ledger)
        if row["transaction_id"] == transaction_id
    )
    ledger.insert(
        position + 1,
        {
            "entry_id": f"{transaction_id}-FXREVAL",
            "transaction_id": transaction_id,
            "timestamp": cash_row["timestamp"],
            "entity_id": cash_row["entity_id"],
            "invoice_id": cash_row["invoice_id"],
            "payment_id": cash_row["payment_id"],
            "currency": cash_row["currency"],
            "account": "FX Revaluation",
            "debit_minor": max(0, debit_delta),
            "credit_minor": max(0, -debit_delta),
        },
    )
