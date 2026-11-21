
import random
from datetime import date, timedelta
from decimal import Decimal


FOREIGN_CURRENCIES = ["USD", "EUR", "GBP", "KZT", "CHF"]

# Units of base currency per one unit of quote currency.
BASE_RATES = {
    "USD": Decimal("1.000000"),
    "EUR": Decimal("1.080000"),
    "GBP": Decimal("1.270000"),
    "KZT": Decimal("0.002200"),
    "CHF": Decimal("1.120000"),
}


def generate_fx(seed: int, manifest: dict) -> list[dict]:
    rng = random.Random(seed + 3003)

    base_currency = manifest["base_currency"]
    start = date.fromisoformat(manifest["period_start"])
    end = date.fromisoformat(manifest["period_end"])

    if start > end:
        raise ValueError("Invalid reporting period")

    if base_currency not in BASE_RATES:
        raise ValueError(f"Unsupported base currency: {base_currency}")

    currencies = [
        currency
        for currency in FOREIGN_CURRENCIES
        if currency != base_currency
    ]

    rates = []
    current = start

    while current <= end:
        for currency in currencies:
            base_rate = (
                BASE_RATES[currency] / BASE_RATES[base_currency]
            )

            variation = Decimal(
                rng.randint(-300, 300)
            ) / Decimal("10000")

            reference_rate = (
                base_rate * (Decimal("1") + variation)
            ).quantize(Decimal("0.000001"))

            fx_id = f"FX-{current.isoformat()}-{currency}"

            rates.append({
                "fx_id": fx_id,
                "date": current.isoformat(),
                "base_currency": base_currency,
                "quote_currency": currency,
                "rate": str(reference_rate),
                "reference_rate": str(reference_rate),
                "source": "SYNTHETIC_DAILY",
                "reference_source": "INDEPENDENT_REFERENCE_FEED",
            })

        current += timedelta(days=1)

    return rates
