"""Базовые политики на фикстурах.

Главная проверка здесь — решаемость: простой алгоритм сверки обязан
восстанавливать каждый дефект из публичных наблюдений и прикладывать
достаточный набор доказательств. Если он не может, значит эталон требует
недоступного факта, и это дефект генератора, а не политики.
"""

from __future__ import annotations

import json
import unittest

from evaluator import MAX_FINDINGS, build_oracle_submission, score, validate_submission
from policies import MarkAllAgent, Policy, RandomExplorer, ReconciliationAgent
from tests.fake_env import FakeEnv, run_policy
from tests.fixtures import EPISODE_IDS, build_episode

EXPECTED_ISSUE_COUNT = {
    "EP-CLEAN": 0,
    "EP-CUTOFF": 1,
    "EP-INTERACT": 2,
    "EP-DUP": 1,
}


def evaluate(episode: dict, policy: Policy):
    env = FakeEnv(episode)
    outcome = run_policy(env, policy)
    report = score(
        outcome["submission"],
        env.truth,
        outcome["inspection_steps"],
        truncated=outcome["truncated"],
    )
    return outcome, report


class ReconciliationTests(unittest.TestCase):
    def test_every_fixture_is_solvable_from_observations(self):
        for episode_id in EPISODE_IDS:
            with self.subTest(episode=episode_id):
                episode = build_episode(episode_id)
                _, report = evaluate(episode, ReconciliationAgent())
                self.assertTrue(report.valid)
                self.assertEqual(
                    report.tp,
                    EXPECTED_ISSUE_COUNT[episode_id],
                    "сверка обязана найти все заявленные дефекты",
                )
                self.assertEqual(report.fp, 0, "ложных обвинений быть не должно")
                self.assertEqual(report.fn, 0)
                self.assertEqual(report.f1, 1.0)

    def test_reconcile_stays_silent_on_a_clean_book_with_distractors(self):
        """Разбитый платёж, возврат и равные абонентские суммы — не дефекты."""
        _, report = evaluate(build_episode("EP-CLEAN"), ReconciliationAgent())
        self.assertEqual(report.tp, 0)
        self.assertEqual(report.fp, 0)
        self.assertGreater(report.reward, 0)

    def test_reconcile_separates_interacting_defects(self):
        """Два дефекта на одном платеже разложены по причинам.

        Суммы находок описывают разные измерения, поэтому их сложение не даёт
        корректировку конкретного счёта. Проверяется именно раздельность.
        """
        episode = build_episode("EP-INTERACT")
        outcome, report = evaluate(episode, ReconciliationAgent())
        self.assertEqual(report.tp, 2)

        claimed = {
            item["type"]: item["claimed_amount_minor"]
            for item in outcome["submission"]["findings"]
        }
        self.assertEqual(claimed["fx_conversion"], 300)
        self.assertEqual(claimed["payment_allocation"], 1250)

    def test_reconcile_fits_the_step_budget_with_room_for_submit(self):
        for episode_id in EPISODE_IDS:
            with self.subTest(episode=episode_id):
                outcome, report = evaluate(
                    build_episode(episode_id), ReconciliationAgent()
                )
                self.assertFalse(outcome["truncated"])
                self.assertLess(report.inspection_steps, 100)
                self.assertIsNotNone(outcome["submission"])


class MarkAllTests(unittest.TestCase):
    def test_mark_all_submits_a_structurally_valid_but_terrible_answer(self):
        for episode_id in EPISODE_IDS:
            with self.subTest(episode=episode_id):
                episode = build_episode(episode_id)
                outcome, report = evaluate(episode, MarkAllAgent())
                self.assertTrue(
                    report.valid,
                    "атака обязана быть валидной, иначе тест проверяет валидацию",
                )
                self.assertLessEqual(
                    len(outcome["submission"]["findings"]), MAX_FINDINGS
                )
                self.assertEqual(report.reward, -1.0)

    def test_mark_all_never_beats_reconcile(self):
        for episode_id in EPISODE_IDS:
            with self.subTest(episode=episode_id):
                _, attack = evaluate(build_episode(episode_id), MarkAllAgent())
                _, honest = evaluate(
                    build_episode(episode_id), ReconciliationAgent()
                )
                self.assertGreater(honest.reward, attack.reward)

    def test_the_cap_actually_binds_on_a_wide_book(self):
        """На широкой книге разметка упирается в лимит 30, а не в размер данных.

        Фикстуры маленькие, поэтому набор записей здесь синтетический: иначе
        лимит не проверяется вовсе и тест только выглядит проверкой.
        """
        invoices = [
            {
                "doc_id": f"D-INV-{index}",
                "invoice_id": f"INV-{index}",
                "entity_id": "ENT-1",
                "total_minor": 1000 + index,
            }
            for index in range(10)
        ]
        ledger = [
            {"row_id": f"R-{index}", "invoice_id": f"INV-{index}"} for index in range(10)
        ]

        raw = MarkAllAgent()._build(ledger, invoices, [], "USD")
        self.assertGreater(len(raw), MAX_FINDINGS, "иначе лимит не достигается")

        capped = raw[:MAX_FINDINGS]
        self.assertTrue(validate_submission(
            {"episode_id": "EP-W", "findings": capped}, "EP-W"
        ).ok)

    def test_one_finding_over_the_limit_is_rejected_structurally(self):
        """31 вывод — уже невалидная заявка, а не дорогая атака."""
        invoices = [
            {
                "doc_id": f"D-INV-{index}",
                "invoice_id": f"INV-{index}",
                "entity_id": "ENT-1",
                "total_minor": 1000 + index,
            }
            for index in range(10)
        ]
        ledger = [
            {"row_id": f"R-{index}", "invoice_id": f"INV-{index}"} for index in range(10)
        ]
        oversized = MarkAllAgent()._build(ledger, invoices, [], "USD")[: MAX_FINDINGS + 1]

        validation = validate_submission(
            {"episode_id": "EP-W", "findings": oversized}, "EP-W"
        )
        self.assertFalse(validation.ok)
        self.assertEqual(validation.reason, "too_many_findings")

    def test_mark_all_respects_its_cap_on_every_fixture(self):
        for episode_id in EPISODE_IDS:
            with self.subTest(episode=episode_id):
                outcome, _ = evaluate(build_episode(episode_id), MarkAllAgent())
                self.assertLessEqual(
                    len(outcome["submission"]["findings"]), MAX_FINDINGS
                )


class RandomExplorerTests(unittest.TestCase):
    def test_random_explorer_is_reproducible(self):
        episode_a = build_episode("EP-INTERACT")
        episode_b = build_episode("EP-INTERACT")
        first, _ = evaluate(episode_a, RandomExplorer(seed=4242))
        second, _ = evaluate(episode_b, RandomExplorer(seed=4242))
        self.assertEqual(
            json.dumps(first["trajectory"], sort_keys=True, ensure_ascii=False),
            json.dumps(second["trajectory"], sort_keys=True, ensure_ascii=False),
        )

    def test_random_explorer_survives_limited_errors(self):
        """Неизвестные ID, лимит 51 и мусорное выражение не ломают среду."""
        episode = build_episode("EP-CLEAN")
        outcome, report = evaluate(episode, RandomExplorer(seed=1, budget=60))
        self.assertTrue(report.valid)
        errors = [
            step["observation"].get("error")
            for step in outcome["trajectory"]
            if step["observation"].get("error")
        ]
        self.assertTrue(errors, "случайная политика обязана наткнуться на ошибки")
        # Ошибки ограничены кодами: ни путей, ни трассировок.
        for code in errors:
            self.assertIsInstance(code, str)
            self.assertNotIn("/", code)
            self.assertNotIn("\\", code)
            self.assertNotIn("Traceback", code)

    def test_random_explorer_always_reserves_a_step_for_submit(self):
        episode = build_episode("EP-CUTOFF")
        outcome, _ = evaluate(episode, RandomExplorer(seed=9, budget=500))
        self.assertFalse(outcome["truncated"])
        self.assertIsNotNone(outcome["submission"])


class OracleIsolationTests(unittest.TestCase):
    def test_oracle_is_not_a_policy(self):
        """Oracle не экспортируется из ``policies``: он живёт у оценщика."""
        import policies

        exported = set(policies.__all__)
        self.assertNotIn("OracleAgent", exported)
        self.assertNotIn("oracle", {name.lower() for name in exported})

    def test_oracle_beats_every_baseline(self):
        for episode_id in EPISODE_IDS:
            with self.subTest(episode=episode_id):
                episode = build_episode(episode_id)
                oracle = score(
                    build_oracle_submission(episode["truth"]), episode["truth"], 0
                )
                self.assertEqual(oracle.reward, 1.0)
                for policy in (ReconciliationAgent(), MarkAllAgent(), RandomExplorer()):
                    _, report = evaluate(build_episode(episode_id), policy)
                    self.assertGreaterEqual(oracle.reward, report.reward)


class LeakageTests(unittest.TestCase):
    """Эталон не должен утекать в наблюдения и траектории."""

    def test_no_private_field_reaches_the_trajectory(self):
        episode = build_episode("EP-INTERACT")
        canary = "CANARY-7f3a91c0-DO-NOT-LEAK"
        episode["truth"]["canary"] = canary
        for issue in episode["truth"]["issues"]:
            issue["canary"] = canary

        outcome, _ = evaluate(episode, ReconciliationAgent())
        serialized = json.dumps(
            outcome["trajectory"], sort_keys=True, ensure_ascii=False, default=str
        )

        self.assertNotIn(canary, serialized)
        for forbidden in (
            "acceptable_evidence_sets",
            "expected_amount_minor",
            "issue_id",
            "provenance",
            "seed",
            "truth",
        ):
            self.assertNotIn(forbidden, serialized, f"утечка поля {forbidden}")

    def test_initial_observation_carries_no_reference_data(self):
        env = FakeEnv(build_episode("EP-CUTOFF"))
        observation, info = env.reset()
        serialized = json.dumps(
            [observation, info], sort_keys=True, ensure_ascii=False, default=str
        )
        for forbidden in ("issue_id", "expected_amount_minor", "truth", "seed"):
            self.assertNotIn(forbidden, serialized)
        self.assertEqual(info, {})

    def test_inspection_reward_is_zero_in_every_mode(self):
        env = FakeEnv(build_episode("EP-CUTOFF"))
        env.reset()
        for action in (
            {"name": "list_records", "table": "ledger", "cursor": None, "limit": 5},
            {"name": "get_record", "table": "ledger", "id": "R-12"},
            {"name": "unknown_action"},
        ):
            _, reward, terminated, truncated, _ = env.step(action)
            self.assertEqual(reward, 0.0)
            self.assertFalse(terminated)
            self.assertFalse(truncated)


if __name__ == "__main__":
    unittest.main()
