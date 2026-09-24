# 目录排序：简单词法 ranking 的真实 Jev 对照

## 目的

在第 6 轮的 visited-window 修复上，加入一个透明的 query-aware lexical page ranking 选项。它只读取用户 query 和页摘要，不使用 gold page/tool；默认 `catalog` 顺序保持不变，`lexical` 仅用于实验。

## 配置

- seed=31、12 页 × 24 工具
- `wrong_page` 12-case 子集
- `ACCEPT/PAGE` 执行前 scope verifier
- 每次最多 8 个选项，resident 上限 2，最大 12 次调用
- 默认 catalog 与 lexical 使用不同的一次性 Jev 凭据/运行，不能当作严格 paired 随机控制

## 结果

| 指标 | catalog（第6轮） | lexical（本轮） |
|---|---:|---:|
| 成功 | 9/12 (75.0%) | 7/12 (58.3%) |
| 首页定位 | 10/12 | 7/12 |
| missing detection | 11/12 | 11/12 |
| candidate rejection | 3 | 3 |
| directory exhausted | 2 | 0 |
| Jev 调用 | 58 | 48 |
| request P50 | 639.8 ms | 637.8 ms |
| case P50 / P95 | 3.30 / 4.53 s | 2.62 / 3.38 s |
| resident 峰值 | 2/2 | 2/2 |

失败集中在 verifier 后的过早 `STOP`：`recent`、`monitor`、`docs`、`accounts` 各有一例，另有 `web` 误 `CLARIFY`。词法排序减少了调用和尾延迟，却没有提高定位或恢复；这个结果不能证明语义检索无效，只能说明简单摘要词重合不是足够的 page locator。

## 判断

相对预期：**质量更差、成本略好**。因此 `lexical` 不设为默认策略，只保留为 baseline。生产方向应比较摘要 embedding/RRF、多个候选页并行 verifier、目录窗口 visited 反馈和明确的 `directory_exhausted → CLARIFY/STOP` 语义。

## 下一步

把 locator 指标拆成目录召回、Jev 页选择、verifier false reject 和终态预算；再加入语义/混合检索候选集，确保比较不是把词法分数误称为模型概率。
