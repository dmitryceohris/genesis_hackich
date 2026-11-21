
import hashlib
import random
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


def generate_payments(
    seed: int,
    manifest: dict,
    invoices: list[dict],
) -> list[dict]:

    rng = random.Random(seed + 2002)

    token = hashlib.sha256(
        str(seed).encode()
    ).hexdigest()[:12].upper()

    timezone = ZoneInfo(manifest["timezone"])
    period_end = date.fromisoformat(manifest["period_end"])

    payments = []
    payment_index = 0

    for invoice in invoices:
        invoice_date = date.fromisoformat(invoice["invoice_date"])
        total_minor = invoice["total_minor"]

        # 15% счетов остаются неоплаченными
        if rng.random() < 0.15:
            continue

        # Выбираем количество платежей
        payment_count = rng.choices(
            [1, 2, 3],
            weights=[60, 30, 10],
            k=1,
        )[0]

        # Определяем долю оплаченной суммы
        if rng.random() < 0.75:
            paid_total = total_minor
        else:
            paid_total = rng.randint(
                max(1, total_minor // 3),
                total_minor - 1,
            )

        # Разбиваем сумму на платежи без потери копеек
        remaining = paid_total
        allocations = []

        for part_index in range(payment_count):
            parts_left = payment_count - part_index

            if parts_left == 1:
                amount = remaining
            else:
                max_amount = remaining - (parts_left - 1)
                amount = rng.randint(
                    1,
                    max_amount,
                )

            allocations.append(amount)
            remaining -= amount

        for amount in allocations:
            available_days = (period_end - invoice_date).days

            if available_days < 0:
                continue

            payment_date = invoice_date + timedelta(
                days=rng.randint(
                    0,
                    min(available_days, 90),
                )
            )

            payment_time = datetime.combine(
                payment_date,
                time(
                    hour=rng.randint(8, 18),
                    minute=rng.choice([0, 15, 30, 45]),
                ),
                tzinfo=timezone,
            )

            payment_id = f"PAY-{token}-{payment_index:05d}"
            payment_index += 1

            payments.append({
                "payment_id": payment_id,
                "entity_id": manifest["episode_id"],
                "timestamp": payment_time.isoformat(),
                "currency": invoice["currency"],
                "counterparty": invoice["counterparty"],
                "amount_minor": amount,
                "allocations": [
                    {
                        "invoice_id": invoice["invoice_id"],
                        "allocated_minor": amount,
                    }
                ],
                "bank_reference": f"BANK-{token}-{payment_index:05d}",
            })

    return payments
