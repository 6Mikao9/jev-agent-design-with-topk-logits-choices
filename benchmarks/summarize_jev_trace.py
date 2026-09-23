from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def sentences(text: str) -> list[str]:
    """Turn a token trace's final text into readable, non-empty sentences."""
    text = text.replace("\r\n", "\n").strip()
    if not text:
        return []
    result: list[str] = []
    for line in text.splitlines():
        line = re.sub(r"^\s*(?:[*+-]|\d+[.)])\s*", "", line).strip()
        if not line:
            continue
        # Keep bullets as complete statements while splitting ordinary prose.
        chunks = re.split(r"(?<=[。！？!?])\s+|(?<=[.!?])\s+(?=[A-Z\"\'])", line)
        result.extend(chunk.strip() for chunk in chunks if chunk.strip())
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    parser.add_argument("--json", type=Path, required=True)
    args = parser.parse_args()

    source = json.loads(args.input.read_text(encoding="utf-8"))
    compact_cases: list[dict] = []
    md: list[str] = [
        "# Jev dialogue readable trace",
        "",
        "This is a compact view of the full token trace. Candidate lists, logits, and repeated prefixes were removed.",
        "`context` is the user/system material supplied to the run. `jev_path` is the accepted text assembled from the helper vocabulary; this run used the reproducible `local_top1_proxy`, not a live Jev API call.",
        "",
    ]
    for case in source["cases"]:
        guided = case["guided"]
        answer_sentences = sentences(guided.get("answer", ""))
        compact = {
            "id": case["id"],
            "turns": [
                {"source": "context", "role": "user", "text": case["user"]},
                *[
                    {"source": "jev_path", "role": "assistant", "text": sentence}
                    for sentence in answer_sentences
                ],
            ],
            "chooser": guided.get("chooser"),
            "status": guided.get("status"),
            "stop_reason": guided.get("stop_reason"),
            "output_tokens": guided.get("output_tokens"),
            "elapsed_ms": guided.get("elapsed_ms"),
            "helper_latency_ms_total": guided.get("helper_latency_ms_total"),
            "chooser_latency_ms_total": guided.get("chooser_latency_ms_total"),
            "helper_tokens_per_second": guided.get("helper_tokens_per_second"),
            "tokens_per_second": guided.get("tokens_per_second"),
        }
        compact_cases.append(compact)
        md.extend(
            [
                f"## {case['id']}",
                "",
                f"**[context｜我们提供]** {case['user']}",
                "",
            ]
        )
        for sentence in answer_sentences:
            md.extend([f"**[jev_path｜选择器补充]** {sentence}", ""])
        md.extend(
            [
                f"**[control｜结束]** `{guided.get('stop_reason')}`；状态 `{guided.get('status')}`；生成 {guided.get('output_tokens')} tokens；helper {guided.get('helper_latency_ms_total')} ms；chooser {guided.get('chooser_latency_ms_total')} ms；端到端 {guided.get('elapsed_ms')} ms。",
                "",
            ]
        )
    compact_result = {
        "experiment": source.get("experiment"),
        "helper_model": source.get("helper_model"),
        "chooser": source.get("chooser"),
        "note": "Compact trace: context is supplied input; jev_path is accepted text from the chooser path; token candidates and logits are omitted.",
        "cases": compact_cases,
    }
    args.markdown.write_text("\n".join(md), encoding="utf-8")
    args.json.write_text(json.dumps(compact_result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {args.markdown} and {args.json}")


if __name__ == "__main__":
    main()
