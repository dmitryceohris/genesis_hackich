import json
import gymnasium as gym

from environment.gym_wrapper import GymAuditEnv


def test_gym_environment_interface():
    env = GymAuditEnv()

    assert isinstance(env, gym.Env)

    observation, info = env.reset(seed=42)

    assert isinstance(observation, str)
    assert isinstance(json.loads(observation), dict)
    assert isinstance(info, dict)
    assert env.observation_space.contains(observation)

    env.close()


def test_gym_reset_is_deterministic():
    env = GymAuditEnv()

    obs1, _ = env.reset(seed=42)
    obs2, _ = env.reset(seed=42)

    assert obs1 == obs2

    env.close()


def test_gym_step_interface():
    env = GymAuditEnv()

    env.reset(seed=42)

    action = json.dumps({"type": "__invalid_action__"})

    observation, reward, terminated, truncated, info = env.step(action)

    assert isinstance(observation, str)
    assert env.observation_space.contains(observation)
    assert isinstance(reward, float)
    assert isinstance(terminated, bool)
    assert isinstance(truncated, bool)
    assert isinstance(info, dict)

    env.close()
