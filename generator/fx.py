
import random
from datetime import date, timedelta
from decimal import Decimal


FOREIGN_CURRENCIES = ["USD", "EUR", "GBP", "KZT", "CHF"]

# Условные базовые курсы: единиц базовой валюты за 1 единицу валюты
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

    currencies = [
        currency
        for currency in FOREIGN_CURRENCIES
        if currency != base_currency
    ]

    rates = []
    current = start

    # Генерируем курсы на каждый календарный день
    while current <= end:
        for currency in currencies:
            base_rate = BASE_RATES[currency] / BASE_RATES.get(
                base_currency,
                Decimal("1.000000"),
            )

            # Небольшое ежедневное изменение курса
            variation = Decimal(
                rng.randint(-300, 300)
            ) / Decimal("10000")

            rate = base_rate * (
                Decimal("1") + variation
            )

            rates.append({
                "date": current.isoformat(),
                "base_currency": base_currency,
                "quote_currency": currency,
                "rate": str(rate.quantize(Decimal("0.000001"))),
                "source": "SYNTHETIC_DAILY",
            })

        current += timedelta(days=1)

    return rates
