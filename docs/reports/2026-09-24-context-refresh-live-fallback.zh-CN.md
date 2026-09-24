# 真实 Jev + raw evidence fallback

脚本：`benchmarks/benchmark_context_refresh_live.py`  
结果：`benchmarks/results/context-refresh-live-with-fallback.json`

## 协议

本轮在上一轮真实 Jev smoke 后增加了 context-space 的 `ContextEvidenceFallback`：

```text
Jev 只看摘要
  ├─ YES → coordinator 检查 epoch/revision 后换入
  └─ NO/NO_EVIDENCE → 对目录候选有界 materialize raw body
                    → evidence marker + revision 校验
                    → 只有唯一完整候选才换入
```

gold block ID 仍然只在评估器中保存，Jev 只看到不透明 ID、摘要、revision 和 query。raw fallback 使用的是环境提供的 evidence contract，不把目标 ID直接传入模型。

## 结果

| case | Jev/coordinator | raw fallback | 最终命中 |
| --- | --- | --- | ---: |
| current deploy 缺失 | `committed b17` | 未触发 | 是 |
| rollback 缺失 | `committed b63` | 未触发 | 是 |
| audit evidence 缺失 | `no_supported_block` | `recovered b88`，213 bytes | 是 |
| current deploy 已驻留 | `no_gain b17` | 未触发 | 是 |
| Atlas plan 歧义、无 gold | `no_supported_block` | `no_match`，212 bytes | 否，安全拒绝 |

汇总：初始驻留命中 **1/4**，只使用 Jev coordinator 时命中 **3/4**；加入 raw evidence fallback 后最终命中 **4/4 gold case**，3 个真正缺失 case 恢复 **3/3**。无 gold 歧义 case 没有误刷新。

本轮 20 次真实 Jev 调用均产生 `NO_EVIDENCE` 结果中的至少一个，但只有 audit case 触发了唯一 evidence recovery。说明 `NO_EVIDENCE` 作为“需要原文”的控制信号有用；它不应被当成错误页选择，也不能直接等价于正确答案。

## 成本与限制

- 20 次 Jev verifier 调用，总报告模型耗时约 **14.09 秒**；
- 单次调用 P50/P95：**690.6 / 767.7 ms**，范围 620.6–799.7 ms；
- raw fallback 是本地有界读取，本轮读取 213/212 bytes；没有额外 Jev 往返；
- 目录召回仍为 4/4，尚未测目录漏召回；
- evidence marker 是受控契约，不是语义判定；真实系统需要来源、字段和冲突证据检查；
- 样本只有 5 个，不能推出一般正确率或 confidence calibration。

相对上一轮：结果**明显更好**，audit case 从 `no_supported_block` 恢复为正确 block，同时歧义 case 仍保持拒绝。代价是 verifier 的 Jev 调用成本不变；fallback 只解决“摘要不足”，不能解决目录本身漏掉目标页。
