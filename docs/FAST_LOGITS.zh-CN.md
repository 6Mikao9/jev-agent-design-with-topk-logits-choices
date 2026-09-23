# Fast raw logits / KV cache helper

`jev_agent.fast_logits.FastLogitsHelper` 是一个可单独使用的因果语言模型 helper：

```python
helper = FastLogitsHelper(model, tokenizer, device="cuda")
state = helper.prefill("prompt")
candidates = helper.top_k(state, 8)  # 按原始 logits 排序，不做 softmax
state = helper.advance(state, candidates[0])  # 只提交一个 token，复用 past_key_values
```

每个候选和状态都保留精确 token id 与 tokenizer token piece。`token_pieces` 是模型词表中的 piece（不保证等同于可读文本）；需要展示文本时，调用 tokenizer 对完整 token id 序列进行 decode，避免逐 token 解码造成边界错误。`advance` 接受 `FastToken` 或整数 token id。

首次 prefill 对完整输入调用一次模型并请求 `use_cache=True`；后续每次 advance 只输入单个 token，并传入上一步返回的 `past_key_values`。Transformers 传统嵌套 tuple cache 和实现 `Cache` 协议的新 cache 对象均作为不透明对象原样传递，不修改其内部结构。模型需支持 `past_key_values` 与 `use_cache` 参数。

## 限制

- 单个 helper/state 只适用于一条序列的顺序解码；共享同一 state 做并发请求不安全，模型和 cache 的线程安全由调用方负责。分支搜索请为分支复制/管理 cache，不能让多个分支推进同一状态。
- 不包含采样、温度、softmax、masking、批处理、beam 管理或自动 tokenizer padding/attention mask 处理。
- logits 和 token 排序取决于具体模型、tokenizer、输入格式、dtype 及 Transformers/模型实现；该 helper 不保证与其他推理栈或完整生成 pipeline 的输出完全一致。
- 需要安装 PyTorch；模型权重由调用方提供，本 helper 不下载模型。
