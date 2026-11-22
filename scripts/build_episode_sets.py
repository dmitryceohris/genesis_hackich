"""Записать наборы эпизодов train и dev каталогами на диск.

Запуск:

    python scripts/build_episode_sets.py [каталог]

По умолчанию пишет в ``episodes/``. Каждый эпизод — отдельный каталог из
восьми файлов (``evaluator/episode_io.py``): шесть публичных и закрытые
``truth.json`` с ``provenance.json``.

Сиды и настройки заданы явно и записаны в ``index.json`` рядом с наборами:
без этого набор нельзя воспроизвести, а воспроизводимость — отдельный
критерий. Два набора различаются не только сидами, но и настройками: в dev
включены сценарии взаимодействия дефектов, потому что отложенный набор обязан
проверять не те же случаи, что обучающий.

Каждый записанный эпизод сразу прогоняется через независимый валидатор. Если
эпизод не проходит, он остаётся на диске, но помечен в ``index.json`` и код
возврата ненулевой: лучше увидеть дефект здесь, чем на оценивании.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluator.episode_io import write_episode
from generator import DEFAULT_ERROR_TYPES, build_episode
from validator import verify_episode

#: Сколько эпизодов в каждом наборе.
SET_SIZE = 10

#: Сценарии взаимодействия дефектов из generator/error_injection.py.
DEV_SCENARIOS = ("duplicate_period", "payment_period", None)


def _train_candidates():
    """Обучающий набор: настройки по умолчанию, сиды с нуля."""
    for seed in range(0, 200):
        yield {"seed": seed, "config": {}}


def _dev_candidates():
    """Отложенный набор: другие сиды и включённые взаимодействия дефектов."""
    for index in range(0, 200):
        yield {
            "seed": 100 + index,
            "config": {
                "error_types": list(DEFAULT_ERROR_TYPES),
                "interaction_scenario": DEV_SCENARIOS[index % len(DEV_SCENARIOS)],
            },
        }


def build_set(name: str, candidates, destination: Path) -> tuple[list[dict], list[dict]]:
    """Отобрать и записать ``SET_SIZE`` эпизодов из потока кандидатов.

    Правило отбора простое и записано в индексе: берутся первые по порядку
    сиды, которые строятся и проходят независимую проверку. Пропущенные тоже
    перечислены с причиной — иначе отбор был бы незаметной подгонкой набора
    под собственный валидатор.
    """
    directory = destination / name
    if directory.exists():
        shutil.rmtree(directory)
    directory.mkdir(parents=True)

    entries: list[dict] = []
    skipped: list[dict] = []

    for spec in candidates:
        if len(entries) == SET_SIZE:
            break

        try:
            episode = build_episode(spec["seed"], spec["config"])
        except Exception as error:  # дефект внесения на этом сиде
            skipped.append({
                "seed": spec["seed"],
                "config": spec["config"],
                "reason": f"{type(error).__name__}: {error}",
            })
            print(f"  пропуск seed={spec['seed']:<4} {type(error).__name__}")
            continue

        verdict = verify_episode(episode)

        if not verdict.ok:
            skipped.append({
                "seed": spec["seed"],
                "config": spec["config"],
                "reason": (
                    f"инварианты={[item.code for item in verdict.invariant_violations]} "
                    f"незаявленных={len(verdict.undeclared_discrepancies)} "
                    f"доказательства={len(verdict.evidence_problems)}"
                ),
            })
            print(
                f"  пропуск seed={spec['seed']:<4} не прошёл независимую проверку"
            )
            continue

        episode_id = episode["manifest"]["episode_id"]
        write_episode(episode, directory / episode_id)
        provenance = episode["provenance"]

        entries.append(
            {
                "episode_id": episode_id,
                "seed": spec["seed"],
                "config": spec["config"],
                "issue_count": len(episode["truth"]["issues"]),
                "issue_types": sorted(
                    {issue["type"] for issue in episode["truth"]["issues"]}
                ),
                "valid": verdict.ok,
                "oracle_reward": verdict.oracle_reward,
                "undeclarable": len(provenance["undeclarable"]),
                "undeclared_discrepancies": len(verdict.undeclared_discrepancies),
                "derivation_disagreements": len(
                    provenance["derivation_disagreements"]
                ),
            }
        )

        print(
            f"  ок   {episode_id}  seed={spec['seed']:<4} "
            f"ошибок={entries[-1]['issue_count']} "
            f"oracle={verdict.oracle_reward:+.3f}"
        )

    if len(entries) < SET_SIZE:
        raise RuntimeError(
            f"набор {name}: удалось собрать {len(entries)} эпизодов из {SET_SIZE}"
        )

    return entries, skipped


def main() -> int:
    destination = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "episodes"

    print("train:")
    train, train_skipped = build_set("train", _train_candidates(), destination)
    print("dev:")
    dev, dev_skipped = build_set("dev", _dev_candidates(), destination)

    index = {
        "train": train,
        "dev": dev,
        "skipped": {"train": train_skipped, "dev": dev_skipped},
        "selection_rule": (
            "первые по порядку сиды, которые строятся и проходят независимую "
            "проверку; пропущенные перечислены в skipped с причиной"
        ),
        "evaluator_contract_version": __import__(
            "evaluator.contract", fromlist=["x"]
        ).EVALUATOR_CONTRACT_VERSION,
    }

    with (destination / "index.json").open("w", encoding="utf-8") as handle:
        json.dump(index, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")

    print()
    print(f"записано эпизодов: {len(train) + len(dev)} в {destination}")
    print(
        f"пропущено кандидатов: train {len(train_skipped)}, dev {len(dev_skipped)}"
    )
    print(f"индекс: {destination / 'index.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
