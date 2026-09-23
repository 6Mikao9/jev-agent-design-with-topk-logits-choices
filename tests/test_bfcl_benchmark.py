from __future__ import annotations

import unittest

from benchmarks.run_bfcl_topk_coverage import (
    DATA_DIR,
    choose_sample,
    coverage_summary,
    pair_examples,
    read_jsonl,
)


class BFCLBenchmarkTests(unittest.TestCase):
    def test_packaged_bfcl_split_has_one_hundred_aligned_examples(self) -> None:
        questions = read_jsonl(DATA_DIR / "questions.jsonl")
        answers = read_jsonl(DATA_DIR / "answers.jsonl")
        pairs = pair_examples(questions, answers)

        self.assertEqual(len(questions), 100)
        self.assertEqual(len(answers), 100)
        self.assertEqual(len(pairs), 100)

    def test_sample_is_deterministic_for_a_seed(self) -> None:
        pairs = pair_examples(
            read_jsonl(DATA_DIR / "questions.jsonl"),
            read_jsonl(DATA_DIR / "answers.jsonl"),
        )

        first = choose_sample(pairs, limit=12, seed=2026)
        second = choose_sample(pairs, limit=12, seed=2026)

        self.assertEqual(
            [question["id"] for question, _ in first],
            [question["id"] for question, _ in second],
        )

    def test_coverage_reports_token_and_full_call_rates(self) -> None:
        summary = coverage_summary(
            [{"ranks": [1, 2]}, {"ranks": [None, 2]}], [1, 2]
        )

        self.assertEqual(summary["token_hit_at_1"], 0.25)
        self.assertEqual(summary["oracle_exact_call_at_1"], 0.0)
        self.assertEqual(summary["token_hit_at_2"], 0.75)
        self.assertEqual(summary["oracle_exact_call_at_2"], 0.5)


if __name__ == "__main__":
    unittest.main()
