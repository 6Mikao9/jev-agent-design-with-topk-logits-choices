import unittest

from jev_agent import ParameterPrior


class ParameterPriorTests(unittest.TestCase):
    def test_exact_state_beats_lexical_and_exports_option(self):
        p = ParameterPrior(max_age_seconds=100)
        p.record(tool="search", field="limit", value=10, phase="lookup", semantic_text="recent orders", revision=1, now=10)
        p.record(tool="search", field="limit", value=50, phase="other", semantic_text="recent orders", revision=1, now=10)
        got = p.candidates(tool="search", field="limit", phase="lookup", semantic_text="orders", revision=1, now=20)
        self.assertEqual(got[0].value, 10)
        self.assertEqual(got[0].source, "exact-state")
        self.assertEqual(got[0].to_option("limit-10").payload, 10)

    def test_stale_revision_and_age_are_filtered(self):
        p = ParameterPrior(max_age_seconds=5)
        p.record(tool="x", field="mode", value="old", phase="p", revision=3, now=0)
        self.assertEqual(p.candidates(tool="x", field="mode", phase="p", revision=2, now=1), ())
        self.assertEqual(p.candidates(tool="x", field="mode", phase="p", revision=3, now=10), ())


if __name__ == "__main__":
    unittest.main()
