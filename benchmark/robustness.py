from generator.generator import generate_episode
from agents.reconciliation_agent import detect_findings
from evaluator.scoring import score_findings

scenarios = [
    ("duplicate_invoice", {"error_types": ["duplicate_invoice"]}),
    ("payment_allocation", {"error_types": ["payment_allocation"]}),
    ("fx_rate", {"error_types": ["fx_rate"]}),
    ("accounting_period", {"error_types": ["accounting_period"]}),
    ("duplicate_period", {"interaction_scenario": "duplicate_period"}),
    ("payment_period", {"interaction_scenario": "payment_period"}),
]

total = 0
passed = 0
failures = []

for scenario_name, config in scenarios:
    for seed in range(100):
        episode = generate_episode(seed, config)

        public = episode["public"]
        truth = episode["private"]["truth"]

        predictions = detect_findings(public, episode["manifest"])

        result = score_findings(
            predictions,
            truth,
            inspection_steps=0,
        )

        total += 1

        if result["f1"] == 1.0:
            passed += 1
        else:
            failures.append({
                "scenario": scenario_name,
                "seed": seed,
                "f1": result["f1"],
                "truth": truth,
                "predictions": predictions,
            })

    print(f"{scenario_name}: completed")

print()
print(f"RESULT: {passed}/{total}")
print(f"FAILURES: {len(failures)}")

for failure in failures[:10]:
    print(failure)
