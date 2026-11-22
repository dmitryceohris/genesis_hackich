"""Независимая проверка эталона: положительные и отрицательные случаи.

Отрицательные тесты здесь важнее положительных. Валидатор, который на чистых
данных говорит «всё хорошо», но не ловит внесённый дефект, не проверяет ничего
и создаёт ложную уверенность. Поэтому на каждый код нарушения есть тест,
который этот дефект вносит и требует, чтобы проверка сработала.
"""

from __future__ import annotations

import unittest
from fractions import Fraction

from evaluator import score
from policies import ReconciliationAgent
from policies.money import convert_minor as decimal_convert
from tests.fake_env import FakeEnv, run_policy
from tests.fixtures import EPISODE_IDS, build_episode, build_episodes
from validator import (
    check_invariants,
    convert_minor as fraction_convert,
    public_snapshot,
    reachable_ids,
    reconstruct,
    round_half_even,
    verify_episode,
    verify_many,
)
from validator.invariants import (
    CODE_BOTH_SIDES_SET,
    CODE_DANGLING_REFERENCE,
    CODE_DUPLICATE_PUBLIC_ID,
    CODE_INVOICE_TOTAL_MISMATCH,
    CODE_JOURNAL_UNBALANCED,
    CODE_MISSING_FX_FIXING,
    CODE_NON_INTEGER_MONEY,
    CODE_PRIVATE_FIELD,
    CODE_RECORD_COUNT_MISMATCH,
    CODE_RULE_ID_UNREACHABLE,
    CODE_UNKNOWN_CURRENCY,
)
from validator.verify import (
    PROBLEM_EMPTY_EVIDENCE_SET,
    PROBLEM_NO_EVIDENCE_SETS,
    PROBLEM_SET_NOT_SUFFICIENT,
    PROBLEM_SET_TOO_LARGE,
    PROBLEM_UNREACHABLE_ID,
)


def codes(violations) -> set[str]:
    return {item.code for item in violations}


def invariant_codes(episode: dict) -> set[str]:
    return codes(check_invariants(public_snapshot(episode)))


def find_row(episode: dict, row_id: str) -> dict:
    for row in episode["ledger"]:
        if row["row_id"] == row_id:
            return row
    raise KeyError(row_id)


def find_invoice(episode: dict, invoice_id: str) -> dict:
    for invoice in episode["invoices"]:
        if invoice["invoice_id"] == invoice_id:
            return invoice
    raise KeyError(invoice_id)


def issue_of(episode: dict, issue_id: str) -> dict:
    for issue in episode["truth"]["issues"]:
        if issue["issue_id"] == issue_id:
            return issue
    raise KeyError(issue_id)


class CleanFixtureTests(unittest.TestCase):
    """На корректных эпизодах проверка обязана молчать."""

    def test_every_fixture_passes_verification(self):
        for episode_id in EPISODE_IDS:
            with self.subTest(episode=episode_id):
                verdict = verify_episode(build_episode(episode_id))
                self.assertEqual(verdict.invariant_violations, ())
                self.assertEqual(verdict.unreconstructed_issue_ids, ())
                self.assertEqual(verdict.undeclared_discrepancies, ())
                self.assertEqual(verdict.evidence_problems, ())
                self.assertEqual(verdict.oracle_reward, 1.0)
                self.assertTrue(verdict.ok)

    def test_declared_issues_are_all_reconstructed(self):
        for episode_id in EPISODE_IDS:
            with self.subTest(episode=episode_id):
                episode = build_episode(episode_id)
                verdict = verify_episode(episode)
                self.assertEqual(
                    len(verdict.matched_issue_ids),
                    len(episode["truth"]["issues"]),
                )

    def test_aggregate_report_counts_correct_episodes(self):
        report = verify_many(build_episodes())
        self.assertEqual(report["episode_count"], len(EPISODE_IDS))
        self.assertEqual(report["correct_episode_count"], len(EPISODE_IDS))
        self.assertEqual(report["correct_share"], 1.0)

    def test_reconstruction_cannot_see_the_reference(self):
        """``reconstruct`` принимает снимок, а не эпизод.

        Тест держит это свойство: порча эталона не меняет восстановление.
        """
        episode = build_episode("EP-INTERACT")
        before = reconstruct(public_snapshot(episode))

        episode["truth"]["issues"] = []
        episode["truth"]["hint"] = "fx_conversion 300 on R-23"
        after = reconstruct(public_snapshot(episode))

        self.assertEqual(
            [item.to_dict() for item in before], [item.to_dict() for item in after]
        )


class InvariantFaultInjectionTests(unittest.TestCase):
    """На каждый код нарушения — внесённый дефект."""

    def test_unbalanced_journal_is_caught(self):
        episode = build_episode("EP-DUP")
        find_row(episode, "R-31")["debit_minor"] = 4600
        self.assertIn(CODE_JOURNAL_UNBALANCED, invariant_codes(episode))

    def test_invoice_total_mismatch_is_caught(self):
        episode = build_episode("EP-CUTOFF")
        find_invoice(episode, "INV-17")["total_minor"] = 25001
        self.assertIn(CODE_INVOICE_TOTAL_MISMATCH, invariant_codes(episode))

    def test_duplicate_public_id_is_caught(self):
        episode = build_episode("EP-CUTOFF")
        find_row(episode, "R-13")["row_id"] = "R-12"
        self.assertIn(CODE_DUPLICATE_PUBLIC_ID, invariant_codes(episode))

    def test_dangling_reference_is_caught(self):
        episode = build_episode("EP-CUTOFF")
        find_row(episode, "R-12")["invoice_id"] = "INV-DOES-NOT-EXIST"
        self.assertIn(CODE_DANGLING_REFERENCE, invariant_codes(episode))

    def test_leaked_private_field_is_caught(self):
        episode = build_episode("EP-CUTOFF")
        episode["manifest"]["seed"] = 12345
        self.assertIn(CODE_PRIVATE_FIELD, invariant_codes(episode))

    def test_leaked_expected_amount_is_caught(self):
        episode = build_episode("EP-CUTOFF")
        find_row(episode, "R-12")["expected_amount_minor"] = 25000
        self.assertIn(CODE_PRIVATE_FIELD, invariant_codes(episode))

    def test_undeclared_currency_exponent_is_caught(self):
        episode = build_episode("EP-INTERACT")
        del episode["manifest"]["currency_exponents"]["EUR"]
        self.assertIn(CODE_UNKNOWN_CURRENCY, invariant_codes(episode))

    def test_missing_fx_fixing_is_caught(self):
        episode = build_episode("EP-INTERACT")
        episode["fx"] = [row for row in episode["fx"] if row["fx_id"] != "FX-2"]
        self.assertIn(CODE_MISSING_FX_FIXING, invariant_codes(episode))

    def test_record_count_mismatch_is_caught(self):
        episode = build_episode("EP-CUTOFF")
        episode["manifest"]["record_counts"]["ledger"] = 99
        self.assertIn(CODE_RECORD_COUNT_MISMATCH, invariant_codes(episode))

    def test_unreachable_rule_id_is_caught(self):
        """Регрессия: ровно этот дефект проверка нашла в фикстурах."""
        episode = build_episode("EP-CUTOFF")
        episode["policy"] = [
            record
            for record in episode["policy"]
            if record["policy_id"] != "POLICY-PERIOD"
        ]
        self.assertIn(CODE_RULE_ID_UNREACHABLE, invariant_codes(episode))

    def test_row_with_both_sides_is_caught(self):
        episode = build_episode("EP-CUTOFF")
        find_row(episode, "R-12")["credit_minor"] = 1
        self.assertIn(CODE_BOTH_SIDES_SET, invariant_codes(episode))

    def test_non_integer_money_is_caught(self):
        episode = build_episode("EP-CUTOFF")
        find_row(episode, "R-12")["debit_minor"] = 250.0
        self.assertIn(CODE_NON_INTEGER_MONEY, invariant_codes(episode))

    def test_boolean_money_is_caught(self):
        episode = build_episode("EP-CUTOFF")
        find_invoice(episode, "INV-17")["total_minor"] = True
        self.assertIn(CODE_NON_INTEGER_MONEY, invariant_codes(episode))


class ReferenceFaultInjectionTests(unittest.TestCase):
    """Дефекты самого эталона, а не публичных данных."""

    def test_wrong_expected_amount_is_caught(self):
        episode = build_episode("EP-CUTOFF")
        issue_of(episode, "ISS-CUTOFF-1")["expected_amount_minor"] = 24999

        verdict = verify_episode(episode)
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.unreconstructed_issue_ids, ("ISS-CUTOFF-1",))
        # То же расхождение всплывает как необъявленное, с верной суммой.
        self.assertEqual(len(verdict.undeclared_discrepancies), 1)
        self.assertEqual(verdict.undeclared_discrepancies[0].amount_minor, 25000)

    def test_wrong_affected_ids_are_caught(self):
        episode = build_episode("EP-DUP")
        issue_of(episode, "ISS-DUP-1")["affected_ids"] = ["INV-31", "R-31"]

        verdict = verify_episode(episode)
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.unreconstructed_issue_ids, ("ISS-DUP-1",))

    def test_a_discrepancy_absent_from_the_reference_is_caught(self):
        """Эталон молчит о реальном расхождении: данные противоречивы."""
        episode = build_episode("EP-INTERACT")
        episode["truth"]["issues"] = [issue_of(episode, "ISS-FX-1")]

        verdict = verify_episode(episode)
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.unreconstructed_issue_ids, ())
        self.assertEqual(len(verdict.undeclared_discrepancies), 1)
        self.assertEqual(
            verdict.undeclared_discrepancies[0].kind, "payment_allocation"
        )

    def test_a_planted_discrepancy_in_a_clean_book_is_caught(self):
        episode = build_episode("EP-CLEAN")
        # Платёж относит 5000, а в журнале распределено 4000.
        find_row(episode, "R-47")["source_minor"] = 4000
        find_row(episode, "R-47")["debit_minor"] = 4000
        find_row(episode, "R-48")["credit_minor"] = 4000
        find_row(episode, "R-48")["source_minor"] = 4000

        verdict = verify_episode(episode)
        self.assertFalse(verdict.ok)
        self.assertEqual(len(verdict.undeclared_discrepancies), 1)
        self.assertEqual(
            verdict.undeclared_discrepancies[0].amount_minor, 1000
        )

    def test_unreachable_evidence_id_is_caught(self):
        episode = build_episode("EP-CUTOFF")
        issue_of(episode, "ISS-CUTOFF-1")["acceptable_evidence_sets"] = [
            ["D-INV-17", "J-7", "POLICY-PERIOD"]
        ]

        verdict = verify_episode(episode)
        self.assertFalse(verdict.ok)
        problems = {problem.code for problem in verdict.evidence_problems}
        self.assertIn(PROBLEM_UNREACHABLE_ID, problems)
        # journal_id не принимается ни одним инструментом как ключ.
        self.assertTrue(
            any("J-7" in problem.detail for problem in verdict.evidence_problems)
        )

    def test_evidence_set_that_covers_no_derivation_is_caught(self):
        """Регрессия: в наборе распределения не хватало записи курса."""
        episode = build_episode("EP-INTERACT")
        issue_of(episode, "ISS-ALLOC-1")["acceptable_evidence_sets"] = [
            ["D-PAY-21", "R-21", "R-22", "POLICY-ALLOC"]
        ]

        verdict = verify_episode(episode)
        self.assertFalse(verdict.ok)
        problems = {problem.code for problem in verdict.evidence_problems}
        self.assertIn(PROBLEM_SET_NOT_SUFFICIENT, problems)

    def test_missing_evidence_sets_are_caught(self):
        episode = build_episode("EP-CUTOFF")
        issue_of(episode, "ISS-CUTOFF-1")["acceptable_evidence_sets"] = []

        verdict = verify_episode(episode)
        self.assertFalse(verdict.ok)
        self.assertEqual(
            {problem.code for problem in verdict.evidence_problems},
            {PROBLEM_NO_EVIDENCE_SETS},
        )

    def test_empty_evidence_set_is_caught(self):
        episode = build_episode("EP-CUTOFF")
        issue_of(episode, "ISS-CUTOFF-1")["acceptable_evidence_sets"] = [[]]

        verdict = verify_episode(episode)
        self.assertFalse(verdict.ok)
        self.assertIn(
            PROBLEM_EMPTY_EVIDENCE_SET,
            {problem.code for problem in verdict.evidence_problems},
        )

    def test_oversized_evidence_set_is_caught(self):
        """Набор из 11 ID заставил бы oracle отправить невалидную заявку."""
        episode = build_episode("EP-CUTOFF")
        # Восемь добавленных ID не должны пересекаться с R-12, иначе после
        # дедупликации в наборе окажется 10 элементов и лимит не сработает.
        issue_of(episode, "ISS-CUTOFF-1")["acceptable_evidence_sets"] = [
            ["D-INV-17", "R-12", "POLICY-PERIOD"]
            + [f"R-9{index}" for index in range(8)]
        ]

        verdict = verify_episode(episode)
        self.assertFalse(verdict.ok)
        self.assertIn(
            PROBLEM_SET_TOO_LARGE,
            {problem.code for problem in verdict.evidence_problems},
        )

    def test_reachable_ids_exclude_structural_identifiers(self):
        snapshot = public_snapshot(build_episode("EP-INTERACT"))
        reachable = reachable_ids(snapshot)

        for public_id in ("R-23", "INV-21", "PAY-21", "FX-2", "POLICY-FX", "D-PAY-21"):
            self.assertIn(public_id, reachable)
        for structural_id in ("J-21", "ENT-5", "OBL-21", "LI-21-1"):
            self.assertNotIn(structural_id, reachable)


class ArithmeticAgreementTests(unittest.TestCase):
    """Две независимые реализации правила обязаны совпадать."""

    def test_banker_rounding_on_exact_halves(self):
        self.assertEqual(round_half_even(Fraction(1, 2)), 0)
        self.assertEqual(round_half_even(Fraction(3, 2)), 2)
        self.assertEqual(round_half_even(Fraction(5, 2)), 2)
        self.assertEqual(round_half_even(Fraction(7, 2)), 4)
        self.assertEqual(round_half_even(Fraction(-1, 2)), 0)

    def test_fraction_and_decimal_conversions_agree(self):
        rates = ("1.25", "1.20", "0.5", "1.005", "2.5", "0.333333")
        for rate in rates:
            for source_minor in (0, 1, 2, 5, 50, 999, 1000, 6000, 123457):
                for source_exponent, target_exponent in ((2, 2), (2, 0), (0, 2)):
                    with self.subTest(
                        rate=rate,
                        source_minor=source_minor,
                        exponents=(source_exponent, target_exponent),
                    ):
                        self.assertEqual(
                            fraction_convert(
                                source_minor, rate, source_exponent, target_exponent
                            ),
                            decimal_convert(
                                source_minor, rate, source_exponent, target_exponent
                            ),
                        )


class CrossCheckWithPolicyTests(unittest.TestCase):
    """Два маршрута к одному ответу: политика сверки и валидатор."""

    def test_reconstruction_agrees_with_the_reconciliation_policy(self):
        for episode_id in EPISODE_IDS:
            with self.subTest(episode=episode_id):
                episode = build_episode(episode_id)

                env = FakeEnv(episode)
                outcome = run_policy(env, ReconciliationAgent())
                policy_view = sorted(
                    (
                        item["type"],
                        frozenset(item["affected_ids"]),
                        item["claimed_amount_minor"],
                        item["currency"],
                    )
                    for item in outcome["submission"]["findings"]
                )

                validator_view = sorted(
                    item.signature() for item in reconstruct(public_snapshot(episode))
                )

                self.assertEqual(policy_view, validator_view)

    def test_policy_findings_still_score_perfectly(self):
        """Правка набора доказательств не сломала совпадение."""
        for episode_id in EPISODE_IDS:
            with self.subTest(episode=episode_id):
                episode = build_episode(episode_id)
                env = FakeEnv(episode)
                outcome = run_policy(env, ReconciliationAgent())
                report = score(
                    outcome["submission"], env.truth, outcome["inspection_steps"]
                )
                self.assertEqual(report.f1, 1.0)
                self.assertEqual(report.fp, 0)


if __name__ == "__main__":
    unittest.main()
