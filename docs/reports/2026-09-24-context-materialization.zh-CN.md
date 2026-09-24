# Context block 正文 materialization 契约

脚本：`benchmarks/benchmark_context_materialization.py`  
结果：`benchmarks/results/context-materialization.json`

## 本轮实现

`ContextResidencyManager` 继续只负责 block ID、摘要和 working/cold 驻留；新增 `ContextMaterializer` 负责在 block 已被选中后读取 `raw_content_ref` 指向的正文。正文来源必须是显式 mapping 或 callback，不会把字符串引用直接当作任意文件路径。

materializer 在返回正文前检查：

- block 是否 stale；
- caller 提供的 expected revision 是否匹配；
- UTF-8 解码是否成功；
- 正文是否超过 `max_bytes`；
- 返回正文的字节数和 SHA-256，便于证据 trace。

它不负责修改 resident set，也不负责提交工具副作用；epoch/revision 的最终提交仍由上层 coordinator 负责。

## 代理结果

4 个 deterministic case：两个摘要遗漏关键 marker、一个 revision 过期、一个正文超预算。

| 指标 | 结果 |
| --- | ---: |
| 成功 materialize | 2/4 |
| 找回关键 marker | 2/2 成功读取的证据 case |
| stale/预算拒绝 | 2/4 |
| 远端测试 | 130 项全部通过 |

结果符合预期：摘要没有包含 marker 时，选中的 block 可以在受限正文中找回证据；过期和超预算正文被拒绝。该结果只验证加载契约，不代表语义证据校验正确，也没有调用 Jev。

## 边界

当前 live refresh 仍只让 Jev 看 block 摘要；下一步可以在 `NO_EVIDENCE` 后由 materializer 加载正文，再通过 evidence contract 或第二次受控 verifier 校验。若将来接文件源，必须增加 workspace resolver 和权限检查，不能把 `raw_content_ref` 直接解释为任意路径。
