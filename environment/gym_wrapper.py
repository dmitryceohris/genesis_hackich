import json
import string

import gymnasium as gym
from gymnasium import spaces

from environment.engine import FinAuditEnvironment


class GymAuditEnv(gym.Env):
    """Gymnasium adapter for FinAuditEnvironment.

    Actions and observations are JSON-encoded strings.
    The underlying audit action schema remains unchanged.
    """

    metadata = {"render_modes": []}

    def __init__(self):
        super().__init__()

        self.engine = FinAuditEnvironment()

        self.action_space = spaces.Text(
            min_length=2,
            max_length=1_000_000,
            charset=string.printable,
        )

        self.observation_space = spaces.Text(
            min_length=2,
            max_length=1_000_000,
            charset=string.printable,
        )

    @staticmethod
    def _encode(value):
        return json.dumps(
            value,
            ensure_ascii=True,
            default=str,
            allow_nan=False,
            separators=(",", ":"),
        )

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)

        observation, info = self.engine.reset(seed=seed)

        return self._encode(observation), info

    def step(self, action):
        if not isinstance(action, str):
            raise TypeError("GymAuditEnv actions must be JSON strings")

        try:
            parsed_action = json.loads(action)
            if not isinstance(parsed_action, dict):
                parsed_action = {"type": "__invalid_action__"}
        except json.JSONDecodeError:
            parsed_action = {"type": "__invalid_action__"}

        observation, reward, terminated, truncated, info = (
            self.engine.step(parsed_action)
        )

        return (
            self._encode(observation),
            float(reward),
            bool(terminated),
            bool(truncated),
            info,
        )

    def close(self):
        pass
