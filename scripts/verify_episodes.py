"""Независимая проверка эталона по всем эпизодам.

Запуск:

    python scripts/verify_episodes.py

Пишет ``artifacts/verification.json`` и завершается ненулевым кодом, если хотя
бы один эпизод не прошёл проверку: скрипт рассчитан на вызов из обязательной
команды ``make verify``.

Сейчас эпизоды берутся из фикстур. Когда появятся настоящие 10 train и 10 dev,
достаточно подменить источник в ``load_episodes``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.fixtures import build_episodes
from validator import verify_many

EPISODE_SOURCE = "hand-built fixtures (not the real generator)"


def load_episodes() -> dict[str, dict]:
    return build_episodes()


def main() -> int:
    artifacts = ROOT / "artifacts"
    artifacts.mkdir(exist_ok=True)

    report = verify_many(load_episodes())
    report["episode_source"] = EPISODE_SOURCE

    destination = artifacts / "verification.json"
    with destination.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")

    header = f"{'episode':13} {'ok':>5} {'issues':>7} {'found':>6} {'oracle':>7}  problems"
    print(header)
    print("-" * len(header))

    for verdict in report["verdicts"]:
        problems = []
        if verdict["invariant_violations"]:
            problems.append(f"invariants={len(verdict['invariant_violations'])}")
        if verdict["unreconstructed_issue_ids"]:
            problems.append(
                f"unreconstructed={','.join(verdict['unreconstructed_issue_ids'])}"
            )
        if verdict["undeclared_discrepancies"]:
            problems.append(
                f"undeclared={len(verdict['undeclared_discrepancies'])}"
            )
        if verdict["evidence_problems"]:
            problems.append(f"evidence={len(verdict['evidence_problems'])}")

        print(
            f"{verdict['episode_id']:13} {str(verdict['ok']):>5} "
            f"{verdict['declared_issue_count']:7d} "
            f"{len(verdict['reconstructed']):6d} "
            f"{verdict['oracle_reward']:7.3f}  {'; '.join(problems) or '-'}"
        )

    print()
    print(
        f"корректных эпизодов: {report['correct_episode_count']} из "
        f"{report['episode_count']} (доля {report['correct_share']})"
    )
    print(f"источник эпизодов: {EPISODE_SOURCE}")
    print(f"отчёт: {destination}")

    # Ненулевой код при провале обязательной проверки.
    return 0 if report["correct_episode_count"] == report["episode_count"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
