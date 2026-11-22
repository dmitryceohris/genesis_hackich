import csv
import json
from pathlib import Path

from environment.engine import FinAuditEnvironment
from agents.random_agent import run as run_random
from agents.reconciliation_agent import run as run_reconciliation
from agents.mark_all_agent import run as run_mark_all
from agents.oracle_agent import run as run_oracle


AGENTS = {
    "random": run_random,
    "reconciliation": run_reconciliation,
    "mark_all": run_mark_all,
    "oracle_evaluator_only": run_oracle,
}


def run_benchmark(seeds=range(100)):
    results = []

    for seed in seeds:
        for name, agent in AGENTS.items():
            env = FinAuditEnvironment()
            metrics = agent(env, seed)

            results.append({
                "agent": name,
                "seed": seed,
                "precision": metrics.get("precision", 0.0),
                "recall": metrics.get("recall", 0.0),
                "f1": metrics.get("f1", 0.0),
                "reward": metrics.get("reward", 0.0),
                "inspection_steps": metrics.get("inspection_steps", 0),
                "true_positives": metrics.get("true_positives", 0),
                "false_positives": metrics.get("false_positives", 0),
                "false_negatives": metrics.get("false_negatives", 0),
            })

    return results


def summarize(results):
    summary = {}

    for name in AGENTS:
        rows = [row for row in results if row["agent"] == name]
        count = len(rows)

        summary[name] = {
            metric: round(sum(row[metric] for row in rows) / count, 6)
            for metric in (
                "precision", "recall", "f1", "reward", "inspection_steps"
            )
        }

    return summary


def main():
    results = run_benchmark(range(100))
    summary = summarize(results)

    output_dir = Path("benchmark/results")
    output_dir.mkdir(parents=True, exist_ok=True)

    with (output_dir / "episodes.csv").open(
        "w", newline="", encoding="utf-8"
    ) as file:
        writer = csv.DictWriter(file, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)

    with (output_dir / "summary.json").open(
        "w", encoding="utf-8"
    ) as file:
        json.dump(summary, file, indent=2)

    print("\n===== BENCHMARK SUMMARY: 100 SEEDS =====")
    for name, metrics in summary.items():
        print(f"\n{name}")
        for key, value in metrics.items():
            print(f"  {key:20s}: {value}")

    print("\nSaved: benchmark/results/episodes.csv")
    print("Saved: benchmark/results/summary.json")


if __name__ == "__main__":
    main()
