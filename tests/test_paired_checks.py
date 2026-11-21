"""Парные проверки: воспроизводимость и обобщение.

Критерий на 15 баллов: повтор seed и действий точен, а перестановка и смена ID
сохраняют ответ oracle и награду с учётом новых ID.

Пара строится из одного исходного эпизода: у членов пары одинаковые сделка,
валюта, сумма и число ошибок. Карта замены остаётся здесь, у проверяющего, и
агенту не передаётся.
"""

from __future__ import annotations

import json
import unittest

from evaluator import build_oracle_submission, score
from policies import ReconciliationAgent
from tests.fake_env import FakeEnv, run_policy
from tests.fixtures import EPISODE_IDS, build_episode
from tests.transformations import (
    apply_id_map,
    build_id_map,
    collect_ids,
    permute_records,
    rename_ids,
)


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


def run_reconcile(episode: dict) -> tuple:
    env = FakeEnv(episode)
    outcome = run_policy(env, ReconciliationAgent())
    report = score(
        outcome["submission"],
        env.truth,
        outcome["inspection_steps"],
        truncated=outcome["truncated"],
    )
    return outcome, report


class ExactReplayTests(unittest.TestCase):
    """Одинаковые эпизод и действия дают одинаковые переходы и награду."""

    def test_same_actions_reproduce_observations_and_reward(self):
        for episode_id in EPISODE_IDS:
            with self.subTest(episode=episode_id):
                first_outcome, first_report = run_reconcile(build_episode(episode_id))
                second_outcome, second_report = run_reconcile(build_episode(episode_id))

                self.assertEqual(
                    canonical(first_outcome["trajectory"]),
                    canonical(second_outcome["trajectory"]),
                    "переходы обязаны совпадать побайтно",
                )
                self.assertEqual(first_report.to_dict(), second_report.to_dict())

    def test_matching_result_is_stable_across_runs(self):
        episode = build_episode("EP-INTERACT")
        first = score(build_oracle_submission(episode["truth"]), episode["truth"], 0)
        second = score(build_oracle_submission(episode["truth"]), episode["truth"], 0)
        self.assertEqual(first.matched_pairs, second.matched_pairs)


class PermutationTests(unittest.TestCase):
    """Перестановка порядка записей ничего не меняет по сути."""

    def test_oracle_reward_survives_permutation(self):
        for episode_id in EPISODE_IDS:
            with self.subTest(episode=episode_id):
                original = build_episode(episode_id)
                permuted = permute_records(build_episode(episode_id))

                original_report = score(
                    build_oracle_submission(original["truth"]), original["truth"], 0
                )
                permuted_report = score(
                    build_oracle_submission(permuted["truth"]), permuted["truth"], 0
                )
                self.assertEqual(original_report.reward, permuted_report.reward)
                self.assertEqual(original_report.tp, permuted_report.tp)

    def test_reconcile_still_solves_a_permuted_episode(self):
        for episode_id in EPISODE_IDS:
            with self.subTest(episode=episode_id):
                _, original_report = run_reconcile(build_episode(episode_id))
                _, permuted_report = run_reconcile(
                    permute_records(build_episode(episode_id))
                )
                self.assertEqual(original_report.f1, permuted_report.f1)
                self.assertEqual(original_report.tp, permuted_report.tp)
                self.assertEqual(original_report.fp, permuted_report.fp)


class RenamingTests(unittest.TestCase):
    """Смена всех ID сохраняет ответ oracle с учётом новых ID."""

    def test_id_map_is_a_bijection_over_every_identifier(self):
        for episode_id in EPISODE_IDS:
            with self.subTest(episode=episode_id):
                episode = build_episode(episode_id)
                id_map = build_id_map(episode)
                self.assertEqual(len(set(id_map.values())), len(id_map))
                # Ни один ID не остался без замены.
                self.assertEqual(set(id_map), set(collect_ids(episode)))

    def test_no_original_identifier_survives_renaming(self):
        episode = build_episode("EP-INTERACT")
        renamed, id_map = rename_ids(episode)
        surviving = set(collect_ids(renamed)) & set(id_map)
        self.assertEqual(surviving, set())

    def test_oracle_answer_maps_through_the_id_map(self):
        for episode_id in EPISODE_IDS:
            with self.subTest(episode=episode_id):
                episode = build_episode(episode_id)
                renamed, id_map = rename_ids(episode)

                # Ответ oracle на исходном эпизоде, переведённый по карте,
                # обязан совпасть с ответом oracle на переименованном.
                translated = apply_id_map(
                    build_oracle_submission(episode["truth"]), id_map
                )
                direct = build_oracle_submission(renamed["truth"])
                self.assertEqual(canonical(translated), canonical(direct))

    def test_reward_is_identical_after_renaming(self):
        for episode_id in EPISODE_IDS:
            with self.subTest(episode=episode_id):
                episode = build_episode(episode_id)
                renamed, _ = rename_ids(episode)

                original = score(
                    build_oracle_submission(episode["truth"]), episode["truth"], 0
                )
                after = score(
                    build_oracle_submission(renamed["truth"]), renamed["truth"], 0
                )
                self.assertEqual(original.reward, after.reward)
                self.assertEqual(
                    (original.tp, original.fp, original.fn),
                    (after.tp, after.fp, after.fn),
                )

    def test_reconcile_does_not_depend_on_literal_identifiers(self):
        """Политика сверки читает правила из политики эпизода, не из констант."""
        for episode_id in EPISODE_IDS:
            with self.subTest(episode=episode_id):
                _, original_report = run_reconcile(build_episode(episode_id))
                renamed, _ = rename_ids(build_episode(episode_id))
                _, renamed_report = run_reconcile(renamed)
                self.assertEqual(original_report.f1, renamed_report.f1)
                self.assertEqual(original_report.tp, renamed_report.tp)


class CombinedPairTests(unittest.TestCase):
    """Перестановка и переименование вместе — так строится парная проверка."""

    def test_full_pair_preserves_oracle_and_reward(self):
        for episode_id in EPISODE_IDS:
            with self.subTest(episode=episode_id):
                episode = build_episode(episode_id)
                transformed, id_map = rename_ids(permute_records(build_episode(episode_id)))

                original = score(
                    build_oracle_submission(episode["truth"]), episode["truth"], 0
                )
                after = score(
                    build_oracle_submission(transformed["truth"]),
                    transformed["truth"],
                    0,
                )
                self.assertEqual(original.reward, after.reward)

                translated = apply_id_map(
                    build_oracle_submission(episode["truth"]), id_map
                )
                direct = build_oracle_submission(transformed["truth"])
                self.assertEqual(canonical(translated), canonical(direct))

    def test_pair_members_declare_the_same_number_of_issues(self):
        for episode_id in EPISODE_IDS:
            with self.subTest(episode=episode_id):
                episode = build_episode(episode_id)
                transformed, _ = rename_ids(permute_records(build_episode(episode_id)))
                self.assertEqual(
                    len(episode["truth"]["issues"]),
                    len(transformed["truth"]["issues"]),
                )


if __name__ == "__main__":
    unittest.main()
