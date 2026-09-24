import unittest

from jev_agent.decision_model import (
    ChoiceBackendAdapter,
    DecisionRequest,
    OracleDecisionModel,
    ReplayDecisionModel,
)
from jev_agent.models import ChoiceOption, ChoiceResult, validate_choice_result


class DecisionModelTests(unittest.TestCase):
    def _options(self):
        return [ChoiceOption("a", "A"), ChoiceOption("b", "B")]

    def test_adapter_keeps_choice_backend_compatibility(self):
        result = ChoiceResult("b", {"a": 0.1, "b": 0.9}, 0.9, "replay")
        adapter = ChoiceBackendAdapter(ReplayDecisionModel([result]))
        self.assertEqual(adapter.choose(state="s", instructions="i", options=self._options()).choice, "b")

    def test_replay_rejects_result_for_wrong_option_space(self):
        result = ChoiceResult("c", {"c": 1.0}, 1.0, "replay")
        adapter = ChoiceBackendAdapter(ReplayDecisionModel([result]))
        with self.assertRaises(ValueError):
            adapter.choose(state="s", instructions="i", options=self._options())

    def test_oracle_is_explicit_upper_bound_backend(self):
        def select(request: DecisionRequest) -> str:
            return next(option.option_id for option in request.options if option.option_id == "a")

        result = OracleDecisionModel(select).decide(DecisionRequest("s", "i", tuple(self._options())))
        self.assertEqual(result.choice, "a")
        self.assertEqual(result.probabilities, {"a": 1.0, "b": 0.0})

    def test_shared_validator_rejects_bad_keys_confidence_and_distribution(self):
        options = self._options()
        with self.assertRaises(ValueError):
            validate_choice_result(ChoiceResult("a", {"a": 1.0}, 1.0, "fake"), options)
        with self.assertRaises(ValueError):
            validate_choice_result(ChoiceResult("a", {"a": 0.5, "b": 0.5}, 1.2, "fake"), options)
        with self.assertRaises(ValueError):
            validate_choice_result(ChoiceResult("a", {"a": 0.2, "b": 0.2}, 0.5, "fake"), options)


if __name__ == "__main__":
    unittest.main()
