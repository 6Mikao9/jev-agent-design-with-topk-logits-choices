# Inference Docker setup

Updated 2026-09-23. Long-lived environments, model weights, logs, caches, and
working copies are under `$HOME` inside the user's Docker. A temporary
download manifest was kept in `/tmp` within the same container. No host
filesystem, sibling container, or system CUDA installation was modified.

## Installed software

| Component | Version / location |
| --- | --- |
| SGLang | 0.5.20, `$HOME/.venvs/sglang-stable` |
| vLLM | 0.30.0, `$HOME/.venvs/vllm-stable` |
| Qwen3.8-27B | `$HOME/models/Qwen3.8-27B`, ModelScope snapshot, 33/33 files SHA-256 verified |
| Qwen3-0.6B helper | `$HOME/models/Qwen3-0.6B`, ModelScope snapshot |
| Qwen3.5-0.8B helper | `$HOME/models/Qwen3.5-0.8B`, ModelScope snapshot, 14/14 files downloaded |
| BabyLM MDLM small proposal model | `$HOME/models/babylm-2026-mdlm-small`, Apache-2.0, 98.4M parameters, optional masked-diffusion experiment |

The Docker already had system CUDA 12.8. SGLang's PyTorch environment uses
CUDA 13.0, so its JIT compiler must use the matching CUDA 13.0.88 toolchain
installed inside the SGLang venv. Source `$HOME/.sglang-env.sh`
before launching SGLang. Its `lib64` and `libcudart.so` links are confined to
that venv; `/usr/local/cuda-12.8` was left untouched. Both venvs passed
`pip check`.

## Shared GPU rule

Run `nvidia-smi` immediately before every launch. Use only card IDs that are
idle at that time, and set `CUDA_VISIBLE_DEVICES` to those exact IDs. On the
2026-09-23 smoke runs, GPUs 0 and 1 already had about 26 GiB allocated, so only
the then-idle GPUs 2 and 3 were used. All test services were stopped afterward;
the final check showed cards 2 and 3 back at 2 MiB. Recheck every time because
the server is shared.

The Qwen3.8-27B weights used about 25.6 GiB on each card in BF16. The tested
servers were deliberately limited to a 2,048-token context on two 32-GiB
RTX 5090 cards. Do not raise the context limit without measuring free memory
and the current users of each selected GPU.

## Start SGLang

After confirming that the selected physical cards are idle, replace `2,3`
below if needed:

```sh
source $HOME/.venvs/sglang-stable/bin/activate
source $HOME/.sglang-env.sh
CUDA_VISIBLE_DEVICES=2,3 HF_HUB_OFFLINE=1 MODELSCOPE_OFFLINE=1 \
python -m sglang.launch_server \
  --model-path $HOME/models/Qwen3.8-27B \
  --tp-size 2 --host 127.0.0.1 --port 30000 --dtype bfloat16 \
  --context-length 2048 --max-total-tokens 2048 \
  --max-running-requests 1 --mem-fraction-static 0.92 \
  --disable-cuda-graph --trust-remote-code
```

## Start vLLM

Use the same idle-card check and adjust IDs as needed. This installed build
needs its FlashInfer sampler disabled on this host; the PyTorch sampling path
passed the live request check.

```sh
source $HOME/.venvs/vllm-stable/bin/activate
CUDA_VISIBLE_DEVICES=2,3 VLLM_USE_FLASHINFER_SAMPLER=0 \
HF_HUB_OFFLINE=1 MODELSCOPE_OFFLINE=1 \
vllm serve $HOME/models/Qwen3.8-27B \
  --tensor-parallel-size 2 --max-model-len 2048 --max-num-seqs 1 \
  --gpu-memory-utilization 0.90 --enforce-eager \
  --host 127.0.0.1 --port 30000 --dtype bfloat16 --trust-remote-code
```

Both engines completed an OpenAI-compatible chat request when bound to
`127.0.0.1`. They are not left running, so they do not reserve GPU memory.

## Top-k and dialogue experiments

The project benchmark scripts live under
`$HOME/jev-agent-prototype/benchmarks`. The next-token comparison
uses the SGLang `/generate` endpoint with `return_logprob=true` and
`top_logprobs_num=250`; the helper phase loads Qwen3.5-0.8B on one idle card,
then the large-model phase uses Qwen3.8-27B on two idle cards. The dialogue
runner offers a separate `END_DIALOGUE` choice and writes its trace under the
project's `benchmarks/results` directory. Its default local top-1 chooser is a
reproducible dry run; the live TypeSafe adapter is only used when its caller
explicitly provides a process environment key.

## Helper benchmark

The Qwen3-0.6B helper loaded in BF16 on one idle RTX 5090. The BFCL V4
`exec_simple` 100-task teacher-forced coverage run took 41.9 seconds. Results
are in the local project at
`benchmarks/results/bfcl-v4-exec-simple-qwen3-0.6b-topk-100.json` and are an
oracle upper bound on helper-token availability, not an end-to-end Jev score.

The current prototype also contains `jev_agent/fast_logits.py` (raw logits and
KV-cache decode), `jev_agent/paged_memory.py` (bounded page-table reads with
revision checks), `jev_tools/` (local Jev/MCP-shaped tool contracts), and the
masked-diffusion proposal runner. Their weights and raw JSON results stay under
`$HOME/models` and the project `benchmarks/results` directory; none are added
to Git.

Temporary result files are moved into the project tree after each run. No
service is left running: stop the exact launch PID and verify cards 2 and 3
return to their idle memory before handing the machine back to other users.
