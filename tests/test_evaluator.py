"""Двадцать проверок сопоставления и награды плюс свойства порядка.

Нумерация соответствует docs/evaluator-contract.md, разделы 5–9. Предложенный
здесь набор — внутренняя регрессия команды, он не подменяет официальный набор
жюри.

Запускается и через ``python -m pytest tests/test_evaluator.py -v``, и через
``python -m unittest tests.test_evaluator``: в офлайн-контейнере pytest может
отсутствовать, а обязательная проверка не должна от него зависеть.
"""

from __future__ import annotations

import unittest
from decimal import Decimal
from fractions import Fraction

from evaluator import (
    Counts,
    build_oracle_submission,
    f1,
    f1_fraction,
    lexicographic_maximum_matching,
    match,
    normalize_truth,
    precision,
    recall,
    reward_from_f1,
    score,
    validate_submission,
)

EPISODE = "EP-T1"

TRUTH_ONE_ISSUE = {
    "episode_id": EPISODE,
    "issues": [
        {
            "issue_id": "ISS-1",
            "type": "period_cutoff",
            "affected_ids": ["INV-17", "R-12"],
            "expected_amount_minor": 25000,
            "currency": "USD",
            "acceptable_evidence_sets": [
                ["D-INV-17", "R-12", "POLICY-PERIOD"],
                ["INV-17", "R-12", "POLICY-PERIOD"],
            ],
        }
    ],
}

TRUTH_CLEAN = {"episode_id": EPISODE, "issues": []}

#: Публичные ID, которые агент может получить инструментами в этой фикстуре.
#: Нужны для проверки существования доказательств (примеры M03 и M04).
AVAILABLE_IDS = frozenset(
    {"INV-17", "R-12", "R-13", "D-INV-17", "POLICY-PERIOD"}
)


def finding(**overrides) -> dict:
    base = {
        "type": "period_cutoff",
        "affected_ids": ["INV-17", "R-12"],
        "claimed_amount_minor": 25000,
        "currency": "USD",
        "evidence_ids": ["D-INV-17", "R-12", "POLICY-PERIOD"],
        "explanation": "услуга в марте, расход проведён в апреле",
    }
    base.update(overrides)
    return base


def submission(*findings, episode_id: str = EPISODE) -> dict:
    return {"episode_id": episode_id, "findings": list(findings)}


class MatcherAndRewardTests(unittest.TestCase):
    """Проверки 01–20."""

    # --- 01–05 ---------------------------------------------------------------

    def test_01_full_correct_answer(self):
        report = score(submission(finding()), TRUTH_ONE_ISSUE, 6)
        self.assertTrue(report.valid)
        self.assertEqual((report.tp, report.fp, report.fn), (1, 0, 0))
        self.assertEqual(report.f1, 1.0)
        self.assertAlmostEqual(report.reward, 0.988, places=10)

    def test_02_silence_with_one_issue(self):
        report = score(submission(), TRUTH_ONE_ISSUE, 6)
        self.assertEqual((report.tp, report.fp, report.fn), (0, 0, 1))
        self.assertEqual(report.f1, 0.0)
        self.assertEqual(report.reward, -1.0)
        self.assertEqual(report.missed_issue_ids, ("ISS-1",))

    def test_03_silence_on_clean_book(self):
        report = score(submission(), TRUTH_CLEAN, 6)
        self.assertEqual((report.tp, report.fp, report.fn), (0, 0, 0))
        # Пустой эталон и пустая заявка: задание задаёт F1 = 1.
        self.assertEqual(report.f1, 1.0)
        self.assertAlmostEqual(report.reward, 0.988, places=10)

    def test_04_false_accusation_on_clean_book(self):
        report = score(submission(finding()), TRUTH_CLEAN, 6)
        self.assertEqual((report.tp, report.fp, report.fn), (0, 1, 0))
        self.assertEqual(report.f1, 0.0)
        self.assertEqual(report.reward, -1.0)

    def test_05_duplicate_of_correct_finding_is_a_false_positive(self):
        report = score(submission(finding(), finding()), TRUTH_ONE_ISSUE, 6)
        self.assertEqual((report.tp, report.fp, report.fn), (1, 1, 0))
        self.assertEqual(Fraction(report.f1).limit_denominator(100), Fraction(2, 3))
        self.assertAlmostEqual(report.reward, 0.32133333333, places=8)

    # --- 06–10 ---------------------------------------------------------------

    def test_06_wrong_type_with_right_amount_does_not_match(self):
        report = score(
            submission(finding(type="duplicate_invoice")), TRUTH_ONE_ISSUE, 6
        )
        self.assertEqual((report.tp, report.fp, report.fn), (0, 1, 1))

    def test_07_extra_affected_id_does_not_match(self):
        report = score(
            submission(finding(affected_ids=["INV-17", "R-12", "R-13"])),
            TRUTH_ONE_ISSUE,
            6,
        )
        self.assertEqual((report.tp, report.fp, report.fn), (0, 1, 1))

    def test_08_right_amount_in_another_currency_does_not_match(self):
        report = score(submission(finding(currency="EUR")), TRUTH_ONE_ISSUE, 6)
        self.assertEqual((report.tp, report.fp, report.fn), (0, 1, 1))

    def test_09_off_by_one_minor_unit_does_not_match(self):
        report = score(
            submission(finding(claimed_amount_minor=25001)), TRUTH_ONE_ISSUE, 6
        )
        self.assertEqual((report.tp, report.fp, report.fn), (0, 1, 1))

    def test_10_affected_ids_order_is_not_significant(self):
        report = score(
            submission(finding(affected_ids=["R-12", "INV-17"])), TRUTH_ONE_ISSUE, 6
        )
        self.assertEqual(report.tp, 1)

    # --- 11–15 ---------------------------------------------------------------

    def test_11_either_complete_evidence_set_matches(self):
        first = score(
            submission(finding(evidence_ids=["D-INV-17", "R-12", "POLICY-PERIOD"])),
            TRUTH_ONE_ISSUE,
            6,
        )
        second = score(
            submission(finding(evidence_ids=["INV-17", "R-12", "POLICY-PERIOD"])),
            TRUTH_ONE_ISSUE,
            6,
        )
        self.assertEqual(first.tp, 1)
        self.assertEqual(second.tp, 1)
        self.assertEqual(first.reward, second.reward)

    def test_12_mixture_of_two_incomplete_sets_does_not_match(self):
        # По одному элементу из каждого допустимого набора: ни один не полон.
        report = score(
            submission(finding(evidence_ids=["D-INV-17", "INV-17"])),
            TRUTH_ONE_ISSUE,
            6,
        )
        self.assertEqual((report.tp, report.fp, report.fn), (0, 1, 1))

    def test_13_fabricated_evidence_ids_do_not_confirm(self):
        report = score(
            submission(finding(evidence_ids=["D-NOPE", "R-NOPE", "POLICY-NOPE"])),
            TRUTH_ONE_ISSUE,
            6,
        )
        self.assertEqual((report.tp, report.fp, report.fn), (0, 1, 1))

    def test_14a_extra_existing_evidence_id_still_matches(self):
        """Пример M03: дополнительное существующее доказательство разрешено."""
        report = score(
            submission(
                finding(evidence_ids=["D-INV-17", "R-12", "POLICY-PERIOD", "R-13"])
            ),
            TRUTH_ONE_ISSUE,
            6,
            available_evidence_ids=AVAILABLE_IDS,
        )
        self.assertEqual(report.tp, 1)

    def test_14b_unavailable_evidence_id_breaks_the_match(self):
        """Пример M04: выдуманный ID отравляет вывод целиком.

        Полный допустимый набор в заявке присутствует, но определения проверок
        требуют FP: «Если указан несуществующий или недоступный evidence_id,
        вывод не сопоставляется и даёт FP».
        """
        report = score(
            submission(
                finding(evidence_ids=["D-INV-17", "R-12", "POLICY-PERIOD", "R-99"])
            ),
            TRUTH_ONE_ISSUE,
            6,
            available_evidence_ids=AVAILABLE_IDS,
        )
        self.assertEqual((report.tp, report.fp, report.fn), (0, 1, 1))

    def test_14c_without_the_available_set_existence_is_not_checked(self):
        """Граница применимости: ``None`` отключает проверку существования.

        Так устроены модульные тесты формулы, где эпизода нет. На пути
        реального эпизода множество передаётся всегда, иначе выдуманные
        доказательства начнут приносить TP.
        """
        report = score(
            submission(
                finding(evidence_ids=["D-INV-17", "R-12", "POLICY-PERIOD", "R-99"])
            ),
            TRUTH_ONE_ISSUE,
            6,
        )
        self.assertEqual(report.tp, 1)

    def test_15a_greedy_choice_would_lose_a_true_positive(self):
        """Синтетический случай: один вывод подходит к двум ошибкам.

        Жадный проход отдаёт первому выводу первую ошибку, и второй вывод
        остаётся без пары. Максимальное паросочетание находит две пары.
        """
        truth = {
            "episode_id": EPISODE,
            "issues": [
                {
                    "issue_id": "ISS-A",
                    "type": "fx_conversion",
                    "affected_ids": ["PAY-1", "R-1"],
                    "expected_amount_minor": 300,
                    "currency": "USD",
                    "acceptable_evidence_sets": [["E1"]],
                },
                {
                    "issue_id": "ISS-B",
                    "type": "fx_conversion",
                    "affected_ids": ["PAY-1", "R-1"],
                    "expected_amount_minor": 300,
                    "currency": "USD",
                    "acceptable_evidence_sets": [["E2"]],
                },
            ],
        }
        broad = finding(
            type="fx_conversion",
            affected_ids=["PAY-1", "R-1"],
            claimed_amount_minor=300,
            evidence_ids=["E1", "E2"],
        )
        narrow = finding(
            type="fx_conversion",
            affected_ids=["PAY-1", "R-1"],
            claimed_amount_minor=300,
            evidence_ids=["E1"],
        )
        report = score(submission(broad, narrow), truth, 6)
        self.assertEqual(report.tp, 2, "паросочетание обязано найти две пары")
        self.assertEqual(report.fp, 0)
        self.assertEqual(report.fn, 0)

    def test_15b_tie_break_is_deterministic_and_lexicographic(self):
        edges = [(0, "ISS-B"), (0, "ISS-A"), (1, "ISS-A"), (1, "ISS-B")]
        chosen = lexicographic_maximum_matching(edges)
        self.assertEqual(chosen, [(0, "ISS-A"), (1, "ISS-B")])
        # Порядок входа не влияет на результат.
        self.assertEqual(
            lexicographic_maximum_matching(list(reversed(edges))), chosen
        )

    # --- 16–20 ---------------------------------------------------------------

    def test_16_mass_labelling_of_thirty_findings_is_valid_and_scores_badly(self):
        findings = [finding()] + [
            finding(
                affected_ids=[f"INV-{index}"],
                claimed_amount_minor=index,
                evidence_ids=[f"D-{index}"],
            )
            for index in range(29)
        ]
        report = score(submission(*findings), TRUTH_ONE_ISSUE, 6)
        self.assertTrue(report.valid)
        self.assertEqual((report.tp, report.fp, report.fn), (1, 29, 0))
        self.assertEqual(Fraction(report.f1).limit_denominator(1000), Fraction(2, 31))
        self.assertAlmostEqual(report.reward, -0.88296774193, places=8)

    def test_17_structurally_invalid_submissions_end_with_minus_one(self):
        cases = {
            "thirty_one_findings": submission(*[finding()] * 31),
            "eleven_evidence_ids": submission(
                finding(evidence_ids=[f"E{index}" for index in range(11)])
            ),
            "explanation_too_long": submission(finding(explanation="x" * 1001)),
            "wrong_episode_id": submission(finding(), episode_id="EP-OTHER"),
            "boolean_amount": submission(finding(claimed_amount_minor=True)),
            "findings_not_a_list": {"episode_id": EPISODE, "findings": "none"},
            "unknown_type": submission(finding(type="made_up")),
            "empty_affected_ids": submission(finding(affected_ids=[])),
            # Структурно неверна только нестрока или пустая строка. Код
            # валюты в другом регистре структурно валиден и даёт FP: см.
            # test_currency_case_difference_is_a_false_positive.
            "currency_not_a_string": submission(finding(currency=840)),
            "currency_empty": submission(finding(currency="")),
            "payload_not_an_object": ["not", "an", "object"],
            "amount_as_string": submission(finding(claimed_amount_minor="25000")),
            "evidence_not_strings": submission(finding(evidence_ids=[1, 2])),
        }
        for name, payload in cases.items():
            with self.subTest(case=name):
                report = score(payload, TRUTH_ONE_ISSUE, 6)
                self.assertFalse(report.valid)
                self.assertEqual(report.reward, -1.0)
                self.assertIsNotNone(report.invalid_reason)
                # Метрики не считаются: ни одного TP у невалидной заявки.
                self.assertEqual(report.tp, 0)

    def test_17c_currency_case_difference_is_a_false_positive(self):
        """Пример M06: регистр или пробел в коде валюты — FP, а не −1.

        Это разница между потерей одного вывода и обнулением всего эпизода,
        поэтому проверяется отдельно от структурных случаев.
        """
        for variant in ("usd", "USD ", " USD"):
            with self.subTest(currency=variant):
                report = score(
                    submission(finding(currency=variant)),
                    TRUTH_ONE_ISSUE,
                    6,
                    available_evidence_ids=AVAILABLE_IDS,
                )
                self.assertTrue(report.valid, "структурно это валидная заявка")
                self.assertEqual((report.tp, report.fp, report.fn), (0, 1, 1))

    def test_17b_empty_evidence_list_is_valid_but_confirms_nothing(self):
        report = score(submission(finding(evidence_ids=[])), TRUTH_ONE_ISSUE, 6)
        self.assertTrue(report.valid)
        self.assertEqual((report.tp, report.fp, report.fn), (0, 1, 1))

    def test_18_one_extra_inspection_step_costs_exactly_two_thousandths(self):
        first = reward_from_f1(Fraction(1), 5)
        second = reward_from_f1(Fraction(1), 6)
        self.assertEqual(first - second, Decimal("0.002"))

        # То же на полном пути через score.
        high = score(submission(finding()), TRUTH_ONE_ISSUE, 5).reward
        low = score(submission(finding()), TRUTH_ONE_ISSUE, 6).reward
        self.assertAlmostEqual(high - low, 0.002, places=10)

    def test_19_bounds_zero_denominators_and_truncation(self):
        # Верхняя граница: идеальный ответ без осмотров.
        self.assertEqual(reward_from_f1(Fraction(1), 0), Decimal(1))
        # Нижняя граница: clip не пускает ниже -1.
        self.assertEqual(reward_from_f1(Fraction(0), 100), Decimal(-1))
        # Шаги съедают награду только до границы.
        self.assertEqual(reward_from_f1(Fraction(1), 2000), Decimal(-1))

        empty = Counts(0, 0, 0)
        self.assertEqual(precision(empty), 0.0)
        self.assertEqual(recall(empty), 0.0)
        self.assertEqual(f1(empty), 1.0)
        self.assertEqual(f1_fraction(Counts(0, 3, 0)), Fraction(0))
        self.assertEqual(f1_fraction(Counts(0, 0, 3)), Fraction(0))

        # Усечение: заявки не было, оценивается пустая.
        truncated_faulty = score(None, TRUTH_ONE_ISSUE, 100, truncated=True)
        self.assertTrue(truncated_faulty.valid)
        self.assertTrue(truncated_faulty.truncated)
        self.assertEqual(truncated_faulty.reward, -1.0)

    def test_19b_truncation_on_a_clean_book_pays_positively(self):
        """Известный эффект общей формулы, а не баг.

        На чистой книге пустая заявка даёт F1 = 1, поэтому усечённый эпизод
        получает положительный возврат. Это зафиксировано тестом, чтобы эффект
        не обнаружился впервые на защите, и отдельно описано в записке.
        """
        report = score(None, TRUTH_CLEAN, 100, truncated=True)
        self.assertTrue(report.truncated)
        self.assertAlmostEqual(report.reward, 0.8, places=10)
        self.assertGreater(report.reward, 0)

    def test_20_scoring_is_idempotent(self):
        payload = submission(finding())
        first = score(payload, TRUTH_ONE_ISSUE, 6)
        second = score(payload, TRUTH_ONE_ISSUE, 6)
        self.assertEqual(first.to_dict(), second.to_dict())
        # Повторная отправка не может улучшить оценку.
        self.assertEqual(first.reward, second.reward)


class OrderingPropertyTests(unittest.TestCase):
    """Задание требует неравенств, а не только отдельных значений."""

    def test_correct_answer_beats_silence_on_a_faulty_book(self):
        correct = score(submission(finding()), TRUTH_ONE_ISSUE, 6).reward
        silence = score(submission(), TRUTH_ONE_ISSUE, 6).reward
        self.assertGreater(correct, silence)

    def test_silence_beats_a_false_accusation_on_a_clean_book(self):
        silence = score(submission(), TRUTH_CLEAN, 6).reward
        accusation = score(submission(finding()), TRUTH_CLEAN, 6).reward
        self.assertGreater(silence, accusation)

    def test_duplicating_a_correct_finding_never_helps(self):
        single = score(submission(finding()), TRUTH_ONE_ISSUE, 6).reward
        doubled = score(submission(finding(), finding()), TRUTH_ONE_ISSUE, 6).reward
        self.assertGreater(single, doubled)

    def test_flagging_everything_is_worse_than_one_confirmed_finding(self):
        one = score(submission(finding()), TRUTH_ONE_ISSUE, 6).reward
        everything = score(
            submission(
                finding(),
                *[
                    finding(
                        affected_ids=[f"INV-{index}"],
                        claimed_amount_minor=index,
                        evidence_ids=[f"D-{index}"],
                    )
                    for index in range(29)
                ],
            ),
            TRUTH_ONE_ISSUE,
            6,
        ).reward
        self.assertGreater(one, everything)

    def test_step_thrift_only_slightly_separates_equal_answers(self):
        thrifty = score(submission(finding()), TRUTH_ONE_ISSUE, 3).reward
        wasteful = score(submission(finding()), TRUTH_ONE_ISSUE, 40).reward
        self.assertGreater(thrifty, wasteful)
        # Разница по шагам не должна перевешивать разницу по качеству.
        quality_gap = thrifty - score(submission(), TRUTH_ONE_ISSUE, 3).reward
        self.assertLess(thrifty - wasteful, quality_gap)


class OracleTests(unittest.TestCase):
    def test_oracle_reaches_the_maximum_reward_without_inspections(self):
        report = score(build_oracle_submission(TRUTH_ONE_ISSUE), TRUTH_ONE_ISSUE, 0)
        self.assertEqual(report.tp, 1)
        self.assertEqual(report.fp, 0)
        self.assertEqual(report.fn, 0)
        self.assertEqual(report.reward, 1.0)

    def test_oracle_on_a_clean_book_submits_nothing(self):
        payload = build_oracle_submission(TRUTH_CLEAN)
        self.assertEqual(payload["findings"], [])
        self.assertEqual(score(payload, TRUTH_CLEAN, 0).reward, 1.0)

    def test_every_acceptable_evidence_set_yields_the_same_reward(self):
        rewards = {
            index: score(
                build_oracle_submission(TRUTH_ONE_ISSUE, evidence_set_index=index),
                TRUTH_ONE_ISSUE,
                0,
            ).reward
            for index in range(2)
        }
        self.assertEqual(set(rewards.values()), {1.0})

    def test_oracle_refuses_an_unprovable_reference(self):
        broken = {
            "episode_id": EPISODE,
            "issues": [
                {
                    "issue_id": "ISS-X",
                    "type": "period_cutoff",
                    "affected_ids": ["INV-1"],
                    "expected_amount_minor": 1,
                    "currency": "USD",
                    "acceptable_evidence_sets": [],
                }
            ],
        }
        with self.assertRaises(ValueError):
            build_oracle_submission(broken)


class ValidationUnitTests(unittest.TestCase):
    def test_limits_are_checked_before_duplicates_are_removed(self):
        """Заявку из 31 вывода нельзя «вылечить» дедупликацией."""
        payload = submission(*[finding()] * 31)
        validation = validate_submission(payload, EPISODE)
        self.assertFalse(validation.ok)
        self.assertEqual(validation.reason, "too_many_findings")

    def test_valid_submission_is_normalized(self):
        validation = validate_submission(submission(finding()), EPISODE)
        self.assertTrue(validation.ok)
        self.assertEqual(len(validation.findings), 1)
        self.assertIsInstance(validation.findings[0]["affected_ids"], tuple)

    def test_explanation_text_does_not_affect_matching(self):
        persuasive = score(
            submission(finding(explanation="x" * 1000)), TRUTH_ONE_ISSUE, 6
        )
        terse = score(submission(finding(explanation="")), TRUTH_ONE_ISSUE, 6)
        self.assertEqual(persuasive.reward, terse.reward)
        self.assertEqual(persuasive.tp, terse.tp)

    def test_normalize_truth_sorts_evidence_sets_deterministically(self):
        shuffled = {
            "episode_id": EPISODE,
            "issues": [
                {
                    "issue_id": "ISS-1",
                    "type": "period_cutoff",
                    "affected_ids": ["R-12", "INV-17"],
                    "expected_amount_minor": 25000,
                    "currency": "USD",
                    "acceptable_evidence_sets": [
                        ["INV-17", "R-12", "POLICY-PERIOD"],
                        ["D-INV-17", "R-12", "POLICY-PERIOD"],
                    ],
                }
            ],
        }
        first = normalize_truth(shuffled)[0]["acceptable_evidence_sets"]
        second = normalize_truth(TRUTH_ONE_ISSUE)[0]["acceptable_evidence_sets"]
        self.assertEqual(first, second)

    def test_match_reports_unmatched_findings_and_missed_issues(self):
        issues = normalize_truth(TRUTH_ONE_ISSUE)
        validation = validate_submission(
            submission(finding(claimed_amount_minor=1)), EPISODE
        )
        result = match(validation.findings, issues)
        self.assertEqual(result.unmatched_finding_indexes, (0,))
        self.assertEqual(result.missed_issue_ids, ("ISS-1",))


if __name__ == "__main__":
    unittest.main()
