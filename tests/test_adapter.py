"""Адаптер жюри и формат эпизода на диске.

Проверяется путь, которым пойдёт жюри: создать эпизод в каталоге, загрузить
именно его, походить официальным конвертом действий, отправить заявку,
получить оценку из семи полей.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import judge_adapter
from evaluator import build_oracle_submission
from evaluator.episode_io import (
    PRIVATE_FILES,
    read_provenance,
    read_public_episode,
    read_truth,
    write_episode,
)
from tests.fixtures import build_episode


def action(name: str, **args) -> dict:
    """Официальный конверт: {"name": ..., "args": {...}}."""
    return {"name": name, "args": args}


class EpisodeIoTests(unittest.TestCase):
    def test_round_trip_preserves_integers_and_explicit_nulls(self):
        episode = build_episode("EP-INTERACT")
        with tempfile.TemporaryDirectory() as directory:
            write_episode(episode, directory)
            restored = read_public_episode(directory)

            original_rows = {row["row_id"]: row for row in episode["ledger"]}
            for row in restored["ledger"]:
                source = original_rows[row["row_id"]]
                with self.subTest(row=row["row_id"]):
                    # Деньги обязаны вернуться целыми, а не строками.
                    self.assertIsInstance(row["debit_minor"], int)
                    self.assertEqual(row["debit_minor"], source["debit_minor"])
                    self.assertEqual(row["credit_minor"], source["credit_minor"])
                    self.assertEqual(row["source_minor"], source["source_minor"])
                    # Отсутствующая ссылка — явный null, а не пустая строка.
                    self.assertEqual(row["invoice_id"], source["invoice_id"])

    def test_fx_rate_stays_a_decimal_string(self):
        episode = build_episode("EP-INTERACT")
        with tempfile.TemporaryDirectory() as directory:
            write_episode(episode, directory)
            restored = read_public_episode(directory)
            for row in restored["fx"]:
                with self.subTest(fx=row["fx_id"]):
                    self.assertIsInstance(row["rate"], str)
                    self.assertEqual(row["rate"], "1.25")

    def test_all_declared_files_are_written(self):
        episode = build_episode("EP-CUTOFF")
        with tempfile.TemporaryDirectory() as directory:
            write_episode(episode, directory)
            present = {path.name for path in Path(directory).iterdir()}
            self.assertEqual(
                present,
                {
                    "manifest.json",
                    "ledger.csv",
                    "invoices.jsonl",
                    "payments.jsonl",
                    "fx.csv",
                    "policy.json",
                    "truth.json",
                    "provenance.json",
                },
            )

    def test_public_reader_never_returns_the_reference(self):
        episode = build_episode("EP-CUTOFF")
        with tempfile.TemporaryDirectory() as directory:
            write_episode(episode, directory)
            public = read_public_episode(directory)
            serialized = json.dumps(public, ensure_ascii=False, default=str)

            self.assertNotIn("truth", public)
            self.assertNotIn("provenance", public)
            for forbidden in ("issue_id", "expected_amount_minor", "acceptable_evidence_sets"):
                self.assertNotIn(forbidden, serialized)

    def test_private_files_are_readable_only_through_trusted_helpers(self):
        episode = build_episode("EP-CUTOFF")
        with tempfile.TemporaryDirectory() as directory:
            write_episode(episode, directory)
            self.assertEqual(read_truth(directory)["episode_id"], "EP-CUTOFF")
            self.assertIn("episode_id", read_provenance(directory))
            self.assertEqual(PRIVATE_FILES, ("truth.json", "provenance.json"))

    def test_provenance_placeholder_is_explicit_about_being_empty(self):
        """Пока генератора нет, provenance честно помечен как незаполненный."""
        episode = build_episode("EP-CUTOFF")
        with tempfile.TemporaryDirectory() as directory:
            write_episode(episode, directory)
            provenance = read_provenance(directory)
            self.assertIn("note", provenance)


class AdapterProtocolTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.episode_dir = self._directory.name
        judge_adapter.generate_episode(1, {}, self.episode_dir)
        self.truth = read_truth(self.episode_dir)

    def tearDown(self):
        self._directory.cleanup()

    def test_reset_loads_exactly_the_given_episode(self):
        env = judge_adapter.make_env()
        observation, info = env.reset(
            999, {"mode": "closed", "episode_dir": self.episode_dir}
        )
        # Переданный seed не должен подменить эпизод другим.
        self.assertEqual(
            observation["manifest"]["episode_id"], self.truth["episode_id"]
        )
        self.assertEqual(info, {})

    def test_first_observation_has_the_protocol_shape(self):
        env = judge_adapter.make_env()
        observation, _ = env.reset(
            1, {"mode": "closed", "episode_dir": self.episode_dir}
        )
        for key in ("task", "manifest", "policy", "remaining_steps"):
            self.assertIn(key, observation)
        self.assertEqual(observation["remaining_steps"], 100)
        serialized = json.dumps(observation, ensure_ascii=False, default=str)
        for forbidden in ("truth", "seed", "issue_id", "expected_amount_minor"):
            self.assertNotIn(forbidden, serialized)

    def test_list_records_returns_records_and_cursor(self):
        env = judge_adapter.make_env()
        env.reset(1, {"mode": "closed", "episode_dir": self.episode_dir})
        observation, reward, terminated, truncated, _ = env.step(
            action("list_records", table="ledger", cursor=None, limit=50)
        )
        self.assertIsNone(observation["error"])
        self.assertIn("records", observation["result"])
        self.assertIn("next_cursor", observation["result"])
        self.assertEqual(reward, 0.0)
        self.assertFalse(terminated)
        self.assertFalse(truncated)
        self.assertEqual(observation["remaining_steps"], 99)

    def test_calculator_returns_a_decimal_string(self):
        """Проверка C09: 0.1+0.2 равно десятичному 0.3."""
        env = judge_adapter.make_env()
        env.reset(1, {"mode": "closed", "episode_dir": self.episode_dir})
        observation, *_ = env.step(action("calculator", expression="0.1+0.2"))
        self.assertIsNone(observation["error"])
        self.assertEqual(observation["result"], "0.3")

    def test_calculator_rejects_expressions_outside_the_grammar(self):
        """Проверка C10: обращение к файлу не исполняется."""
        env = judge_adapter.make_env()
        env.reset(1, {"mode": "closed", "episode_dir": self.episode_dir})
        observation, *_ = env.step(
            action("calculator", expression="open('/etc/passwd').read()")
        )
        self.assertIsNone(observation["result"])
        self.assertEqual(observation["error"]["code"], "invalid_expression")

    def test_errors_are_objects_with_a_code_and_a_short_message(self):
        env = judge_adapter.make_env()
        env.reset(1, {"mode": "closed", "episode_dir": self.episode_dir})
        observation, *_ = env.step(
            action("get_record", table="ledger", id="ID-DOES-NOT-EXIST")
        )
        self.assertIsNone(observation["result"])
        self.assertEqual(observation["error"]["code"], "not_found")
        self.assertIsInstance(observation["error"]["message"], str)
        # Ни путей, ни трассировок в сообщении.
        self.assertNotIn("/", observation["error"]["message"])
        self.assertNotIn("\\", observation["error"]["message"])

    def test_errors_consume_a_step(self):
        """Проверка C14: ошибка не даёт бесплатное действие."""
        env = judge_adapter.make_env()
        env.reset(1, {"mode": "closed", "episode_dir": self.episode_dir})
        env.step(action("list_records", table="ledger", cursor=None, limit=50))
        observation, *_ = env.step(action("unknown_action_name"))
        self.assertEqual(observation["remaining_steps"], 98)

    def test_submit_returns_only_accepted(self):
        env = judge_adapter.make_env()
        env.reset(1, {"mode": "closed", "episode_dir": self.episode_dir})
        payload = build_oracle_submission(self.truth)
        observation, reward, terminated, truncated, _ = env.step(
            action("submit", findings=payload)
        )
        self.assertEqual(observation["result"], {"accepted": True})
        self.assertTrue(terminated)
        self.assertFalse(truncated)
        # В закрытом режиме числовая награда интерфейса равна 0.
        self.assertEqual(reward, 0.0)


class ScoreEpisodeTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.episode_dir = self._directory.name
        judge_adapter.generate_episode(1, {}, self.episode_dir)
        self.truth = read_truth(self.episode_dir)

    def tearDown(self):
        self._directory.cleanup()

    def test_oracle_submission_scores_one(self):
        payload = build_oracle_submission(self.truth)
        result = judge_adapter.score_episode(self.episode_dir, payload, 0)
        self.assertEqual(
            set(result),
            {"tp", "fp", "fn", "precision", "recall", "f1", "return"},
        )
        self.assertEqual(result["return"], 1.0)
        self.assertEqual(result["fp"], 0)
        self.assertEqual(result["fn"], 0)

    def test_step_cost_is_applied(self):
        payload = build_oracle_submission(self.truth)
        result = judge_adapter.score_episode(self.episode_dir, payload, 10)
        self.assertAlmostEqual(result["return"], 0.98, delta=1e-9)

    def test_invalid_structure_returns_minus_one_and_nulls(self):
        payload = {"episode_id": self.truth["episode_id"], "findings": "not a list"}
        result = judge_adapter.score_episode(self.episode_dir, payload, 5)
        self.assertEqual(result["return"], -1.0)
        for key in ("tp", "fp", "fn", "precision", "recall", "f1"):
            with self.subTest(field=key):
                self.assertIsNone(result[key])

    def test_fabricated_evidence_does_not_earn_a_true_positive(self):
        """Пример M04 на сквозном пути, а не только в модульном тесте.

        Портится ровно один вывод из эталонной заявки. Он обязан стать FP, а
        его ошибка — FN; остальные выводы не задеты. Проверка записана через
        число ошибок эпизода, а не через константу: эпизоды генератора
        содержат больше одной ошибки, и захардкоженное число делало бы тест
        проверкой размера фикстуры.
        """
        payload = build_oracle_submission(self.truth)
        total = len(payload["findings"])
        if not total:
            self.skipTest("нужен эпизод с заявленной ошибкой")
        payload["findings"][0]["evidence_ids"].append("ID-THAT-DOES-NOT-EXIST")

        result = judge_adapter.score_episode(self.episode_dir, payload, 0)
        self.assertEqual(result["tp"], total - 1)
        self.assertEqual(result["fp"], 1)
        self.assertEqual(result["fn"], 1)

    def test_generation_is_deterministic_for_a_seed(self):
        with tempfile.TemporaryDirectory() as other:
            judge_adapter.generate_episode(1, {}, other)
            self.assertEqual(read_truth(other), self.truth)

    def test_placeholder_state_is_declared(self):
        """Заглушки помечены флагами, а не только текстом в документации."""
        self.assertIsInstance(judge_adapter.GENERATOR_IS_PLACEHOLDER, bool)
        self.assertIsInstance(judge_adapter.ENVIRONMENT_IS_PLACEHOLDER, bool)


if __name__ == "__main__":
    unittest.main()
