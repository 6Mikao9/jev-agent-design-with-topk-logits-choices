import unittest

from jev_agent.agent import Agent, ToolDefinition
from jev_agent.memory import DependencyIndex, MemoryBank, MemoryRecord
from jev_agent.models import Candidate, ChoiceOption, ChoiceResult, TaskState
from jev_agent.topk import LogitsState, TokenProposal, TopKBuilder, TransformersLogitsBackend


class FixedChooser:
    def __init__(self, picks):
        self.picks = iter(picks)

    def choose(self, *, state, instructions, options):
        desired = next(self.picks)
        assert desired in {option.option_id for option in options}, (desired, [o.option_id for o in options])
        return ChoiceResult(desired, {desired: 1.0}, 1.0, "test")


class OneCharacterHelper:
    def start(self, *, context, prefix):
        return LogitsState(prefix)

    def next_top_k(self, *, state, k):
        next_char = "a" if not state.value else "b"
        return [TokenProposal(ord(next_char), next_char, 1.0)]

    def append_token(self, *, state, token):
        return LogitsState(state.value + token.text, state.token_ids + (token.token_id,))


class AgentTests(unittest.TestCase):
    def test_rejects_stale_proposal_and_executes_topk_result(self):
        state = TaskState("t1", "write query", revision=2)
        schema = {
            "type": "object",
            "properties": {"query": {"type": "string", "minLength": 2}},
            "required": ["query"],
            "additionalProperties": False,
        }
        calls = []
        tool = ToolDefinition("search", "Search", "v2", schema, lambda args: calls.append(args) or "ok")
        stale = Candidate("old", "search", {"query": "stale"}, "fixture", 1, "v2")
        chooser = FixedChooser(["FALLBACK_TOPK", "token_97", "token_98", "FINISH"])
        helper = OneCharacterHelper()
        topk = TopKBuilder(helper=helper, chooser=chooser, max_tokens=5)
        result = Agent(chooser, topk=topk).run(
            state=state,
            tool=tool,
            drafts=[stale],
            fallback_field=("query",),
            fallback_complete=lambda value: len(value) >= 2,
        )
        self.assertEqual(result.status, "executed")
        self.assertEqual(calls, [{"query": "ab"}])

    def test_missing_fact_returns_clarification_without_execution(self):
        state = TaskState("t2", "find the service")
        tool = ToolDefinition("search", "Search", "v1", {"type": "object"}, lambda _: self.fail("must not execute"))
        chooser = FixedChooser(["CLARIFY"])
        result = Agent(chooser).run(state=state, tool=tool, drafts=[])
        self.assertEqual(result.status, "clarification_required")

    def test_memory_retrieval_prioritizes_direct_decision_impact(self):
        bank = MemoryBank()
        bank.add(MemoryRecord("old", "unrelated log", "event", storage_tier="L0"))
        bank.add(MemoryRecord("constraint", "use at most two GPUs", "constraint", impact_tags=frozenset({"gpu"})))
        retrieved = bank.retrieve(dependency_ids=[], current_versions={}, impact_tags=["gpu"])
        self.assertEqual(retrieved[0].record_id, "constraint")

    def test_dependency_index_invalidates_transitive_dependents(self):
        index = DependencyIndex()
        index.register("namespace-choice", depends_on=["region"])
        index.register("instance-choice", depends_on=["namespace-choice"])
        self.assertEqual(index.affected_by(["region"]), {"region", "namespace-choice", "instance-choice"})

    def test_task_revision_bumps_transitive_versions_but_preserves_unrelated_candidate(self):
        state = TaskState(
            "t-deps",
            "choose an instance",
            dependency_versions={"region": 0, "namespace": 0, "instance": 0, "other": 0},
        )
        state.register_dependency("namespace", depends_on=["region"])
        state.register_dependency("instance", depends_on=["namespace"])
        candidate = Candidate(
            "instance-0",
            "launch",
            {"instance": "i-1"},
            "fixture",
            task_revision=state.revision,
            schema_version="v1",
            dependency_versions={"instance": 0},
        )

        state.revise("other")
        self.assertTrue(candidate.is_current(state, "v1"))
        state.revise("region")

        self.assertEqual(state.dependency_versions["namespace"], 1)
        self.assertEqual(state.dependency_versions["instance"], 1)
        self.assertFalse(candidate.is_current(state, "v1"))

    def test_agent_retrieves_only_current_memories_and_marks_old_versions_stale(self):
        state = TaskState(
            "t-memory",
            "query the current service",
            dependency_versions={"service": 0, "query": 0},
        )
        state.register_dependency("query", depends_on=["service"])
        bank = MemoryBank()
        old = MemoryRecord(
            "old-query", "use the retired endpoint", "observation", {"query": 0}
        )
        bank.add(old)
        state.revise("service", "service endpoint changed")
        bank.add(
            MemoryRecord(
                "current-query", "use the new endpoint", "observation", {"query": 1}
            )
        )

        class CapturingChooser:
            state_text = ""

            def choose(self, *, state, instructions, options):
                self.state_text = state
                return ChoiceResult("CLARIFY", {"CLARIFY": 1.0}, 1.0, "test")

        chooser = CapturingChooser()
        result = Agent(chooser, memory=bank).run(
            state=state,
            tool=ToolDefinition("search", "Search", "v1", {"type": "object"}, lambda _: None),
            drafts=[],
            decision_dependencies=["query"],
        )

        self.assertEqual(old.validity, "stale")
        self.assertEqual(result.memory_ids, ("current-query",))
        self.assertIn("use the new endpoint", chooser.state_text)
        self.assertNotIn("retired endpoint", chooser.state_text)

    def test_fallback_only_restarts_for_a_changed_declared_dependency(self):
        def run_with_change(changed_id):
            state = TaskState(
                f"t-{changed_id}",
                "write query",
                dependency_versions={"query": 0, "service": 0, "other": 0},
            )
            state.register_dependency("query", depends_on=["service"])

            class MutatingChooser:
                def __init__(self):
                    self.picks = iter(["FALLBACK_TOPK", "token_97", "token_98", "FINISH"])
                    self.calls = 0

                def choose(self, *, state, instructions, options):
                    self.calls += 1
                    if self.calls == 2:
                        state_object.revise(changed_id)
                    desired = next(self.picks)
                    assert desired in {option.option_id for option in options}
                    return ChoiceResult(desired, {desired: 1.0}, 1.0, "test")

            state_object = state
            chooser = MutatingChooser()
            calls = []
            tool = ToolDefinition(
                "search",
                "Search",
                "v1",
                {
                    "type": "object",
                    "properties": {"query": {"type": "string", "minLength": 2}},
                    "required": ["query"],
                },
                lambda args: calls.append(args) or "ok",
            )
            result = Agent(
                chooser,
                topk=TopKBuilder(helper=OneCharacterHelper(), chooser=chooser, max_tokens=5),
            ).run(
                state=state,
                tool=tool,
                drafts=[],
                fallback_field=("query",),
                fallback_complete=lambda value: len(value) >= 2,
                fallback_dependencies=("query",),
            )
            return result, calls

        unrelated_result, unrelated_calls = run_with_change("other")
        affected_result, affected_calls = run_with_change("service")

        self.assertEqual(unrelated_result.status, "executed")
        self.assertEqual(unrelated_calls, [{"query": "ab"}])
        self.assertEqual(affected_result.status, "stale_before_execution")
        self.assertEqual(affected_calls, [])

    def test_fallback_requires_completion_predicate(self):
        state = TaskState("t3", "write query")
        tool = ToolDefinition("search", "Search", "v1", {"type": "object"}, lambda _: self.fail("must not execute"))
        chooser = FixedChooser(["STOP_UNRESOLVED"])
        result = Agent(chooser, topk=TopKBuilder(helper=OneCharacterHelper(), chooser=chooser)).run(
            state=state,
            tool=tool,
            drafts=[],
            fallback_field=("query",),
        )
        self.assertEqual(result.status, "unresolved")

    def test_backtrack_restores_a_whole_token_boundary(self):
        class MultiTokenHelper:
            def start(self, *, context, prefix):
                return LogitsState(prefix)

            def next_top_k(self, *, state, k):
                token = TokenProposal(10, "ab", 1.0) if not state.value else TokenProposal(11, "x", 1.0)
                return [token]

            def append_token(self, *, state, token):
                return LogitsState(state.value + token.text, state.token_ids + (token.token_id,))

        chooser = FixedChooser(["token_10", "BACKTRACK", "token_10", "FINISH"])
        helper = MultiTokenHelper()
        result = TopKBuilder(helper=helper, chooser=chooser, max_tokens=8).construct(
            context="query",
            complete=lambda value: value == "ab",
        )
        self.assertEqual(result.status, "complete")
        self.assertEqual(result.value, "ab")
        self.assertEqual(result.helper_calls, 4)

    def test_dialogue_end_requires_completion_predicate(self):
        chooser = FixedChooser(["token_97", "END_DIALOGUE"])
        result = TopKBuilder(
            helper=OneCharacterHelper(),
            chooser=chooser,
            max_tokens=3,
            allow_end=lambda value: value == "complete",
        ).construct(context="", complete=lambda _value: False)
        self.assertEqual(result.status, "premature_end")

    def test_dialogue_end_returns_complete_after_predicate(self):
        chooser = FixedChooser(["token_97", "END_DIALOGUE"])
        result = TopKBuilder(
            helper=OneCharacterHelper(),
            chooser=chooser,
            max_tokens=3,
            allow_end=lambda value: value == "a",
        ).construct(context="", complete=lambda _value: False)
        self.assertEqual(result.status, "dialogue_complete")
        self.assertEqual(result.reason, "jev_end")

    def test_transformer_state_keeps_exact_token_ids_and_decodes_as_a_sequence(self):
        class TokenRow(list):
            def tolist(self):
                return list(self)

        class Encoded:
            input_ids = [TokenRow([101, 202])]

            def to(self, _device):
                return self

        class Tokenizer:
            eos_token_id = 0

            def __call__(self, _text, return_tensors):
                self.return_tensors = return_tensors
                return Encoded()

            def decode(self, token_ids, **_kwargs):
                if token_ids == [7]:
                    return ""
                if token_ids == [7, 8]:
                    return "é"
                return ""

            def convert_ids_to_tokens(self, token_id):
                return f"token-{token_id}"

        backend = TransformersLogitsBackend.__new__(TransformersLogitsBackend)
        backend.tokenizer = Tokenizer()
        backend.device = "cpu"
        first = backend.start(context="context", prefix="seed")
        partial = backend.append_token(
            state=first,
            token=TokenProposal(7, "partial-byte", 1.0),
        )
        complete = backend.append_token(
            state=partial,
            token=TokenProposal(8, "continuation-byte", 1.0),
        )
        self.assertEqual(first.metadata["prompt_ids"], (101, 202))
        self.assertEqual(complete.metadata["generated_ids"], (7, 8))
        self.assertEqual(complete.token_ids, (7, 8))
        self.assertEqual(partial.value, "seed")
        self.assertEqual(complete.value, "seedé")


if __name__ == "__main__":
    unittest.main()
