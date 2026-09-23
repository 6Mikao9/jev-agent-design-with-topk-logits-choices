import unittest

try:
    import torch
except ImportError:  # optional model dependency
    torch = None

from jev_agent.fast_logits import FastLogitsHelper


@unittest.skipIf(torch is None, "torch optional dependency is not installed")
class FastLogitsTests(unittest.TestCase):
    def test_prefill_then_single_token_decode_uses_cache_and_raw_logits(self):
        class Tokenizer:
            eos_token_id = 9

            def __call__(self, text, return_tensors):
                return type("Encoded", (), {"input_ids": torch.tensor([[1, 2]])})()

            def convert_ids_to_tokens(self, token_id):
                return f"p{token_id}"

        class Model:
            def __init__(self):
                self.calls = []

            def parameters(self):
                yield type("Param", (), {"device": torch.device("cpu")})()

            def __call__(self, *, input_ids, use_cache, past_key_values=None):
                self.calls.append((input_ids.tolist(), past_key_values, use_cache))
                logits = torch.tensor([[[0., 1., 6., 2., 3., 4., 5., -1., -2., 7.]]])
                cache = ("cache", len(self.calls))
                return type("Output", (), {"logits": logits, "past_key_values": cache})()

        model = Model()
        helper = FastLogitsHelper(model, Tokenizer())
        state = helper.prefill("hi")
        proposals = helper.top_k(state, 2)
        self.assertEqual([p.token_id for p in proposals], [9, 2])
        self.assertEqual([p.logit for p in proposals], [7.0, 6.0])
        self.assertEqual(model.calls[0], ([[1, 2]], None, True))
        following = helper.advance(state, proposals[1])
        self.assertEqual(model.calls[1][0], [[2]])
        self.assertEqual(model.calls[1][1], state.past_key_values)
        self.assertEqual(following.token_ids, (2,))
        self.assertEqual(following.token_pieces, ("p2",))
        self.assertEqual(following.prompt_length, 2)

    def test_topk_adapter_materializes_one_decode_for_repeated_candidate_checks(self):
        class Tokenizer:
            eos_token_id = 9

            def __call__(self, text, return_tensors):
                return type("Encoded", (), {"input_ids": torch.tensor([[1, 2]])})()

            def convert_ids_to_tokens(self, token_id):
                return f"p{token_id}"

            def decode(self, ids, **_kwargs):
                return "".join(f"p{x}" for x in ids)

        class Model:
            def __init__(self):
                self.calls = []

            def parameters(self):
                yield type("Param", (), {"device": torch.device("cpu")})()

            def __call__(self, *, input_ids, use_cache, past_key_values=None, **_kwargs):
                self.calls.append((input_ids.tolist(), past_key_values, use_cache))
                logits = torch.arange(10, dtype=torch.float32).reshape(1, 1, 10)
                return type("Output", (), {"logits": logits, "past_key_values": ("cache", len(self.calls))})()

        model = Model()
        helper = FastLogitsHelper(model, Tokenizer())
        state = helper.start(context="ctx", prefix="")
        proposals = helper.next_top_k(state=state, k=2)
        first = helper.append_token(state=state, token=proposals[0])
        second = helper.append_token(state=state, token=proposals[1])
        self.assertEqual(len(model.calls), 1)  # prefill only; append is lazy
        helper.next_top_k(state=first, k=2)
        helper.next_top_k(state=first, k=2)
        self.assertEqual(len(model.calls), 2)  # one cached single-token decode
        self.assertEqual(second.token_ids, (8,))


if __name__ == "__main__":
    unittest.main()
