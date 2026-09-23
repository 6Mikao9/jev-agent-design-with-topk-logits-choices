# 将技术设计公开到 GitHub

作者：匿名作者 · 文档版本：v0.5-prototype

GitHub 适合公开这份设计：README 提供入口，Markdown 正文便于阅读和修改，讨论与后续实现可以集中在同一仓库。公开设计可以在完整实验前完成。

## 仓库信息，可直接复制

仓库名：`jev-agent-design`

Description：

> Jev natural-language conversation prototype: Qwen-0.8B helper logits produce a dynamic Top-k token table, Jev chooses each next token, and the project extends this loop to agent tools, fallback, memory, and replanning.

建议的 GitHub Description（可直接复制）：

> Jev natural-language conversation prototype using Qwen-0.8B helper logits and dynamic Top-k token selection. Jev chooses each next token for fluent dialogue, with agent tools, fallback, memory, and replanning.

建议 Topics：

```text
jev
typesafe
qwen-0.8b
logits
top-k
token-selection
natural-language-generation
conversational-ai
autoregressive-generation
ai-agents
tool-calling
```

GitHub Topics（添加到仓库 About 区域，每项一个主题）：

```text
jev
typesafe
ai-agents
agent-framework
tool-calling
function-calling
agent-memory
hierarchical-memory
decision-models
top-k
small-language-models
diffusion-language-models
ai-infrastructure
research
technical-design
```

Topics 用于表达项目主题。发布版本使用的 Git tag 可设为 `v0.5-prototype`，它与主题标签分别填写。

## 建议的仓库结构

```text
jev-agent-design/
├── README.md
└── docs/
    ├── DESIGN.zh-CN.md
    ├── DESIGN.en.md
    ├── CANDIDATE_COVERAGE.zh-CN.md
    ├── CANDIDATE_COVERAGE.en.md
    ├── OPTIONAL_IDEAS.zh-CN.md
    ├── OPTIONAL_IDEAS.en.md
    └── PUBLISHING.zh-CN.md
```

其中 `DESIGN.zh-CN.md` 和 `DESIGN.en.md` 是主文档的中英文版本，`CANDIDATE_COVERAGE.*.md` 单独讨论 I2，`OPTIONAL_IDEAS.*.md` 记录采纳状态和备选路线。建议将这组文件一起上传，保留完整链接。

## 发布步骤

1. 在自己的 GitHub 账号下新建公开仓库，可使用 `jev-agent-design` 或自选名称。
2. 本版本不公开作者身份。初稿日期保留为写作日期，首次公开时间以实际发布为准。
3. 将本目录内容上传到仓库根目录。README 中的链接已经按这一目录结构编写。
4. 可以发布一个 `v0.5-prototype` Release，说明项目已有 Qwen‑0.8B + Jev 的可运行自然语言对话原型，并加入“辅助 logits 生成动态 token 表、Jev 逐步选择下一 token”的协议说明。此前的 v0.4 为进行中设计版本。
5. 后续修改保留版本说明；新增实现、机制或实验时写清楚该版本增加了什么。

GitHub Release 关联仓库历史中的标签。标签日期和 Release 日期可能不同，分享时可以给出明确的版本链接。[GitHub Release 官方说明](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)

## 署名与引用信息

本匿名版本只包含完整标题、版本和仓库链接，不包含真实姓名或公开 ID。不要把本地草稿日期称作首次公开日期。分享时建议引用具体 Release 或提交，而非只链接持续变化的默认分支。

这份文档没有预先替作者选择许可证。发布者可以根据希望允许他人怎样引用、修改和再发布文档来选择相应许可；后续代码可以另行采用代码许可证。

## 与后续论文的衔接

公开设计能够记录具体披露内容并获取反馈。后续可把经过实现、分析与实验支持的结果整理成论文，更新相关工作和贡献声明。

arXiv 通常不接受纯研究提案，并对提交内容进行审核。GitHub 技术设计与 arXiv 研究文章应根据各自内容要求准备；也应在确定投稿 venue 后核对其当时的预印本和匿名政策。[arXiv 内容类型要求](https://info.arxiv.org/help/policies/content-types.html)

如果后续论文使用了重要的生成式 AI 辅助，应按目标平台要求说明用途，并由署名作者核对与负责文中内容。[arXiv 对生成式 AI 工具的要求](https://info.arxiv.org/help/moderation/index.html)
