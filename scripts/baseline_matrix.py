"""Прогон всех базовых политик по всем эпизодам и сводный отчёт.

Запуск:

    python scripts/baseline_matrix.py

Пишет в ``artifacts/``:

- ``trajectories.jsonl`` — по строке на фактический шаг, без закрытого эталона;
- ``metrics.csv`` — по строке на пару «эпизод × политика»;
- ``summary.json`` — агрегаты по политикам.

Сейчас эпизоды берутся из фикстур, а среда — тестовый двойник: настоящие
10 train + 10 dev и настоящая ``environment/`` ещё не готовы. Источник данных
указан в ``summary.json`` полем ``episode_source``, чтобы отчёт нельзя было
принять за прогон на реальном наборе.
"""

from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluator import EVALUATOR_CONTRACT_VERSION, build_oracle_submission, score
from policies import MarkAllAgent, RandomExplorer, ReconciliationAgent
from environment.engine import AuditEnv, run_policy
from scripts.episodes import EPISODE_IDS, build_episode
from validator import public_snapshot, reachable_ids

from scripts.episodes import EPISODE_SOURCE  # noqa: E402

CSV_COLUMNS = [
    "episode_id",
    "policy",
    "valid",
    "tp",
    "fp",
    "fn",
    "precision",
    "recall",
    "f1",
    "reward",
    "inspection_steps",
    "truncated",
    "wall_ms",
]


def policies():
    return [ReconciliationAgent(), MarkAllAgent(), RandomExplorer()]


def run_all() -> tuple[list[dict], list[dict]]:
    rows: list[dict] = []
    trajectory_lines: list[dict] = []

    for episode_id in EPISODE_IDS:
        for policy in policies():
            episode = build_episode(episode_id)
            available = frozenset(reachable_ids(public_snapshot(episode)))
            env = AuditEnv(episode)

            started = time.perf_counter()
            outcome = run_policy(env, policy)
            report = score(
                outcome["submission"],
                env.truth,
                outcome["inspection_steps"],
                truncated=outcome["truncated"],
                available_evidence_ids=available,
            )
            elapsed_ms = (time.perf_counter() - started) * 1000

            rows.append(
                {
                    "episode_id": episode_id,
                    "policy": policy.name,
                    "valid": report.valid,
                    "tp": report.tp,
                    "fp": report.fp,
                    "fn": report.fn,
                    "precision": round(report.precision, 6),
                    "recall": round(report.recall, 6),
                    "f1": round(report.f1, 6),
                    "reward": round(report.reward, 6),
                    "inspection_steps": report.inspection_steps,
                    "truncated": report.truncated,
                    "wall_ms": round(elapsed_ms, 3),
                }
            )
            for step in outcome["trajectory"]:
                trajectory_lines.append({"policy": policy.name, **step})

        # Oracle считается на стороне оценщика и шагов не расходует.
        episode = build_episode(episode_id)
        oracle_report = score(
            build_oracle_submission(episode["truth"]),
            episode["truth"],
            0,
            available_evidence_ids=frozenset(
                reachable_ids(public_snapshot(episode))
            ),
        )
        rows.append(
            {
                "episode_id": episode_id,
                "policy": "oracle",
                "valid": oracle_report.valid,
                "tp": oracle_report.tp,
                "fp": oracle_report.fp,
                "fn": oracle_report.fn,
                "precision": round(oracle_report.precision, 6),
                "recall": round(oracle_report.recall, 6),
                "f1": round(oracle_report.f1, 6),
                "reward": round(oracle_report.reward, 6),
                "inspection_steps": 0,
                "truncated": False,
                "wall_ms": 0.0,
            }
        )

    return rows, trajectory_lines


def summarize(rows: list[dict]) -> dict:
    clean_episodes = {
        episode_id
        for episode_id in EPISODE_IDS
        if not build_episode(episode_id)["truth"]["issues"]
    }

    by_policy: dict[str, list[dict]] = {}
    for row in rows:
        by_policy.setdefault(row["policy"], []).append(row)

    summary = {
        "evaluator_contract_version": EVALUATOR_CONTRACT_VERSION,
        "episode_source": EPISODE_SOURCE,
        "episode_count": len(EPISODE_IDS),
        "clean_episodes": sorted(clean_episodes),
        "policies": {},
    }

    for name, policy_rows in sorted(by_policy.items()):
        total_tp = sum(row["tp"] for row in policy_rows)
        total_fp = sum(row["fp"] for row in policy_rows)
        total_fn = sum(row["fn"] for row in policy_rows)

        clean_rows = [row for row in policy_rows if row["episode_id"] in clean_episodes]
        false_accusations = sum(1 for row in clean_rows if row["fp"] > 0)

        summary["policies"][name] = {
            # Средний F1 по эпизодам и micro-P/R по суммарным счётчикам — это
            # разные агрегаты, поэтому показываются оба и подписаны.
            "mean_f1_over_episodes": round(
                sum(row["f1"] for row in policy_rows) / len(policy_rows), 6
            ),
            "mean_reward_over_episodes": round(
                sum(row["reward"] for row in policy_rows) / len(policy_rows), 6
            ),
            "micro_precision": round(
                total_tp / (total_tp + total_fp) if total_tp + total_fp else 0.0, 6
            ),
            "micro_recall": round(
                total_tp / (total_tp + total_fn) if total_tp + total_fn else 0.0, 6
            ),
            "total_tp": total_tp,
            "total_fp": total_fp,
            "total_fn": total_fn,
            "mean_inspection_steps": round(
                sum(row["inspection_steps"] for row in policy_rows)
                / len(policy_rows),
                3,
            ),
            "truncation_count": sum(1 for row in policy_rows if row["truncated"]),
            "invalid_submission_count": sum(
                1 for row in policy_rows if not row["valid"]
            ),
            "false_accusations_on_clean_books": false_accusations,
            "clean_book_count": len(clean_rows),
        }

    return summary


def main() -> int:
    artifacts = ROOT / "artifacts"
    artifacts.mkdir(exist_ok=True)

    rows, trajectory_lines = run_all()
    summary = summarize(rows)

    with (artifacts / "metrics.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    with (artifacts / "trajectories.jsonl").open("w", encoding="utf-8") as handle:
        for line in trajectory_lines:
            handle.write(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n")

    with (artifacts / "summary.json").open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")

    header = f"{'episode':13} {'policy':10} {'tp/fp/fn':10} {'f1':>6} {'steps':>6} {'reward':>9}"
    print(header)
    print("-" * len(header))
    for row in rows:
        counts = f"{row['tp']}/{row['fp']}/{row['fn']}"
        print(
            f"{row['episode_id']:13} {row['policy']:10} {counts:10} "
            f"{row['f1']:6.3f} {row['inspection_steps']:6d} {row['reward']:+9.4f}"
        )

    print()
    print(f"episode source: {EPISODE_SOURCE}")
    print(f"artifacts written to {artifacts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
