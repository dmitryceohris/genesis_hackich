
import hashlib
import random
from datetime import date, datetime, time, timedelta
from generator.settlement import (
    from_base_minor,
    quote_currencies,
    rate_on,
)
from generator.timezones import resolve as _resolve_timezone

#: Доля платежей, уходящих в банк в иностранной валюте. Нужна не для
#: разнообразия: без валютного плеча ошибку пересчёта курса нельзя сделать
#: денежной, а значит и доказуемой.
FOREIGN_SETTLEMENT_SHARE = 0.25


def generate_payments(
    seed: int,
    manifest: dict,
    invoices: list[dict],
    fx: list[dict] | None = None,
) -> list[dict]:

    rng = random.Random(seed + 2002)
    fx = fx or []
    settlement_currencies = quote_currencies(fx)

    token = hashlib.sha256(
        str(seed).encode()
    ).hexdigest()[:12].upper()

    timezone = _resolve_timezone(manifest["timezone"])
    period_end = date.fromisoformat(manifest["period_end"])

    payments = []
    payment_index = 0

    def make_timestamp(payment_date: date) -> str:
        value = datetime.combine(
            payment_date,
            time(
                hour=rng.randint(8, 18),
                minute=rng.choice([0, 15, 30, 45]),
            ),
            tzinfo=timezone,
        )
        return value.isoformat()

    def make_reference(index: int) -> str:
        return f"BANK-{token}-{index:05d}"

    for invoice in invoices:
        invoice_date = date.fromisoformat(invoice["invoice_date"])
        total_minor = invoice["total_minor"]

        if rng.random() < 0.15:
            continue

        payment_count = rng.choices(
            [1, 2, 3],
            weights=[60, 30, 10],
            k=1,
        )[0]

        if rng.random() < 0.75:
            paid_total = total_minor
        else:
            paid_total = rng.randint(
                max(1, total_minor // 3),
                total_minor - 1,
            )

        remaining = paid_total
        allocations = []

        for part_index in range(payment_count):
            parts_left = payment_count - part_index

            if parts_left == 1:
                amount = remaining
            else:
                amount = rng.randint(
                    1,
                    remaining - (parts_left - 1),
                )

            allocations.append(amount)
            remaining -= amount

        for amount in allocations:
            available_days = (period_end - invoice_date).days

            if available_days < 0:
                continue

            payment_date = invoice_date + timedelta(
                days=rng.randint(0, min(available_days, 90))
            )

            payment_id = f"PAY-{token}-{payment_index:05d}"
            payment_index += 1

            timestamp = make_timestamp(payment_date)

            record = {
                "payment_id": payment_id,
                "entity_id": manifest["episode_id"],
                "payment_type": "payment",
                "related_payment_id": None,
                "timestamp": timestamp,
                "currency": invoice["currency"],
                "counterparty": invoice["counterparty"],
                "amount_minor": amount,
                "allocations": [{
                    "invoice_id": invoice["invoice_id"],
                    "allocated_minor": amount,
                }],
                "bank_reference": make_reference(payment_index),
            }

            _attach_settlement(
                record,
                rng,
                settlement_currencies,
                fx,
                payment_date,
            )

            payments.append(record)

    # Generate legitimate refunds after original payments.
    original_payments = list(payments)

    for original in original_payments:
        if rng.random() >= 0.05:
            continue

        original_date = datetime.fromisoformat(
            original["timestamp"]
        ).date()

        available_days = (period_end - original_date).days

        if available_days < 1:
            continue

        refund_date = original_date + timedelta(
            days=rng.randint(1, available_days)
        )

        refund_amount = rng.randint(
            1,
            original["amount_minor"],
        )

        original_allocation = original["allocations"][0]

        refund_id = f"PAY-{token}-{payment_index:05d}"
        payment_index += 1

        payments.append({
            "payment_id": refund_id,
            "entity_id": manifest["episode_id"],
            "payment_type": "refund",
            "related_payment_id": original["payment_id"],
            "timestamp": make_timestamp(refund_date),
            "currency": original["currency"],
            "counterparty": original["counterparty"],
            "amount_minor": refund_amount,
            "allocations": [{
                "invoice_id": original_allocation["invoice_id"],
                "allocated_minor": refund_amount,
            }],
            "bank_reference": make_reference(payment_index),
        })

    return payments


def _attach_settlement(
    payment: dict,
    rng: random.Random,
    currencies: list[str],
    fx: list[dict],
    payment_date,
) -> None:
    """Отметить платёж как ушедший в банк в иностранной валюте.

    Сумма в иностранной валюте считается обратным пересчётом базовой. Точного
    обратного хода у округления нет, и подгонять суммы не нужно: разницу
    журнал относит на счёт курсовой разницы.
    """
    if not currencies or rng.random() >= FOREIGN_SETTLEMENT_SHARE:
        return

    currency = currencies[rng.randrange(len(currencies))]
    fx_row = rate_on(fx, currency, payment_date.isoformat())

    if fx_row is None:
        return

    payment["settlement_currency"] = currency
    payment["settlement_minor"] = from_base_minor(
        payment["amount_minor"], fx_row["rate"]
    )
    payment["settlement_fx_id"] = fx_row["fx_id"]
