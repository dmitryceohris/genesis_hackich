"""Оболочка протокола: конверт действий, формы наблюдений, режимы награды.

Ядро (``environment/engine.py``) работает с плоскими действиями и награду не
считает. Этот слой добавляет ровно то, что требует протокол жюри:

1. конверт ``{"name": ..., "args": {...}}`` разворачивается в плоский вид;
2. наблюдение всегда имеет три поля — ``result``, ``error``, ``remaining_steps``;
3. ошибка приходит объектом ``{"code", "message"}`` из закрытого списка кодов,
   без путей, seed и таймингов;
4. в закрытом режиме числовая награда интерфейса всегда 0, в обучающем на
   ``submit`` возвращается терминальная награда официального оценщика.

Почему награда считается здесь, а не в ядре: ядро не должно знать ни об
оценщике, ни о режиме. Тогда один и тот же эпизод нельзя оценить двумя разными
способами, а закрытый режим отличается от обучающего одной строкой, а не
отдельной копией среды.
"""

from __future__ import annotations

from typing import Any

from environment.engine import EPISODE_TIME_LIMIT_SECONDS, PUBLIC_TABLES, AuditEnv
from evaluator.contract import ISSUE_TYPES

MODE_CLOSED = "closed"
MODE_TRAIN = "train"
MODES = (MODE_CLOSED, MODE_TRAIN)

#: Краткие сообщения к кодам ошибок. Ни путей, ни seed, ни чисел эталона.
ERROR_MESSAGES = {
    "unknown_action": "неизвестное действие",
    "unknown_table": "неизвестная таблица",
    "not_found": "запись не найдена",
    "invalid_cursor": "неверный курсор",
    "invalid_limit": "неверный размер страницы",
    "invalid_expression": "выражение вне арифметической грамматики",
    "invalid_arguments": "неверные аргументы действия",
    "episode_finished": "эпизод завершён",
}


class ProtocolEnv:
    """Среда в терминах протокола: ``reset(seed, config)`` и ``step(action)``."""

    def __init__(
        self,
        mode: str = MODE_CLOSED,
        *,
        time_limit_seconds: float | None = EPISODE_TIME_LIMIT_SECONDS,
        max_steps: int | None = None,
    ) -> None:
        if mode not in MODES:
            raise ValueError(f"режим должен быть одним из {MODES}, получено {mode!r}")
        self.mode = mode
        self._time_limit = time_limit_seconds
        self._max_steps = max_steps
        self._inner: AuditEnv | None = None
        self._episode: dict | None = None

    # --- интерфейс протокола -------------------------------------------------

    def reset(self, seed: int = 0, config: dict | None = None) -> tuple[dict, dict]:
        """Загрузить или сгенерировать эпизод и вернуть первое наблюдение.

        ``config["episode_dir"]`` — закрытая ветка: берётся именно переданный
        каталог, без новой генерации и без смены ID. Иначе эпизод строится
        генератором по ``seed``.
        """
        config = dict(config or {})
        episode_dir = config.pop("episode_dir", None)

        if episode_dir:
            from evaluator.episode_io import read_public_episode, read_truth

            episode = dict(read_public_episode(episode_dir))
            episode["truth"] = read_truth(episode_dir)
        else:
            from generator import build_episode

            episode = build_episode(seed, config)

        self._episode = episode
        kwargs: dict[str, Any] = {"time_limit_seconds": self._time_limit}
        if self._max_steps is not None:
            kwargs["max_steps"] = self._max_steps
        self._inner = AuditEnv(episode, **kwargs)

        observation, info = self._inner.reset()
        return self._first_observation(observation), dict(info)

    def step(self, action: object) -> tuple[dict, float, bool, bool, dict]:
        if self._inner is None:
            raise RuntimeError("перед step нужен reset")

        name = action.get("name") if isinstance(action, dict) else None
        observation, _, terminated, truncated, info = self._inner.step(
            self._translate_action(action)
        )

        reward = 0.0
        if self.mode == MODE_TRAIN and (terminated or truncated):
            reward = self._terminal_reward()

        return (
            self._translate_observation(observation, name),
            reward,
            terminated,
            truncated,
            dict(info),
        )

    # --- доверенная сторона --------------------------------------------------
    # Читает оркестратор. Агент этих значений не видит: они не попадают ни в
    # наблюдение, ни в info.

    @property
    def inspection_steps(self) -> int:
        return self._inner.inspection_steps

    @property
    def submission(self) -> Any:
        return self._inner.submission

    @property
    def truncated(self) -> bool:
        return self._inner.truncated

    @property
    def timed_out(self) -> bool:
        return self._inner.timed_out

    def report(self) -> dict:
        """Отчёт оценщика по завершённому эпизоду, семь полей протокола."""
        from evaluator import score

        from validator.snapshot import public_snapshot, reachable_ids

        episode = self._episode or {}
        available = frozenset(reachable_ids(public_snapshot(episode)))
        return score(
            self._inner.submission,
            episode["truth"],
            self._inner.inspection_steps,
            truncated=self._inner.truncated,
            available_evidence_ids=available,
        ).to_judge_dict()

    # --- внутреннее ----------------------------------------------------------

    def _terminal_reward(self) -> float:
        value = self.report().get("return")
        return 0.0 if value is None else float(value)

    def _first_observation(self, observation: dict) -> dict:
        return {
            "task": observation.get("task", ""),
            "manifest": observation.get("manifest", {}),
            "policy": observation.get("policy", {}),
            "remaining_steps": observation.get("remaining_steps", 0),
            "tables": list(PUBLIC_TABLES),
            "issue_types": list(ISSUE_TYPES),
        }

    def _translate_action(self, action: object) -> dict:
        """``{"name": ..., "args": {...}}`` → плоский вид ядра."""
        if not isinstance(action, dict):
            return {"name": None}
        name = action.get("name")
        args = action.get("args")
        if not isinstance(args, dict):
            # Плоский вид тоже принимается: обратная совместимость бесплатна.
            args = {key: value for key, value in action.items() if key != "name"}
        if name == "submit":
            return {"name": "submit", "findings": args.get("findings")}
        return {"name": name, **args}

    def _translate_observation(self, observation: dict, name: object) -> dict:
        remaining = observation.get("remaining_steps", 0)

        error = observation.get("error")
        if error is not None:
            return {
                "result": None,
                "error": {"code": error, "message": ERROR_MESSAGES.get(error, error)},
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
