# Round 18：255-entry 目录页与 Jev 调用预算

## 目标

把用户提出的“Option Space 页面与 Jev 的 255 个 Choice 上限对齐”具体化，区分
逻辑目录页和实际决策批次，并核对 Jev 的上下文预算。

## 实现

- 新增 `jev_agent/option_budget.py`：
  - `JEV_MAX_OPTIONS=255`；
  - `OptionPageBudget.catalog_pages()` 按最多 255 个逻辑条目切页；
  - `decision_calls()` 默认每次 16 个动作候选，并为控制出口预留 6 个名额；
  - 检查控制项重复、控制项预留和 255 总数上限。
- 导出 `OptionPageBudget`、`OptionCall` 及常量。
- 新增 `tests/test_option_budget.py` 的 3 个边界测试。
- 文档：`docs/OPTION_PAGE_BUDGET.zh-CN.md`、Virtual Option 技术报告、Option Space 状态机说明和 README 链接。

## 结果

本地 bundled Python 测试：**140 passed，3 skipped**（可选 torch/symlink 条件），
其中新增预算测试全部通过。255 个目录候选被切成 `[255,255]`；40 个候选在 4 个
控制项下切成 `[16,16,8]`，每个调用均不超过 255。

官方 TypeSafe 文档写明 Choice 最多 255 个选项；Jev 1.13 当前上下文预算为每请求
64k tokens，`state` 加最长单个问题 32k tokens。仓库的 24 KiB Context Frame 是
按 UTF-8 字节计的保守分区预算，本地 Qwen 服务的 2048-token 参数也是测试配置，
不是 Jev 的官方上下文上限。

## 设计判断

用户关于“目录页对齐 255”的建议可采纳，且比原来笼统的“超过 8 就分页”更精确。
如果把 255 个动作全部交给 Jev，控制出口会挤占名额、候选描述会膨胀，实际决策
质量和延迟未必好。因此保留 `255 catalog → 8/16/32 decision batch + controls`
的两级边界；默认 16 只是待验证的工程点，后续用真实 Jev 消融而不是文档直觉定案。

AIOS 只作为 runtime 资源分层的相关工作启发；它没有证明 255 是合适的页面大小，
本轮没有把 AIOS 的实现复制进项目。

## 相对预期

**比预期清楚，尚未证明质量更好。** 255 上限和 Jev 上下文上限现在有了可核验的
定义，代码也有边界测试；但真实 Jev 在 8/16/32/64 候选下的准确率、延迟和控制项
误选率尚未测，本轮不宣称默认 16 最优。

