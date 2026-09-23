# Small helper-model shortlist

The first prototype separates the helper from Jev. A causal model can provide
the next-token logits used by Top-k fallback; a diffusion model can provide
batch field proposals, but cannot be dropped into the same next-token API
without an autoregressive scoring adapter.

| Candidate | Size / access | Fit for this work | Recommendation |
| --- | --- | --- | --- |
| `HuggingFaceTB/SmolLM2-135M-Instruct` | 135M parameters, Apache-2.0 | Smallest practical instruct checkpoint on this shortlist. Candidate for schema-conditioned field proposals, constrained query writing, and later LoRA/SFT. The model card calls out English-focused training and weak arithmetic/editing, so test Chinese tasks separately. | First fine-tuning candidate; begin with English synthetic tool schemas. |
| `Qwen/Qwen3-0.6B` | 0.6B parameters, Apache-2.0, roughly 1.5 GB on the published HF repo | Stronger small causal baseline and directly exposes the logits needed by `TransformersLogitsBackend`. Use the official checkpoint; check the model's usage restrictions before applying it to a domain. | Quality baseline beside SmolLM2; the prototype defaults to CPU until a caller explicitly chooses a device. |
| `Qwen/Qwen3.5-0.8B` | 0.8B parameters, Apache-2.0, about 1.75 GB in the ModelScope snapshot used here | Current small helper candidate with the same tokenizer vocabulary as Qwen3.8-27B, making token-ID overlap measurements valid. Its hybrid text/vision architecture loads in the installed Transformers/SGLang stack. | Preferred helper for the new next-token overlap and Jev-vocabulary experiment; keep Qwen3-0.6B as the older control. |
| PlaidQ | 0.7B continuous diffusion model; paper reports released training/inference code and checkpoints | Recent code-generation DLM with few-step/one-step distillation work. It is not yet established as a tool-parameter generator, and its interface is full-sequence denoising rather than next-token logits. | Interesting follow-up as a full-field proposal backend after causal baseline results. |
| Plaid 1B | 1B diffusion LM with research code and published weights | Primarily a likelihood/unconditional and zero-shot-control research model. The reference code requires fused CUDA/Apex setup; scale and interface are less attractive for a tiny parameter proposer. | Keep as a research comparison only if PlaidQ or a smaller diffusion model proves useful. |
| microDLM | 10.7M parameter character-level teaching implementation | Small enough to modify from scratch, but trained on Tiny Shakespeare and a character vocabulary. It demonstrates masking/denoising mechanics; it is not a general-purpose tool-argument model. | Use for explaining and modifying diffusion mechanics, not as the task-quality baseline. |

Recommended comparison order:

1. Proposal-only `SmolLM2-135M-Instruct`, without tuning.
2. The same model fine-tuned on schema → validated field proposals. Split by
   tool/schema family so test schemas are not copied from training.
3. `Qwen3-0.6B` as a size/quality control.
4. `Qwen3.5-0.8B` as the current helper for same-vocabulary candidate tests.
5. PlaidQ as a full-field proposal generator only, with matched task and
   generation budgets. Keep Top-k fallback on a causal logits backend.

### Initial logits coverage result

Qwen3-0.6B was run in BF16 on all 100 BFCL V4 `exec_simple` tasks. Across 2,324
reference-call tokens, the gold next token appeared in top 8 for 98.97% of
positions and top 32 for 99.83%. A perfect chooser could reproduce 78/100 calls
at k=8 and 96/100 at k=32. This is teacher-forced candidate availability with
an oracle chooser, not Jev accuracy or end-to-end tool success. Keep the split
held out if tuning this model.

Do not train on “Jev selected this candidate” alone. Store labels for proposal
validity, tool execution result, and task completion separately. Include
counterexamples with missing facts so the small model learns to ask for lookup
or clarification instead of inventing IDs or constraints.

## DeepSeek V4.1

The official DeepSeek V4.1-Flash checkpoint is described as a 552B-parameter
MoE with 8B active parameters for input and 16B for output. It is the smallest
official model found in this architecture family, but no tiny student, toy, or
distilled checkpoint with the same architecture was verified. It is outside the
four-RTX-5090 machine's practical scope, so this project skips it unless a
small compatible checkpoint appears.

## Sources

- [SmolLM2-135M-Instruct model card](https://huggingface.co/HuggingFaceTB/SmolLM2-135M-Instruct)
- [Qwen3-0.6B model card and files](https://huggingface.co/Qwen/Qwen3-0.6B)
- [PlaidQ paper](https://arxiv.org/abs/2609.04531) and [reference implementation](https://github.com/pengzhangzhi/plaidq)
- [Plaid paper](https://arxiv.org/abs/2305.18619) and [reference implementation](https://github.com/igul222/plaid)
- [microDLM educational implementation](https://github.com/BrutalCaeser/microDLM)
- [DeepSeek's V4.1-Flash release description](https://deepseek.com/en/news/deepseek-v4-1-flash/) and [official checkpoint configuration](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash/blob/main/inference/config.json)
