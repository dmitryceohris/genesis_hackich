
import random
from datetime import date
import hashlib


COMPANIES = [
    "Northstar Trading",
    "Vertex Solutions",
    "Atlas Industries",
    "Nova Technologies",
    "Summit Group",
    "Pioneer Logistics",
    "Horizon Systems",
    "Apex Corporation",
]

CURRENCIES = ["USD", "EUR", "KZT", "GBP"]

# По умолчанию используются только пояса без переходов на летнее время: база
# таймзон не входит в стандартную библиотеку и в офлайн-контейнере может
# отсутствовать, см. generator/timezones.py. Пояса с переходами задаются через
# config["company"]["timezone"] и требуют установленного tzdata.
TIMEZONES = [
    "Asia/Almaty",
    "Asia/Aqtobe",
]


def generate_company(seed: int, config: dict | None = None) -> dict:
    config = config or {}
    rng = random.Random(seed)

    token = hashlib.sha256(
        str(seed).encode()
    ).hexdigest()[:12].upper()

    company_name = config.get("company_name", rng.choice(COMPANIES))
    currency = config.get("base_currency", rng.choice(CURRENCIES))
    timezone = config.get("timezone", rng.choice(TIMEZONES))

    year = config.get("year", 2026)

    period_start = config.get(
        "period_start", date(year, 1, 1).isoformat()
    )

    period_end = config.get(
        "period_end", date(year, 12, 31).isoformat()
    )

    if currency not in CURRENCIES:
        raise ValueError(f"Unsupported currency: {currency}")

    if period_start >= period_end:
        raise ValueError("Invalid reporting period")

    return {
        "company": {
            "company_id": f"COMP-{token}",
            "name": company_name,
        },
        "manifest": {
            "schema_version": "1.0",
            "episode_id": f"EP-{token}",
            "base_currency": currency,
            "period_start": period_start,
            "period_end": period_end,
            "timezone": timezone,
            "rounding": "HALF_UP",
        },
    }
