
from datetime import date, datetime, time
from zoneinfo import ZoneInfo


def generate_ledger(
    seed: int,
    manifest: dict,
    invoices: list[dict],
    payments: list[dict],
) -> list[dict]:

    timezone = ZoneInfo(manifest["timezone"])
    episode_id = manifest["episode_id"]

    invoice_map = {
        invoice["invoice_id"]: invoice
        for invoice in invoices
    }

    if len(invoice_map) != len(invoices):
        raise ValueError("Duplicate invoice IDs")

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
    ):
        if debit < 0 or credit < 0:
            raise ValueError("Negative ledger amount")

        if debit and credit:
            raise ValueError("Entry cannot have both debit and credit")

        if debit == 0 and credit == 0:
            return

        rows.append({
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
        })

    # 1. Проводки по счетам
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
            # Продажа: дебиторская задолженность
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
            # Покупка: кредиторская задолженность
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

    # 2. Проводки по платежам
    for payment in payments:
        payment_id = payment["payment_id"]
        allocations = payment["allocations"]

        allocated_total = sum(
            allocation["allocated_minor"]
            for allocation in allocations
        )

        if allocated_total != payment["amount_minor"]:
            raise ValueError(
                f"Payment {payment_id} allocation mismatch"
            )

        for allocation_index, allocation in enumerate(allocations):
            invoice_id = allocation["invoice_id"]
            amount = allocation["allocated_minor"]

            if invoice_id not in invoice_map:
                raise ValueError(
                    f"Unknown invoice: {invoice_id}"
                )

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
                f"PAY-POST-{payment_id}-{allocation_index}"
            )

            timestamp = payment["timestamp"]
            currency = payment["currency"]

            if invoice["direction"] == "sales":
                # Получение денег от клиента
                add_entry(
                    transaction_id, timestamp,
                    currency, invoice_id, payment_id,
                    "Bank", amount, 0
                )

                add_entry(
                    transaction_id, timestamp,
                    currency, invoice_id, payment_id,
                    "Accounts Receivable", 0, amount
                )

            else:
                # Оплата поставщику
                add_entry(
                    transaction_id, timestamp,
                    currency, invoice_id, payment_id,
                    "Accounts Payable", amount, 0
                )

                add_entry(
                    transaction_id, timestamp,
                    currency, invoice_id, payment_id,
                    "Bank", 0, amount
                )

    # 3. Проверяем баланс каждой операции отдельно
    transaction_totals = {}

    for row in rows:
        transaction_id = row["transaction_id"]

        totals = transaction_totals.setdefault(
            transaction_id,
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
