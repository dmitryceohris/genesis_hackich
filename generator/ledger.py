
from datetime import date, datetime, time
from generator.settlement import rate_on, to_base_minor
from generator.timezones import resolve as _resolve_timezone

#: Счёт курсовой разницы. Пересчёт иностранной суммы по курсу почти никогда не
#: совпадает с суммой обязательства до минимальной единицы, и в учёте разницу
#: относят на отдельный счёт, а не подгоняют проводку.
FX_REVALUATION_ACCOUNT = "FX Revaluation"


def generate_ledger(
    seed: int,
    manifest: dict,
    invoices: list[dict],
    payments: list[dict],
    fx: list[dict] | None = None,
) -> list[dict]:

    timezone = _resolve_timezone(manifest["timezone"])
    episode_id = manifest["episode_id"]
    fx = fx or []

    invoice_map = {
        invoice["invoice_id"]: invoice
        for invoice in invoices
    }

    payment_map = {
        payment["payment_id"]: payment
        for payment in payments
    }

    if len(invoice_map) != len(invoices):
        raise ValueError("Duplicate invoice IDs")

    if len(payment_map) != len(payments):
        raise ValueError("Duplicate payment IDs")

    rows = []

    def add_entry(
        transaction_id,
        timestamp,
        currency,
        invoice_id,
        payment_id,
        account,
        debit,
        credit,
        extra=None,
    ):
        if debit < 0 or credit < 0:
            raise ValueError("Negative ledger amount")

        if debit and credit:
            raise ValueError("Entry cannot have both debit and credit")

        if debit == 0 and credit == 0:
            return

        entry = {
            "entry_id": f"{transaction_id}-{len(rows):06d}",
            "transaction_id": transaction_id,
            "timestamp": timestamp,
            "entity_id": episode_id,
            "invoice_id": invoice_id,
            "payment_id": payment_id,
            "currency": currency,
            "account": account,
            "debit_minor": debit,
            "credit_minor": credit,
        }

        if extra:
            entry.update(extra)

        rows.append(entry)

    # Invoice postings
    for invoice in invoices:
        invoice_id = invoice["invoice_id"]
        transaction_id = f"INV-POST-{invoice_id}"

        invoice_date = date.fromisoformat(
            invoice["invoice_date"]
        )

        timestamp = datetime.combine(
            invoice_date,
            time.min,
            tzinfo=timezone,
        ).isoformat()

        subtotal = invoice["subtotal_minor"]
        tax = invoice["tax_minor"]
        total = invoice["total_minor"]

        if subtotal + tax != total:
            raise ValueError(
                f"Invoice {invoice_id} has inconsistent totals"
            )

        if invoice["direction"] == "sales":
            add_entry(
                transaction_id, timestamp,
                invoice["currency"], invoice_id, None,
                "Accounts Receivable", total, 0
            )
            add_entry(
                transaction_id, timestamp,
                invoice["currency"], invoice_id, None,
                "Revenue", 0, subtotal
            )
            if tax:
                add_entry(
                    transaction_id, timestamp,
                    invoice["currency"], invoice_id, None,
                    "Tax Payable", 0, tax
                )

        elif invoice["direction"] == "purchase":
            add_entry(
                transaction_id, timestamp,
                invoice["currency"], invoice_id, None,
                "Operating Expenses", subtotal, 0
            )
            if tax:
                add_entry(
                    transaction_id, timestamp,
                    invoice["currency"], invoice_id, None,
                    "Input Tax", tax, 0
                )
            add_entry(
                transaction_id, timestamp,
                invoice["currency"], invoice_id, None,
                "Accounts Payable", 0, total
            )

        else:
            raise ValueError(
                f"Unknown invoice direction: {invoice['direction']}"
            )

    # Payment and refund postings
    for payment in payments:
        payment_id = payment["payment_id"]
        payment_type = payment.get("payment_type", "payment")
        allocations = payment["allocations"]

        allocated_total = sum(
            item["allocated_minor"]
            for item in allocations
        )

        if allocated_total != payment["amount_minor"]:
            raise ValueError(
                f"Payment {payment_id} allocation mismatch"
            )

        if payment_type not in {"payment", "refund"}:
            raise ValueError(
                f"Unknown payment type: {payment_type}"
            )

        if payment_type == "refund":
            original_id = payment.get("related_payment_id")
            original = payment_map.get(original_id)

            if original is None:
                raise ValueError(
                    f"Refund {payment_id} has no original payment"
                )

            if original.get("payment_type", "payment") != "payment":
                raise ValueError(
                    f"Refund {payment_id} references another refund"
                )

        elif payment.get("related_payment_id") is not None:
            raise ValueError(
                f"Normal payment {payment_id} cannot reference another payment"
            )

        for allocation_index, allocation in enumerate(allocations):
            invoice_id = allocation["invoice_id"]
            amount = allocation["allocated_minor"]

            if invoice_id not in invoice_map:
                raise ValueError(f"Unknown invoice: {invoice_id}")

            invoice = invoice_map[invoice_id]

            if payment["currency"] != invoice["currency"]:
                raise ValueError(
                    f"Currency mismatch in payment {payment_id}"
                )

            if amount <= 0:
                raise ValueError(
                    f"Invalid allocation in payment {payment_id}"
                )

            transaction_id = (
                f"{payment_type.upper()}-POST-"
                f"{payment_id}-{allocation_index}"
            )

            timestamp = payment["timestamp"]
            currency = payment["currency"]

            if payment_type == "payment":
                # Валютное плечо: со счёта ушла иностранная сумма, в книге
                # отражён её пересчёт по курсу на дату платежа. Денежная
                # строка несёт обе суммы, разницу забирает счёт курсовой
                # разницы.
                settlement = _settlement_leg(payment, fx)

                if settlement is None:
                    cash_amount = amount
                    cash_extra = None
                else:
                    cash_amount = settlement["base_minor"]
                    cash_extra = {
                        "source_minor": settlement["source_minor"],
                        "source_currency": settlement["currency"],
                        "fx_id": settlement["fx_id"],
                    }

                difference = cash_amount - amount

                if invoice["direction"] == "sales":
                    add_entry(
                        transaction_id, timestamp,
                        currency, invoice_id, payment_id,
                        "Bank", cash_amount, 0, cash_extra
                    )
                    add_entry(
                        transaction_id, timestamp,
                        currency, invoice_id, payment_id,
                        "Accounts Receivable", 0, amount
                    )
                    add_entry(
                        transaction_id, timestamp,
                        currency, invoice_id, payment_id,
                        FX_REVALUATION_ACCOUNT,
                        max(0, -difference), max(0, difference)
                    )
                else:
                    add_entry(
                        transaction_id, timestamp,
                        currency, invoice_id, payment_id,
                        "Accounts Payable", amount, 0
                    )
                    add_entry(
                        transaction_id, timestamp,
                        currency, invoice_id, payment_id,
                        "Bank", 0, cash_amount, cash_extra
                    )
                    add_entry(
                        transaction_id, timestamp,
                        currency, invoice_id, payment_id,
                        FX_REVALUATION_ACCOUNT,
                        max(0, difference), max(0, -difference)
                    )

            else:
                if invoice["direction"] == "sales":
                    add_entry(
                        transaction_id, timestamp,
                        currency, invoice_id, payment_id,
                        "Accounts Receivable", amount, 0
                    )
                    add_entry(
                        transaction_id, timestamp,
                        currency, invoice_id, payment_id,
                        "Bank", 0, amount
                    )
                else:
                    add_entry(
                        transaction_id, timestamp,
                        currency, invoice_id, payment_id,
                        "Bank", amount, 0
                    )
                    add_entry(
                        transaction_id, timestamp,
                        currency, invoice_id, payment_id,
                        "Accounts Payable", 0, amount
                    )

    # Verify transaction balance
    transaction_totals = {}

    for row in rows:
        totals = transaction_totals.setdefault(
            (row["transaction_id"], row["currency"]),
            {"debit": 0, "credit": 0},
        )

        totals["debit"] += row["debit_minor"]
        totals["credit"] += row["credit_minor"]

    for transaction_id, totals in transaction_totals.items():
        if totals["debit"] != totals["credit"]:
            raise ValueError(
                f"Unbalanced transaction: {transaction_id}"
            )

    return rows


def _settlement_leg(payment: dict, fx: list[dict]) -> dict | None:
    """Валютное плечо платежа, если оно есть и курс на дату найден."""
    currency = payment.get("settlement_currency")
    source_minor = payment.get("settlement_minor")

    if not currency or not isinstance(source_minor, int):
        return None

    day = payment["timestamp"][:10]
    fx_row = rate_on(fx, currency, day)

    if fx_row is None:
        return None

    return {
        "currency": currency,
        "source_minor": source_minor,
        "fx_id": fx_row["fx_id"],
        "base_minor": to_base_minor(source_minor, fx_row["rate"]),
    }
