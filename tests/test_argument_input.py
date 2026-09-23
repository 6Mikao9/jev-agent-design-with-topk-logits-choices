import threading
import unittest

from jev_agent.agent import Agent, ToolDefinition
from jev_agent.arguments import ArgumentField, ArgumentInput, ValueProposal
from jev_agent.models import ChoiceResult, TaskState
from jev_agent.topk import LogitsState, TokenProposal
from jev_agent.validation import SchemaError


class Picks:
    def __init__(self, *picks):
        self.picks = iter(picks)
        self.menus = []

    def choose(self, *, state, instructions, options):
        self.menus.append([o.option_id for o in options])
        pick = next(self.picks)
        assert pick in self.menus[-1], (pick, self.menus[-1])
        return ChoiceResult(pick, {pick: 1}, 1, "scripted-test")


class Letters:
    def start(self, *, context, prefix):
        return LogitsState(prefix)

    def next_top_k(self, *, state, k):
        return [TokenProposal(1, "x", 1), TokenProposal(2, "y", 0)][:k]

    def append_token(self, *, state, token):
        return LogitsState(state.value + token.text, state.token_ids + (token.token_id,))


def make_tool(properties, validator=None):
    calls = []
    tool = ToolDefinition("demo", "Example", "v1", {
        "type": "object", "properties": properties, "required": list(properties),
        "additionalProperties": False,
    }, lambda args: calls.append(args), argument_validator=validator)
    return tool, calls


class ArgumentInputTests(unittest.TestCase):
    def test_direct_refine_on_first_proposal_is_allowed(self):
        backend = Picks("REFINE", "token_1", "END_FIELD")
        attempts = []
        def propose(ctx):
            attempts.append(ctx.attempt)
            return [ValueProposal("unwanted")]
        tool, _ = make_tool({"text": {"type": "string", "minLength": 1}})
        result = ArgumentInput(chooser_factory=lambda _: backend, proposer=propose,
            helper_factory=lambda _: Letters()).build(state=TaskState("t", "x"), tool=tool,
                                                       fields=[ArgumentField("text")])
        self.assertEqual(result.status, "ready")
        self.assertEqual(result.candidate.arguments["text"], "x")
        self.assertEqual(attempts, [1])

    def test_refresh_candidate_then_accept(self):
        backend = Picks("REPROPOSE", "VALUE_0")
        tool, _ = make_tool({"text": {"type": "string"}})
        result = ArgumentInput(chooser_factory=lambda _: backend,
            proposer=lambda ctx: [ValueProposal("old" if ctx.attempt == 1 else "fresh")]).build(
            state=TaskState("t", "refresh"), tool=tool, fields=[ArgumentField("text")])
        self.assertEqual(result.candidate.arguments["text"], "fresh")
        self.assertEqual(result.fields["text"].proposal_rounds, 2)

    def test_refresh_during_construction_discards_partial_and_is_bounded(self):
        tool, _ = make_tool({"text": {"type": "string", "minLength": 1}})
        backend = Picks("REFINE", "token_1", "REPROPOSE", "VALUE_0")
        result = ArgumentInput(chooser_factory=lambda _: backend,
            proposer=lambda ctx: [ValueProposal(f"round-{ctx.attempt}")],
            helper_factory=lambda _: Letters()).build(state=TaskState("t", "refresh"), tool=tool,
                                                       fields=[ArgumentField("text")])
        self.assertEqual(result.candidate.arguments["text"], "round-2")
        self.assertEqual(result.fields["text"].proposal_rounds, 2)
        self.assertEqual(result.choice_calls, 4)
        exhausted = ArgumentInput(chooser_factory=lambda _: Picks("REFINE", "REPROPOSE"),
            proposer=lambda _: [ValueProposal("x")], helper_factory=lambda _: Letters(), proposal_rounds=1).build(
                state=TaskState("t", "refresh"), tool=tool, fields=[ArgumentField("text")])
        self.assertEqual(exhausted.status, "budget_exhausted")

    def test_reject_twice_then_construct_and_explicit_commit(self):
        backend = Picks("REPROPOSE", "REPROPOSE", "token_1", "END_FIELD")
        tool, calls = make_tool({"text": {"type": "string", "minLength": 1}})
        state = TaskState("t", "Write x")
        result = ArgumentInput(chooser_factory=lambda _: backend,
            proposer=lambda ctx: [ValueProposal("bad")], helper_factory=lambda _: Letters(),
            choice_cap=8).build(state=state, tool=tool, fields=[ArgumentField("text")])
        self.assertEqual(result.status, "ready")
        self.assertEqual(result.candidate.arguments, {"text": "x"})
        self.assertEqual(result.fields["text"].proposal_rounds, 2)
        self.assertEqual(calls, [])
        self.assertLessEqual(max(map(len, backend.menus)), 8)
        committed = Agent(Picks(result.candidate.candidate_id)).run(state=state, tool=tool, drafts=[result.candidate])
        self.assertEqual(committed.status, "executed")
        self.assertEqual(calls, [{"text": "x"}])

    def test_invalid_proposals_fallback_without_invalid_menu(self):
        backend = Picks("token_1", "END_FIELD")
        tool, _ = make_tool({"text": {"type": "string", "minLength": 1}})
        result = ArgumentInput(chooser_factory=lambda _: backend,
            proposer=lambda _: [ValueProposal(42)], helper_factory=lambda _: Letters()).build(
                state=TaskState("t", "x"), tool=tool, fields=[ArgumentField("text")])
        self.assertEqual(result.status, "ready")
        self.assertEqual(result.choice_calls, 2)
        self.assertEqual(sum(e["event"] == "invalid_proposal" for e in result.fields["text"].events), 2)

    def test_independent_fields_parallel_and_dependent_after_both(self):
        barrier = threading.Barrier(2)
        def propose(ctx):
            if ctx.name in ("a", "b"):
                barrier.wait(timeout=3)
                return [ValueProposal(ctx.name)]
            self.assertEqual(ctx.dependencies, {"a": "a", "b": "b"})
            return [ValueProposal(ctx.dependencies["a"] + ctx.dependencies["b"])]
        tool, calls = make_tool({k: {"type": "string"} for k in ("a", "b", "c")})
        result = ArgumentInput(chooser_factory=lambda _: Picks("VALUE_0"), proposer=propose,
                               parallel_fields=2).build(state=TaskState("t", "example"), tool=tool,
            fields=[ArgumentField("a"), ArgumentField("b"), ArgumentField("c", ("a", "b"))])
        self.assertEqual(result.status, "ready")
        self.assertEqual(result.candidate.arguments, {"a": "a", "b": "b", "c": "ab"})
        self.assertFalse(calls)

    def test_missing_evidence_never_fabricates(self):
        tool, _ = make_tool({"id": {"type": "string"}})
        result = ArgumentInput(chooser_factory=lambda _: Picks(), proposer=lambda _: [ValueProposal("guessed")],
            helper_factory=lambda _: self.fail("must not create helper")).build(
            state=TaskState("t", "unknown account"), tool=tool, fields=[ArgumentField("id", require_evidence=True)])
        self.assertEqual(result.status, "lookup_required")
        self.assertIsNone(result.candidate)

    def test_explicit_clarify_does_not_trigger_construction(self):
        tool, _ = make_tool({"name": {"type": "string"}})
        result = ArgumentInput(chooser_factory=lambda _: Picks("CLARIFY"), proposer=lambda _: [ValueProposal("a")],
            helper_factory=lambda _: self.fail("must not create helper")).build(
                state=TaskState("t", "ambiguous"), tool=tool, fields=[ArgumentField("name")])
        self.assertEqual(result.status, "clarification_required")

    def test_changed_revision_discards_all_fields(self):
        state = TaskState("t", "example")
        def propose(ctx):
            state.revise("file")
            return [ValueProposal("x")]
        tool, calls = make_tool({"text": {"type": "string"}})
        result = ArgumentInput(chooser_factory=lambda _: Picks(), proposer=propose).build(
            state=state, tool=tool, fields=[ArgumentField("text")])
        self.assertEqual(result.status, "stale")
        self.assertIsNone(result.candidate)
        self.assertFalse(calls)

    def test_global_budget_counts_parallel_requests(self):
        tool, _ = make_tool({k: {"type": "string"} for k in ("a", "b")})
        result = ArgumentInput(chooser_factory=lambda _: Picks("VALUE_0"),
            proposer=lambda _: [ValueProposal("x")], max_choice_calls=1).build(
                state=TaskState("t", "example"), tool=tool, fields=[ArgumentField("a"), ArgumentField("b")])
        self.assertEqual(result.status, "budget_exhausted")
        self.assertEqual(result.choice_calls, 1)
        self.assertIsNone(result.candidate)

    def test_cross_field_validation_and_stale_commit(self):
        def check(args):
            if args["start"] > args["end"]:
                raise SchemaError("reversed interval")
        tool, calls = make_tool({k: {"type": "integer"} for k in ("start", "end")}, check)
        state = TaskState("t", "example")
        result = ArgumentInput(chooser_factory=lambda _: Picks("VALUE_0"),
            proposer=lambda ctx: [ValueProposal(5 if ctx.name == "start" else 1)]).build(
            state=state, tool=tool, fields=[ArgumentField("start"), ArgumentField("end")])
        self.assertEqual(result.status, "invalid_arguments")
        self.assertFalse(calls)
        valid = ArgumentInput(chooser_factory=lambda _: Picks("VALUE_0"), proposer=lambda _: [ValueProposal(1)]).build(
            state=state, tool=tool, fields=[ArgumentField("start"), ArgumentField("end")])
        state.revise("range")
        outcome = Agent(Picks("CLARIFY")).run(state=state, tool=tool, drafts=[valid.candidate])
        self.assertEqual(outcome.status, "clarification_required")
        self.assertFalse(calls)

    def test_cycle_rejected_before_provider_calls(self):
        tool, _ = make_tool({k: {"type": "string"} for k in ("a", "b")})
        with self.assertRaises(ValueError):
            ArgumentInput(chooser_factory=lambda _: self.fail(), proposer=lambda _: self.fail()).build(
                state=TaskState("t", "example"), tool=tool,
                fields=[ArgumentField("a", ("b",)), ArgumentField("b", ("a",))])

    def test_provider_failure_not_semantic_retry(self):
        seen = []
        def broken(ctx):
            seen.append(ctx.name)
            raise RuntimeError("network error with private detail")
        tool, _ = make_tool({"a": {"type": "string"}})
        result = ArgumentInput(chooser_factory=lambda _: Picks(), proposer=broken,
            helper_factory=lambda _: self.fail()).build(state=TaskState("t", "example"), tool=tool,
                                                       fields=[ArgumentField("a")])
        self.assertEqual(result.status, "provider_error")
        self.assertEqual(result.reason, "RuntimeError")
        self.assertEqual(seen, ["a"])

    def test_nonfinite_json_rejected(self):
        tool, _ = make_tool({"x": {"type": "number"}})
        result = ArgumentInput(chooser_factory=lambda _: Picks(), proposer=lambda _: [ValueProposal(float("nan"))]).build(
            state=TaskState("t", "example"), tool=tool, fields=[ArgumentField("x")])
        self.assertEqual(result.status, "construction_unavailable")


if __name__ == "__main__":
    unittest.main()
