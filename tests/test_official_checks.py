"""Официальные определения проверок как регрессионный набор.

Источник: «Genesis FinTech: определения проверок», опубликованы 20 ноября
2026 года одинаково для всех команд. Здесь воспроизведены блок 3 (двадцать
тестов matcher и награды) и открытые примеры M01-M12 — с их фикстурами, их
числами и их ожиданиями, а не с нашими.

Зачем отдельный файл: наши собственные тесты в ``test_evaluator.py`` написаны
под наши фикстуры и наши соглашения. Этот файл проверяет совпадение с чужим
текстом, поэтому ничего из него не переиспользует. Если жюри уточнит
определения, правится только он.

Фикстура блока 3: эталон содержит одну ошибку A, тип T из поддерживаемых,
одна каноническая запись R1, сумма 10000 минимальных единиц KZT, один
допустимый набор доказательств {D1, D2}, допуск τ=0, inspection_steps=10
по умолчанию.
"""

from __future__ import annotations

import unittest
from fractions import Fraction

from evaluator import score

EPISODE = "EP-OFFICIAL"

#: Тип и «другой уже поддерживаемый тип»: новая задача не вводится.
T = "period_cutoff"
OTHER_T = "duplicate_invoice"
ALL_TYPES = ("period_cutoff", "duplicate_invoice", "payment_allocation", "fx_conversion")

#: Абсолютная погрешность из определений: «не более 10^-9».
TOLERANCE = 1e-9

#: Публичные ID фикстуры. U среди них отсутствует, D3 — существующее
#: дополнительное доказательство.
AVAILABLE = frozenset({"R1", "R2", "R3", "R4", "R5", "D1", "D2", "D3"})

ISSUE_A = {
    "issue_id": "A",
    "type": T,
    "affected_ids": ["R1"],
    "expected_amount_minor": 10000,
    "currency": "KZT",
    "acceptable_evidence_sets": [["D1", "D2"]],
}

ISSUE_B = {
    "issue_id": "B",
    "type": T,
    "affected_ids": ["R4"],
    "expected_amount_minor": 20000,
    "currency": "KZT",
    "acceptable_evidence_sets": [["D1", "D3"]],
}


def truth(*issues) -> dict:
    return {"episode_id": EPISODE, "issues": list(issues)}


def finding(**overrides) -> dict:
    base = {
        "type": T,
        "affected_ids": ["R1"],
        "claimed_amount_minor": 10000,
        "currency": "KZT",
        "evidence_ids": ["D1", "D2"],
        "explanation": "короткое обоснование",
    }
    base.update(overrides)
    return base


def submission(*findings, episode_id: str = EPISODE) -> dict:
    return {"episode_id": episode_id, "findings": list(findings)}


def evaluate(payload, reference, steps: int = 10, tolerance_minor: int = 0):
    return score(
        payload,
        reference,
        steps,
        tolerance_minor=tolerance_minor,
        available_evidence_ids=AVAILABLE,
    )


class Block3MatcherAndRewardTests(unittest.TestCase):
    """Блок 3: двадцать тестов matcher и награды, 25 баллов."""

    def assert_counts(self, report, tp, fp, fn):
        self.assertEqual((report.tp, report.fp, report.fn), (tp, fp, fn))

    def assert_reward(self, report, expected):
        self.assertAlmostEqual(report.reward, float(expected), delta=TOLERANCE)

    def test_01_one_correct_finding(self):
        report = evaluate(submission(finding()), truth(ISSUE_A))
        self.assert_counts(report, 1, 0, 0)
        self.assertEqual(report.precision, 1.0)
        self.assertEqual(report.recall, 1.0)
        self.assertEqual(report.f1, 1.0)
        self.assert_reward(report, Fraction(98, 100))

    def test_02_empty_findings_against_one_issue(self):
        report = evaluate(submission(), truth(ISSUE_A))
        self.assert_counts(report, 0, 0, 1)
        self.assertEqual(report.f1, 0.0)
        self.assert_reward(report, -1)

    def test_03_empty_reference_and_empty_findings(self):
        report = evaluate(submission(), truth())
        self.assert_counts(report, 0, 0, 0)
        self.assertEqual(report.precision, 0.0)
        self.assertEqual(report.recall, 0.0)
        self.assertEqual(report.f1, 1.0, "F1=1 по специальному правилу")
        self.assert_reward(report, Fraction(98, 100))

    def test_04_empty_reference_with_one_false_finding(self):
        report = evaluate(submission(finding()), truth())
        self.assert_counts(report, 0, 1, 0)
        self.assertEqual(report.f1, 0.0)
        self.assert_reward(report, -1)

    def test_05_two_identical_findings(self):
        report = evaluate(submission(finding(), finding()), truth(ISSUE_A))
        self.assert_counts(report, 1, 1, 0)
        self.assertEqual(report.precision, 0.5)
        self.assertEqual(report.recall, 1.0)
        self.assert_reward(report, Fraction(47, 150))

        single = evaluate(submission(finding()), truth(ISSUE_A))
        self.assertLessEqual(report.reward, single.reward, "не выше теста 1")

    def test_06_wrong_type(self):
        report = evaluate(submission(finding(type=OTHER_T)), truth(ISSUE_A))
        self.assert_counts(report, 0, 1, 1)
        self.assert_reward(report, -1)

    def test_07_existing_but_unaffected_record_in_affected_ids(self):
        report = evaluate(submission(finding(affected_ids=["R1", "R3"])), truth(ISSUE_A))
        self.assert_counts(report, 0, 1, 1)
        self.assert_reward(report, -1)

    def test_08_amount_off_by_one_at_zero_tolerance(self):
        report = evaluate(submission(finding(claimed_amount_minor=10001)), truth(ISSUE_A))
        self.assert_counts(report, 0, 1, 1)
        self.assert_reward(report, -1)

    def test_09_another_currency(self):
        report = evaluate(submission(finding(currency="USD")), truth(ISSUE_A))
        self.assert_counts(report, 0, 1, 1)
        self.assert_reward(report, -1)

    def test_10_only_part_of_the_evidence_set(self):
        report = evaluate(submission(finding(evidence_ids=["D1"])), truth(ISSUE_A))
        self.assert_counts(report, 0, 1, 1)
        self.assert_reward(report, -1)

    def test_11_missing_evidence_id_replaced_by_an_absent_one(self):
        report = evaluate(submission(finding(evidence_ids=["D1", "U"])), truth(ISSUE_A))
        self.assert_counts(report, 0, 1, 1)
        self.assert_reward(report, -1)

    def test_12_mass_labelling_of_five_records_with_four_types(self):
        """Двадцать структурно корректных выводов, ровно один совпадает."""
        findings = [
            finding(type=issue_type, affected_ids=[record])
            for record in ("R1", "R2", "R3", "R4", "R5")
            for issue_type in ALL_TYPES
        ]
        self.assertEqual(len(findings), 20)

        report = evaluate(submission(*findings), truth(ISSUE_A))
        self.assert_counts(report, 1, 19, 0)
        self.assertEqual(report.precision, 1 / 20)
        self.assertEqual(report.recall, 1.0)
        self.assertEqual(Fraction(report.f1).limit_denominator(100), Fraction(2, 21))
        self.assert_reward(report, Fraction(-871, 1050))

    def test_13_two_issues_with_a_correct_finding_for_one(self):
        report = evaluate(submission(finding()), truth(ISSUE_A, ISSUE_B))
        self.assert_counts(report, 1, 0, 1)
        self.assertEqual(report.precision, 1.0)
        self.assertEqual(report.recall, 0.5)
        self.assert_reward(report, Fraction(47, 150))

    def test_14_two_issues_with_one_correct_and_one_false_finding(self):
        report = evaluate(
            submission(finding(), finding(affected_ids=["R5"])),
            truth(ISSUE_A, ISSUE_B),
        )
        self.assert_counts(report, 1, 1, 1)
        self.assertEqual(report.precision, 0.5)
        self.assertEqual(report.recall, 0.5)
        self.assertEqual(report.f1, 0.5)
        self.assert_reward(report, Fraction(-2, 100))

    def test_15_zero_inspection_steps(self):
        report = evaluate(submission(finding()), truth(ISSUE_A), steps=0)
        self.assertEqual(report.f1, 1.0)
        self.assert_reward(report, 1)

    def test_16_fifty_inspection_steps(self):
        report = evaluate(submission(finding()), truth(ISSUE_A), steps=50)
        self.assertEqual(report.f1, 1.0)
        self.assert_reward(report, Fraction(90, 100))

        baseline = evaluate(submission(finding()), truth(ISSUE_A))
        self.assertAlmostEqual(baseline.reward - report.reward, 0.08, delta=TOLERANCE)

    def test_17_hundred_inspection_steps(self):
        report = evaluate(submission(finding()), truth(ISSUE_A), steps=100)
        self.assertEqual(report.f1, 1.0)
        self.assert_reward(report, Fraction(80, 100))

    def test_18_thirty_one_findings(self):
        report = evaluate(submission(*[finding()] * 31), truth(ISSUE_A))
        self.assertFalse(report.valid)
        self.assert_reward(report, -1)
        self.assertIsNotNone(report.invalid_reason)

    def test_19_eleven_distinct_evidence_ids(self):
        report = evaluate(
            submission(finding(evidence_ids=[f"D{index}" for index in range(11)])),
            truth(ISSUE_A),
        )
        self.assertFalse(report.valid)
        self.assert_reward(report, -1)

    def test_20_explanation_of_1001_ascii_characters(self):
        report = evaluate(submission(finding(explanation="x" * 1001)), truth(ISSUE_A))
        self.assertFalse(report.valid)
        self.assert_reward(report, -1)


class OpenExamplesTests(unittest.TestCase):
    """Открытые примеры M01-M12.

    Фикстура примеров отличается от блока 3: у ошибки A два затронутых ID.
    """

    ISSUE = {
        "issue_id": "A",
        "type": T,
        "affected_ids": ["R1", "R2"],
        "expected_amount_minor": 10000,
        "currency": "KZT",
        "acceptable_evidence_sets": [["D1", "D2"]],
    }

    def finding(self, **overrides) -> dict:
        base = {
            "type": T,
            "affected_ids": ["R1", "R2"],
            "claimed_amount_minor": 10000,
            "currency": "KZT",
            "evidence_ids": ["D1", "D2"],
            "explanation": "ok",
        }
        base.update(overrides)
        return base

    def evaluate(self, *findings, reference=None, tolerance_minor=0):
        return evaluate(
            submission(*findings),
            reference if reference is not None else truth(self.ISSUE),
            tolerance_minor=tolerance_minor,
        )

    def test_m01_repeated_id_inside_affected_ids(self):
        report = self.evaluate(self.finding(affected_ids=["R2", "R1", "R1"]))
        self.assertEqual(report.tp, 1, "множество равно {R1, R2}")
        self.assertEqual(report.fp, 0)

    def test_m02_existing_but_unaffected_record(self):
        report = self.evaluate(self.finding(affected_ids=["R1", "R2", "R3"]))
        self.assertEqual((report.fp, report.fn), (1, 1))

    def test_m03_extra_available_evidence_is_allowed(self):
        report = self.evaluate(self.finding(evidence_ids=["D2", "D1", "D3"]))
        self.assertEqual(report.tp, 1)

    def test_m04_absent_evidence_id_breaks_the_match(self):
        """Минимальный набор присутствует, но U не существует."""
        report = self.evaluate(self.finding(evidence_ids=["D1", "D2", "U"]))
        self.assertEqual((report.tp, report.fp, report.fn), (0, 1, 1))

    def test_m05_eleven_elements_with_ten_duplicates(self):
        """Структурная ошибка считается до удаления повторов."""
        report = self.evaluate(self.finding(evidence_ids=["D1"] * 10 + ["D2"]))
        self.assertFalse(report.valid)
        self.assertAlmostEqual(report.reward, -1.0, delta=TOLERANCE)

    def test_m06_currency_differing_by_case_or_space(self):
        for variant in ("kzt", " KZT", "KZT "):
            with self.subTest(currency=variant):
                report = self.evaluate(self.finding(currency=variant))
                self.assertTrue(report.valid, "это не структурная ошибка")
                self.assertEqual((report.fp, report.fn), (1, 1))

    def test_m07_amount_off_by_one_at_zero_tolerance(self):
        report = self.evaluate(self.finding(claimed_amount_minor=10001))
        self.assertEqual((report.fp, report.fn), (1, 1))

    def test_m08_published_tolerance_of_one_includes_the_boundary(self):
        inside = self.evaluate(
            self.finding(claimed_amount_minor=10001), tolerance_minor=1
        )
        self.assertEqual(inside.tp, 1, "граница включительно")

        outside = self.evaluate(
            self.finding(claimed_amount_minor=10002), tolerance_minor=1
        )
        self.assertEqual((outside.fp, outside.fn), (1, 1))

    def test_m09_amount_as_string_or_boolean(self):
        for value in ("10000", True):
            with self.subTest(amount=value):
                report = self.evaluate(self.finding(claimed_amount_minor=value))
                self.assertFalse(report.valid)
                self.assertAlmostEqual(report.reward, -1.0, delta=TOLERANCE)

    def test_m10_greedy_choice_is_not_acceptable(self):
        """F0 подходит A и B, F1 подходит только A: ожидается TP=2."""
        issue_a = dict(self.ISSUE, issue_id="A", acceptable_evidence_sets=[["D1"]])
        issue_b = dict(self.ISSUE, issue_id="B", acceptable_evidence_sets=[["D2"]])
        report = self.evaluate(
            self.finding(evidence_ids=["D1", "D2"]),
            self.finding(evidence_ids=["D1"]),
            reference=truth(issue_a, issue_b),
        )
        self.assertEqual((report.tp, report.fp, report.fn), (2, 0, 0))

    def test_m11_tie_break_is_deterministic_and_order_independent(self):
        issue_a = dict(self.ISSUE, issue_id="A")
        issue_b = dict(self.ISSUE, issue_id="B")
        reference = truth(issue_a, issue_b)

        report = self.evaluate(self.finding(), self.finding(), reference=reference)
        self.assertEqual(report.tp, 2)
        # При A < B выбирается A->F0, B->F1.
        self.assertEqual(report.matched_pairs, ((0, "A"), (1, "B")))

        # Перестановка выводов не меняет TP и награду.
        swapped = self.evaluate(
            self.finding(explanation="второй"),
            self.finding(explanation="первый"),
            reference=reference,
        )
        self.assertEqual(swapped.tp, report.tp)
        self.assertAlmostEqual(swapped.reward, report.reward, delta=TOLERANCE)

    def test_m12_two_identical_correct_findings(self):
        report = self.evaluate(self.finding(), self.finding())
        self.assertEqual((report.tp, report.fp, report.fn), (1, 1, 0))
        self.assertAlmostEqual(report.reward, float(Fraction(47, 150)), delta=TOLERANCE)


class JudgeResponseShapeTests(unittest.TestCase):
    """Форма ответа ``score_episode`` из протокола подключения."""

    REQUIRED_KEYS = {"tp", "fp", "fn", "precision", "recall", "f1", "return"}

    def test_valid_submission_returns_exactly_the_seven_fields(self):
        report = evaluate(submission(finding()), truth(ISSUE_A))
        payload = report.to_judge_dict()
        self.assertEqual(set(payload), self.REQUIRED_KEYS)
        self.assertAlmostEqual(payload["return"], 0.98, delta=TOLERANCE)
        self.assertEqual(payload["tp"], 1)

    def test_invalid_submission_returns_minus_one_and_nulls(self):
        report = evaluate(submission(*[finding()] * 31), truth(ISSUE_A))
        payload = report.to_judge_dict()
        self.assertEqual(set(payload), self.REQUIRED_KEYS)
        self.assertEqual(payload["return"], -1.0)
        for key in self.REQUIRED_KEYS - {"return"}:
            with self.subTest(field=key):
                self.assertIsNone(payload[key])


if __name__ == "__main__":
    unittest.main()
