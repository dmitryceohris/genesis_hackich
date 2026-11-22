import random


def run(env, seed=42):
    """Random exploration baseline. It intentionally submits no findings."""
    rng = random.Random(seed)
    observation, _ = env.reset(seed=seed)

    record_types = ["ledger", "invoices", "payments", "fx"]

    for _ in range(10):
        record_type = rng.choice(record_types)
        offset = rng.randint(0, 5) * 50

        observation, _, terminated, truncated, _ = env.step({
            "type": "list_records",
            "record_type": record_type,
            "offset": offset,
            "limit": 50,
        })

        if terminated or truncated:
            break

    return env.step({"type": "submit", "findings": []})[-1]
