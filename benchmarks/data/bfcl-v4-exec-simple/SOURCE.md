Dataset: BFCL V4 exec_simple
Repository: https://github.com/EnlightenedAI/BFCL
Snapshot commit: 6ea57973c7a6097fd7c5915698c54c17c5b1b6c8 (2026-03-23)
Files: berkeley-function-call-leaderboard/bfcl_eval/data/unused_datasets/question/BFCL_v4_exec_simple.json and berkeley-function-call-leaderboard/bfcl_eval/data/unused_datasets/possible_answer/BFCL_v4_exec_simple.json
Official category documentation: https://github.com/EnlightenedAI/BFCL/blob/main/berkeley-function-call-leaderboard/bfcl_eval/data/README.md
License: Apache-2.0; the upstream LICENSE file is retained here.

SHA-256:
- questions.jsonl: `32EE3959E8E3F92FAC1E90E55BF5FA41C759BFEF4E6A2D88421AF527A859D0A4`
- answers.jsonl: `4584017C92AE9A2407EAC25BCEC2496233A32A08182301B15F65538AA575B5A7`
- LICENSE: `C71D239DF91726FC519C6EB72D318EC65820627232B2F796219E87DCF35D0AB4`

This source subset has 100 single-function executable questions and reference calls. We use it to measure next-token candidate coverage against one reference call per task. The upstream BFCL executable runner is not invoked by this prototype benchmark, so results are not BFCL leaderboard scores.
