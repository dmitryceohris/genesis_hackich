
import hashlib
import random
from datetime import date, timedelta


COUNTERPARTIES = [
    "Northstar Trading Ltd",
    "Meridian Supplies",
    "Atlas Technologies",
    "Caspian Logistics",
    "Orion Manufacturing",
    "Summit Consulting",
    "Vertex Systems",
    "Blue River Distribution",
]

ITEMS = [
    "Office equipment",
    "Software license",
    "Consulting services",
    "Raw materials",
    "Transportation services",
    "Maintenance",
    "Marketing services",
    "Industrial components",
]


def generate_invoices(
    seed: int,
    manifest: dict,
    n_invoices: int = 50,
) -> list[dict]:
    if not 20 <= n_invoices <= 200:
        raise ValueError("n_invoices must be between 20 and 200")

    rng = random.Random(seed + 1001)

    start = date.fromisoformat(manifest["period_start"])
    end = date.fromisoformat(manifest["period_end"])

    if start > end:
        raise ValueError("Invalid reporting period")

    duration = (end - start).days
    token = hashlib.sha256(str(seed).encode()).hexdigest()[:12].upper()

    invoices = []

    for index in range(n_invoices):
        invoice_id = f"INV-{token}-{index:05d}"

        invoice_date = start + timedelta(
            days=rng.randint(0, duration)
        )

        due_date = invoice_date + timedelta(
            days=rng.choice([15, 30, 45, 60])
        )

        direction = rng.choice(["sales", "purchase"])
        counterparty = rng.choice(COUNTERPARTIES)

        item_count = rng.randint(1, 3)
        line_items = []
        subtotal_minor = 0

        for item_index in range(item_count):
            quantity = rng.randint(1, 5)
            unit_price_minor = rng.randint(10_000, 500_000)
            line_total_minor = quantity * unit_price_minor

            line_items.append({
                "line_id": f"{invoice_id}-L{item_index + 1}",
                "description": rng.choice(ITEMS),
                "quantity": quantity,
                "unit_price_minor": unit_price_minor,
                "line_total_minor": line_total_minor,
            })

            subtotal_minor += line_total_minor

        tax_rate_bps = rng.choice([0, 500, 1000, 1200])
        tax_minor = (
            subtotal_minor * tax_rate_bps + 5000
        ) // 10000

        total_minor = subtotal_minor + tax_minor

        invoices.append({
            "invoice_id": invoice_id,
            "entity_id": manifest["episode_id"],
            "counterparty": counterparty,
            "direction": direction,
            "invoice_date": invoice_date.isoformat(),
            "due_date": due_date.isoformat(),
            "currency": manifest["base_currency"],
            "line_items": line_items,
            "subtotal_minor": subtotal_minor,
            "tax_rate_bps": tax_rate_bps,
            "tax_minor": tax_minor,
            "total_minor": total_minor,
        })

    return invoices
