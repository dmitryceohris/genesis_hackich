"""Набор эпизодов для обязательного прогона.

Два источника, и оба нужны.

``gen-NN`` — эпизоды генератора по сидам. Это то, что получает жюри: четыре
типа дефектов в настройке по умолчанию, взаимодействия, provenance.

``fixture-*`` — собранные руками случаи, которые генератор не выдаёт и выдавать
не должен: чистая книга без единой ошибки, эпизод с одной ошибкой каждого
типа, эпизод со взаимодействием. Они проверяют края формулы награды (молчание
на чистой книге, усечение) и остаются в наборе как регрессия: если генератор
однажды перестанет порождать какой-то тип, сломается не только отчёт, но и
конкретный тест.

Отчёты помечают источник каждого эпизода, чтобы прогон на сидах нельзя было
принять за прогон на фикстурах и наоборот.
"""

from __future__ import annotations

from copy import deepcopy

#: Сиды генератора, попадающие в обязательный прогон.
GENERATED_SEEDS: tuple[int, ...] = tuple(range(10))

EPISODE_SOURCE = (
    f"{len(GENERATED_SEEDS)} эпизодов генератора (сиды "
    f"{GENERATED_SEEDS[0]}..{GENERATED_SEEDS[-1]}) плюс собранные руками фикстуры"
)

_GENERATED_PREFIX = "gen-"
_FIXTURE_PREFIX = "fixture-"


def _fixture_ids() -> list[str]:
    from tests.fixtures import EPISODE_IDS

    return list(EPISODE_IDS)


def episode_ids() -> list[str]:
    """Имена всех эпизодов набора в устойчивом порядке."""
    generated = [f"{_GENERATED_PREFIX}{seed:02d}" for seed in GENERATED_SEEDS]
    return generated + [f"{_FIXTURE_PREFIX}{name}" for name in _fixture_ids()]


def build_episode(name: str) -> dict:
    """Собрать эпизод по имени. Каждый вызов отдаёт свежую копию."""
    if name.startswith(_GENERATED_PREFIX):
        from generator import build_episode as build_generated

        return build_generated(int(name[len(_GENERATED_PREFIX) :]))

    if name.startswith(_FIXTURE_PREFIX):
        from tests.fixtures import build_episode as build_fixture

        return deepcopy(build_fixture(name[len(_FIXTURE_PREFIX) :]))

    raise KeyError(f"неизвестный эпизод: {name!r}")


def build_episodes() -> dict[str, dict]:
    """Весь набор целиком: имя эпизода → эпизод."""
    return {name: build_episode(name) for name in episode_ids()}


#: Для скриптов, которые писались против списка имён.
EPISODE_IDS = episode_ids()
