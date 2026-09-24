# PAGE 投机预取首轮报告

日期：2026-09-24  
报告文件：`benchmarks/results/speculative-page.json`  
脚本：`benchmarks/benchmark_speculative_page.py`

## 实验边界

这是固定转移轨迹上的 timing model，不是真实 Jev、网络或 GPU 结果。每次当前决策等待期间，预测器按显式转移排序预取 top-1 或 top-2 page；目标页只在轨迹结束后用于评分。预取内容在独立 shadow buffer 中，不进入 `VirtualOptionManager` 的 resident set。

## 结果

运行参数：`jev_wait_ms=20`，21 个页面转移，准备成本由固定页面成本表给出。

|策略|命中率|有效预取比|剩余 page stall|隐藏准备时间|浪费比|
|---|---:|---:|---:|---:|---:|
|关闭|0%|0%|432 ms|0 ms|0%（无预取）|
|Top-1|45%|45%|268 ms|164 ms|55%|
|Top-2|65%|32.5%|194 ms|238 ms|67.5%|

数字来自本次固定轨迹运行；`benchmarks/results/` 被 Git 忽略，完整逐步 trace 只保留在本机/远端项目目录。

相对关闭策略，Top-1 隐藏了 164 ms（约 38.0% 的 page stall），Top-2 隐藏了 238 ms（约 55.1%）。Top-2 命中率更高，但有效预取比从 45% 降至 32.5%，浪费比升至 67.5%。按这个模型，Top-2 的覆盖收益伴随明显额外准备；这比“预取越宽越好”的预期更差，暂不值得直接扩大到 REFINE 树。

## 预期解读边界

Top-2 可能提高覆盖，同时增加无用准备和资源占用；命中也只能隐藏 `min(准备耗时, Jev 等待窗口)`。该实验不能证明真实端到端加速，也不能证明小模型的 page 排序与 Jev 概率一致。下一步才是接入真实 page materialization、取消、共享资源竞争和 Jev trace。
