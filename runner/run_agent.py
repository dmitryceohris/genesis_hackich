"""Прогон политики внутри контейнера изоляции агента.

Запуск:

    python -s -P -m runner.run_agent --episode-dir /episode --out /out/submission.json

Что здесь намеренно НЕ делается:

- не считается награда. Оценку делает доверенная сторона вне контейнера, и
  внутрь оценщик не копируется;
- не читается ``truth.json`` и ``provenance.json``. Каталог эпизода монтируется
  доверенной стороной, и чтение идёт через среду, а не напрямую;
- не пишется ничего, кроме одного файла заявки в переданный каталог вывода.

Флаги ``-s -P`` в точке входа обязательны: ``-P`` убирает текущий каталог из
``sys.path``, ``-s`` — пользовательский site-packages. Без них подложенный
рядом модуль с именем из стандартной библиотеки исполнился бы при импорте.
Целиком ``-I`` не годится: он заодно игнорирует ``PYTHONPATH``, а код в
контейнере лежит именно по нему.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from environment import MODE_CLOSED, make_env

POLICIES = {
    "reconcile": ("policies.reconciliation_agent", "ReconciliationAgent"),
    "flag_all": ("policies.mark_all_agent", "MarkAllAgent"),
    "random": ("policies.random_agent", "RandomExplorer"),
}


def load_policy(name: str):
    if name not in POLICIES:
        raise SystemExit(
            f"неизвестная политика {name!r}; доступны: {', '.join(sorted(POLICIES))}"
        )
    module_name, class_name = POLICIES[name]
    module = __import__(module_name, fromlist=[class_name])
    return getattr(module, class_name)()


def run(policy, episode_dir: str, seed: int) -> dict:
    """Провести эпизод до завершения и вернуть заявку с числом шагов."""
    env = make_env(MODE_CLOSED)
    config = {"episode_dir": episode_dir} if episode_dir else {}
    observation, _ = env.reset(seed, config)

    generator = policy.run(observation)

    try:
        action = next(generator)
    except StopIteration:
        action = {"name": "submit", "args": {"findings": None}}

    while True:
        observation, _, terminated, truncated, _ = env.step(action)
        if terminated or truncated:
            break
        try:
            action = generator.send(observation)
        except StopIteration:
            action = {"name": "submit", "args": {"findings": None}}

    generator.close()

    return {
        "submission": env.submission,
        "inspection_steps": env.inspection_steps,
        "truncated": env.truncated,
        "timed_out": env.timed_out,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", default="reconcile")
    parser.add_argument("--episode-dir", default="")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", default="")
    arguments = parser.parse_args(argv)

    result = run(load_policy(arguments.policy), arguments.episode_dir, arguments.seed)
    payload = json.dumps(result, ensure_ascii=False, indent=2, default=str)

    if arguments.out:
        destination = Path(arguments.out)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(payload + "\n", encoding="utf-8")
        print(f"заявка записана: {destination}")
    else:
        sys.stdout.write(payload + "\n")

    findings = (result["submission"] or {}).get("findings")
    print(
        f"шагов: {result['inspection_steps']}, "
        f"выводов: {len(findings) if findings else 0}, "
        f"усечение: {result['truncated']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
