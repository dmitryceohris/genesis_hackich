"""Среда: режимы награды, предел времени, оболочка протокола, генератор.

Проверяется поведение, которое отличает среду от ядра: что в закрытом режиме
число всегда 0, что усечение по времени и по шагам дают один и тот же итог,
что невалидная структура заявки приводит к −1 отдельным путём, и что эталон
через среду не виден.
"""

from __future__ import annotations

import json
import unittest

from environment import MODE_CLOSED, MODE_TRAIN, make_env
from environment.engine import EPISODE_TIME_LIMIT_SECONDS, AuditEnv
from evaluator.contract import MAX_STEPS
from evaluator.oracle import build_oracle_submission
from generator import DEFAULT_ERROR_TYPES, build_episode

SEED = 4


def _submit(findings):
    return {"name": "submit", "args": {"findings": findings}}


class _ManualClock:
    """Часы, которые двигаются только когда их двигают.

    Настоящий ``time.monotonic`` сделал бы тест проверкой скорости машины.
    """

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class ProtocolShapeTests(unittest.TestCase):
    def setUp(self):
        self.env = make_env(MODE_CLOSED, time_limit_seconds=None)
        self.observation, _ = self.env.reset(SEED, {})

    def test_first_observation_has_no_private_data(self):
        text = json.dumps(self.observation, ensure_ascii=False, default=str)
        for forbidden in ("truth", "issue_id", "provenance", "seed", "expected_amount"):
            with self.subTest(key=forbidden):
                self.assertNotIn(forbidden, text)

    def test_every_observation_has_the_three_protocol_fields(self):
        actions = [
            {"name": "list_records", "args": {"table": "ledger", "limit": 1}},
            {"name": "get_record", "args": {"table": "policy", "id": "POLICY-FX"}},
            {"name": "get_document", "args": {"doc_id": "НЕТ-ТАКОГО"}},
            {"name": "calculator", "args": {"expression": "1+1"}},
            {"name": "ничего", "args": {}},
        ]
        for action in actions:
            observation, _, _, _, _ = self.env.step(action)
            with self.subTest(action=action["name"]):
                self.assertEqual(
                    sorted(observation), ["error", "remaining_steps", "result"]
                )

    def test_error_is_an_object_with_a_code_from_the_closed_list(self):
        observation, _, _, _, _ = self.env.step({"name": "list_records", "args": {"table": "нет"}})
        self.assertEqual(observation["result"], None)
        self.assertEqual(observation["error"]["code"], "unknown_table")
        self.assertIsInstance(observation["error"]["message"], str)

    def test_list_records_returns_records_and_a_cursor(self):
        observation, _, _, _, _ = self.env.step(
            {"name": "list_records", "args": {"table": "invoices", "limit": 2}}
        )
        self.assertEqual(len(observation["result"]["records"]), 2)
        self.assertEqual(observation["result"]["next_cursor"], "2")

    def test_calculator_returns_a_decimal_string(self):
        observation, _, _, _, _ = self.env.step(
            {"name": "calculator", "args": {"expression": "0.1+0.2"}}
        )
        self.assertEqual(observation["result"], "0.3")

    def test_policy_rules_are_reachable_by_get_record(self):
        for rule in ("POLICY-FX", "POLICY-PERIOD", "POLICY-ALLOC", "POLICY-DUP"):
            observation, _, _, _, _ = self.env.step(
                {"name": "get_record", "args": {"table": "policy", "id": rule}}
            )
            with self.subTest(rule=rule):
                self.assertIsNone(observation["error"])
                self.assertEqual(observation["result"]["policy_id"], rule)

    def test_flat_action_is_accepted_too(self):
        observation, _, _, _, _ = self.env.step(
            {"name": "list_records", "table": "fx", "limit": 1}
        )
        self.assertIsNone(observation["error"])


class RewardModeTests(unittest.TestCase):
    def test_closed_mode_never_returns_a_number(self):
        env = make_env(MODE_CLOSED, time_limit_seconds=None)
        env.reset(SEED, {})
        payload = build_oracle_submission(env._episode["truth"])

        _, reward, _, _, _ = env.step(
            {"name": "list_records", "args": {"table": "ledger", "limit": 1}}
        )
        self.assertEqual(reward, 0.0)

        _, reward, terminated, _, _ = env.step(_submit(payload))
        self.assertTrue(terminated)
        self.assertEqual(reward, 0.0, "в закрытом режиме и последний шаг даёт 0")
        # Итог существует, но забирает его доверенная сторона.
        self.assertEqual(env.report()["f1"], 1.0)

    def test_train_mode_returns_the_terminal_reward(self):
        env = make_env(MODE_TRAIN, time_limit_seconds=None)
        env.reset(SEED, {})
        payload = build_oracle_submission(env._episode["truth"])

        _, reward, terminated, _, _ = env.step(_submit(payload))
        self.assertTrue(terminated)
        self.assertEqual(reward, 1.0)

    def test_structurally_invalid_submission_is_minus_one(self):
        """Невалидная структура — отдельный путь, а не F1 = 0."""
        env = make_env(MODE_TRAIN, time_limit_seconds=None)
        env.reset(SEED, {})

        _, reward, terminated, _, _ = env.step(_submit({"findings": "не список"}))
        self.assertTrue(terminated, "невалидный submit обязан завершать эпизод")
        self.assertEqual(reward, -1.0)

        report = env.report()
        self.assertEqual(report["return"], -1.0)
        for field in ("tp", "fp", "fn", "precision", "recall", "f1"):
            with self.subTest(field=field):
                self.assertIsNone(report[field])

    def test_submit_cannot_be_retried_after_it_landed(self):
        """Иначе мусорную заявку можно подавать бесплатно до попадания."""
        env = make_env(MODE_TRAIN, time_limit_seconds=None)
        env.reset(SEED, {})
        env.step(_submit({"findings": "не список"}))

        observation, reward, terminated, _, _ = env.step(
            _submit(build_oracle_submission(env._episode["truth"]))
        )
        self.assertTrue(terminated)
        self.assertEqual(observation["error"]["code"], "episode_finished")
        self.assertEqual(env.report()["return"], -1.0, "итог первой заявки не переписан")


class TruncationTests(unittest.TestCase):
    def test_hundredth_inspection_step_truncates_with_an_empty_submission(self):
        env = make_env(MODE_CLOSED, time_limit_seconds=None)
        env.reset(SEED, {})
        action = {"name": "list_records", "args": {"table": "ledger", "limit": 1}}

        for _ in range(MAX_STEPS - 1):
            _, _, terminated, truncated, _ = env.step(action)
            self.assertFalse(terminated or truncated)

        _, _, terminated, truncated, _ = env.step(action)
        self.assertTrue(truncated)
        self.assertFalse(terminated, "усечение — не нормальное завершение")
        self.assertIsNone(env.submission)
        self.assertTrue(env.truncated)
        self.assertFalse(env.timed_out)

    def test_time_limit_truncates_the_same_way(self):
        clock = _ManualClock()
        episode = build_episode(SEED)
        inner = AuditEnv(episode, time_limit_seconds=60.0, clock=clock)
        inner.reset()

        inner.step({"name": "list_records", "table": "ledger", "limit": 1})
        self.assertFalse(inner.truncated)

        clock.now = 60.0
        _, _, terminated, truncated, _ = inner.step(
            {"name": "list_records", "table": "ledger", "limit": 1}
        )
        self.assertTrue(truncated)
        self.assertFalse(terminated)
        self.assertTrue(inner.timed_out)
        self.assertIsNone(inner.submission)

    def test_time_limit_default_matches_the_task(self):
        self.assertEqual(EPISODE_TIME_LIMIT_SECONDS, 60.0)
        self.assertEqual(make_env()._time_limit, 60.0)

    def test_truncation_on_a_clean_book_is_not_an_invalid_submission(self):
        """Два разных итога обязаны оставаться различимыми."""
        from tests.fixtures import build_episode as build_fixture

        clean = build_fixture("EP-CLEAN")
        inner = AuditEnv(clean, max_steps=2)
        inner.reset()
        inner.step({"name": "list_records", "table": "ledger", "limit": 1})
        inner.step({"name": "list_records", "table": "ledger", "limit": 1})

        from evaluator import score

        truncated_report = score(None, clean["truth"], inner.inspection_steps, truncated=True)
        invalid_report = score({"findings": 5}, clean["truth"], inner.inspection_steps)
        self.assertTrue(truncated_report.valid)
        self.assertFalse(invalid_report.valid)
        self.assertNotEqual(truncated_report.reward, invalid_report.reward)


class EpisodeSourceTests(unittest.TestCase):
    def test_same_seed_gives_the_same_episode(self):
        self.assertEqual(build_episode(SEED), build_episode(SEED))

    def test_different_seeds_give_different_episodes(self):
        self.assertNotEqual(
            build_episode(SEED)["manifest"]["episode_id"],
            build_episode(SEED + 1)["manifest"]["episode_id"],
        )

    def test_episode_declares_only_defaults_enabled_types(self):
        episode = build_episode(SEED)
        kinds = {issue["type"] for issue in episode["truth"]["issues"]}
        self.assertTrue(kinds)
        self.assertEqual(len(kinds), len(DEFAULT_ERROR_TYPES))

    def test_every_declared_issue_has_a_provenance_record(self):
        episode = build_episode(SEED)
        declared = {issue["issue_id"] for issue in episode["truth"]["issues"]}
        recorded = {item["error_id"] for item in episode["provenance"]["records"]}
        self.assertEqual(declared, recorded)

    def test_all_four_error_types_are_declared_and_quantified(self):
        """Четыре типа задания, и у каждого сумма в минимальных единицах.

        ``fx_conversion`` держится на валютном плече платежа: без него
        искажение курса не меняет ни одной суммы, ошибка становится
        недоказуемой и в эталон попасть не может.
        """
        episode = build_episode(SEED)
        declared = {issue["type"] for issue in episode["truth"]["issues"]}
        self.assertEqual(
            declared,
            {"duplicate_invoice", "payment_allocation", "fx_conversion", "period_cutoff"},
        )
        for issue in episode["truth"]["issues"]:
            with self.subTest(issue=issue["issue_id"]):
                self.assertIs(type(issue["expected_amount_minor"]), int)
                self.assertGreater(issue["expected_amount_minor"], 0)
                self.assertTrue(issue["acceptable_evidence_sets"])

    def test_undeclarable_errors_are_reported_not_hidden(self):
        """Ошибку, которую реконструкция не выводит, эталон не объявляет.

        Правило проверяется на собранном вручную случае, а не на настройке
        генератора: все четыре типа сейчас доказуемы, и подогнать генератор
        под этот тест значило бы испортить данные ради теста.
        """
        from integration.episode_adapter import adapt_episode

        from generator.generator import generate_episode as build_raw

        raw = build_raw(SEED, {"error_types": list(DEFAULT_ERROR_TYPES)})
        raw["private"]["truth"].append(
            {
                "error_id": "ERR-9999",
                "type": "fx_rate",
                "affected_ids": [raw["public"]["fx"][0]["fx_id"]],
                "claimed_amount_minor": None,
                "currency": raw["public"]["fx"][0]["quote_currency"],
                "evidence_ids": [raw["public"]["fx"][0]["fx_id"]],
                "explanation": "ошибка, которой нет в публичных записях",
            }
        )
        raw["private"]["provenance"].append(
            {
                "error_id": "ERR-9999",
                "type": "fx_rate",
                "operation": "none",
                "source_ids": [],
                "generated_ids": [],
            }
        )

        episode = adapt_episode(raw)
        undeclarable = episode["provenance"]["undeclarable"]
        self.assertEqual([item["error_id"] for item in undeclarable], ["ERR-9999"])
        self.assertNotIn(
            "ERR-9999", {issue["issue_id"] for issue in episode["truth"]["issues"]}
        )
        self.assertNotIn(
            "ERR-9999", {item["error_id"] for item in episode["provenance"]["records"]}
        )

    def test_episode_dir_branch_loads_exactly_that_episode(self):
        import tempfile

        from evaluator.episode_io import write_episode

        with tempfile.TemporaryDirectory() as directory:
            episode = build_episode(SEED)
            write_episode(episode, directory)

            env = make_env(MODE_CLOSED, time_limit_seconds=None)
            env.reset(999, {"episode_dir": directory})
            self.assertEqual(
                env._episode["manifest"]["episode_id"],
                episode["manifest"]["episode_id"],
                "переданный каталог не должен подменяться новой генерацией",
            )


class ModeValidationTests(unittest.TestCase):
    def test_unknown_mode_is_rejected_at_construction(self):
        with self.assertRaises(ValueError):
            make_env("полузакрытый")

    def test_step_before_reset_is_an_error(self):
        with self.assertRaises(RuntimeError):
            make_env().step({"name": "calculator", "args": {"expression": "1"}})


if __name__ == "__main__":
    unittest.main()


class DerivationCrossCheckTests(unittest.TestCase):
    """Сверка двух независимых выводов об одной ошибке.

    Эталон берёт суммы и затронутые записи из реконструкции, поэтому по этим
    полям проверка валидатора нестрогая. Расхождение между тем, что записал
    генератор при внесении, и тем, что восстановлено из публичных записей,
    обязано быть видно в provenance, а не молча исчезать.
    """

    def setUp(self):
        self.episode = build_episode(SEED)
        self.disagreements = self.episode["provenance"]["derivation_disagreements"]

    def test_disagreements_are_recorded_with_both_values(self):
        for item in self.disagreements:
            with self.subTest(error=item["error_id"], field=item["field"]):
                self.assertIn("generator", item)
                self.assertIn("reconstruction", item)
                self.assertEqual(item["adopted"], "reconstruction")
                self.assertNotEqual(item["generator"], item["reconstruction"])

    def test_fx_and_allocation_are_cross_validated(self):
        """По этим двум типам обе стороны считают одно и то же.

        Значит их суммы и записи подтверждены независимо, а не только
        собственным выводом валидатора.
        """
        agreed = {"fx_conversion", "payment_allocation"}
        for item in self.disagreements:
            with self.subTest(error=item["error_id"]):
                self.assertNotIn(item["official_type"], agreed)

    def test_every_disagreement_names_a_declared_issue(self):
        declared = {issue["issue_id"] for issue in self.episode["truth"]["issues"]}
        for item in self.disagreements:
            with self.subTest(error=item["error_id"]):
                self.assertIn(item["error_id"], declared)
