"""Адаптер жюри: три точки входа из определений проверок.

    generate_episode(seed, config, output_dir) -> None
    make_env()                                      # объект с reset и step
    score_episode(episode_dir, findings, inspection_steps) -> dict

Адаптер тонкий: он переводит наши внутренние имена и формы в те, которые
описаны в протоколе подключения, и ничего не решает за политику.

СОСТОЯНИЕ ЗОН. Адаптер делегирует настоящим реализациям, когда они появятся:

- ``generator.generate_episode`` — если пакет ``generator`` есть, вызывается
  он. Пока его нет, работает заглушка на эпизодах-фикстурах: интерфейс
  функционален, но даёт лишь четыре различных эпизода по кругу и не заполняет
  ``provenance``. Это **не** генератор из задания, и подменять его собой он не
  может.
- ``environment.make_env`` — если пакет ``environment`` есть, вызывается он.
  Пока его нет, работает тестовый двойник из ``tests/fake_env.py``, у которого
  нет лимита времени 60 секунд и различия режимов train/closed.

Что уже настоящее: ``score_episode`` — это рабочий оценщик, он читает
``truth.json`` из каталога эпизода и считает награду по общей формуле задания.

ГРАНИЦА ДОСТУПА. ``generate_episode``, пути, seed, config, truth, provenance и
``score_episode`` остаются на стороне жюри. Политика получает только объект из
``make_env`` и ничего больше: каталог эпизода ей не передаётся, оценщик она не
импортирует.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluator import score
from evaluator.episode_io import read_public_episode, read_truth, write_episode
from validator import public_snapshot, reachable_ids

# --- делегирование настоящим зонам, когда они появятся ------------------------

try:  # pragma: no cover - зависит от наличия чужой зоны
    from generator import generate_episode as _real_generate_episode
except ImportError:
    _real_generate_episode = None

try:  # pragma: no cover - зависит от наличия чужой зоны
    from environment import make_env as _real_make_env
except ImportError:
    _real_make_env = None

GENERATOR_IS_PLACEHOLDER = _real_generate_episode is None
ENVIRONMENT_IS_PLACEHOLDER = _real_make_env is None

# --- канонические имена протокола --------------------------------------------

CANONICAL_TABLES = ("ledger", "invoices", "payments", "fx")

#: Таблица правил политики — документированное расширение команды.
#: Правила политики обязаны быть достижимы через get_record, иначе набор
#: доказательств, ссылающийся на правило, требует недоступного факта.
DOCUMENTED_EXTRA_TABLES = ("policy",)

ALL_TABLES = CANONICAL_TABLES + DOCUMENTED_EXTRA_TABLES


def generate_episode(seed: int, config: dict, output_dir: str) -> None:
    """Создать эпизод в каталоге жюри.

    При наличии пакета ``generator`` вызывается он. Иначе работает заглушка на
    фикстурах: эпизод выбирается детерминированно по seed, поэтому один и тот
    же seed даёт один и тот же эпизод, но различных эпизодов всего четыре.
    """
    if _real_generate_episode is not None:  # pragma: no cover
        _real_generate_episode(seed, config, output_dir)
        return

    from tests.fixtures import EPISODE_IDS, build_episode

    episode_id = EPISODE_IDS[seed % len(EPISODE_IDS)]
    episode = build_episode(episode_id)

    # Эпизод обязан называться так, как его просят, иначе reset не сойдётся
    # по episode_id с заявкой агента.
    requested = config.get("episode_id") if isinstance(config, dict) else None
    if requested:
        episode["manifest"]["episode_id"] = requested
        episode["truth"]["episode_id"] = requested

    write_episode(episode, output_dir)


def make_env():
    """Объект среды с ``reset(seed, config)`` и ``step(action)``."""
    if _real_make_env is not None:  # pragma: no cover
        return _real_make_env()
    return _AdaptedEnv()


def score_episode(
    episode_dir: str, findings: dict, inspection_steps: int
) -> dict:
    """Оценить заявку по закрытому эталону эпизода.

    Возвращает ровно семь полей протокола. На невалидной структуре —
    ``return=-1``, остальные поля ``null``.

    Множество доступных ID считается из публичной части эпизода: выдуманное
    или недоступное доказательство не должно приносить TP.
    """
    truth = read_truth(episode_dir)
    snapshot = public_snapshot(read_public_episode(episode_dir))
    available = frozenset(reachable_ids(snapshot))

    report = score(
        findings,
        truth,
        inspection_steps,
        available_evidence_ids=available,
    )
    return report.to_judge_dict()


class _AdaptedEnv:
    """Перевод конверта действий и форм наблюдений протокола.

    Внутри работает тестовый двойник среды. Когда появится настоящая
    ``environment``, этот класс не нужен: ``make_env`` начнёт возвращать её.
    """

    def __init__(self) -> None:
        self._inner: Any = None
        self._episode: dict | None = None

    # --- интерфейс протокола -------------------------------------------------

    def reset(self, seed: int, config: dict) -> tuple[dict, dict]:
        from tests.fake_env import FakeEnv

        config = config or {}
        episode_dir = config.get("episode_dir")

        if episode_dir:
            # Закрытая ветка: загружается именно переданный эпизод. Ни новой
            # генерации, ни смены ID.
            episode = dict(read_public_episode(episode_dir))
            episode["truth"] = read_truth(episode_dir)
        else:
            # Открытая ветка: генератор команды с переданным seed.
            from tests.fixtures import EPISODE_IDS, build_episode

            episode = build_episode(EPISODE_IDS[(seed or 0) % len(EPISODE_IDS)])

        self._episode = episode
        self._inner = FakeEnv(episode)
        observation, info = self._inner.reset()
        return self._first_observation(observation), info

    def step(self, action: object) -> tuple[dict, float, bool, bool, dict]:
        inner_action = self._translate_action(action)
        observation, reward, terminated, truncated, info = self._inner.step(
            inner_action
        )
        name = action.get("name") if isinstance(action, dict) else None
        return (
            self._translate_observation(observation, name),
            reward,
            terminated,
            truncated,
            info,
        )

    # --- доверенная сторона --------------------------------------------------

    @property
    def inspection_steps(self) -> int:
        return self._inner.inspection_steps

    @property
    def submission(self):
        return self._inner.submission

    @property
    def truncated(self) -> bool:
        return self._inner.truncated

    # --- перевод -------------------------------------------------------------

    def _first_observation(self, observation: dict) -> dict:
        return {
            "task": observation.get("task", ""),
            "manifest": observation.get("manifest", {}),
            "policy": observation.get("policy", {}),
            "remaining_steps": observation.get("remaining_steps", 0),
            # Документированное расширение: список таблиц и типов ошибок.
            "tables": list(ALL_TABLES),
            "issue_types": observation.get("issue_types", []),
        }

    def _translate_action(self, action: object) -> dict:
        """``{"name": ..., "args": {...}}`` → наш плоский вид."""
        if not isinstance(action, dict):
            return {"name": None}
        name = action.get("name")
        args = action.get("args")
        if not isinstance(args, dict):
            # Плоский вид тоже принимается: протокол разрешает адаптеру
            # переводить оболочку, и обратная совместимость тут бесплатна.
            args = {
                key: value for key, value in action.items() if key != "name"
            }
        if name == "submit":
            return {"name": "submit", "findings": args.get("findings")}
        return {"name": name, **args}

    def _translate_observation(self, observation: dict, name: object) -> dict:
        remaining = observation.get("remaining_steps", 0)

        error = observation.get("error")
        if error is not None:
            return {
                "result": None,
                "error": {"code": error, "message": _ERROR_MESSAGES.get(error, error)},
                "remaining_steps": remaining,
            }

        result = observation.get("result")

        if name == "submit":
            result = {"accepted": True}
        elif name == "list_records" and isinstance(result, dict):
            # Протокол: records, а не rows.
            result = {
                "records": result.get("rows") or [],
                "next_cursor": result.get("next_cursor"),
            }
        elif name == "calculator" and isinstance(result, dict):
            # Протокол: десятичная строка, а не объект.
            result = result.get("value")

        return {"result": result, "error": None, "remaining_steps": remaining}


#: Краткие сообщения без путей, seed и закрытых данных.
_ERROR_MESSAGES = {
    "unknown_action": "неизвестное действие",
    "unknown_table": "неизвестная таблица",
    "not_found": "запись не найдена",
    "invalid_cursor": "неверный курсор",
    "invalid_limit": "неверный размер страницы",
    "invalid_expression": "выражение вне арифметической грамматики",
    "invalid_arguments": "неверные аргументы действия",
    "episode_finished": "эпизод завершён",
}
