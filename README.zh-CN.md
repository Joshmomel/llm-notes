# llm-notes

[English](README.md) | [简体中文](README.zh-CN.md)

`llm-notes` 是一套面向 [Claude Code](https://claude.ai/code) 的轻量知识库工作流，用于将一个目录中的笔记、论文、代码、截图或其他混合材料整理为由 LLM 维护的 Markdown wiki。问答结果、索引和健康检查都保留为本地文件，便于在 [Obsidian](https://obsidian.md/) 中浏览、版本化与持续迭代。

本项目基于 **Andrej Karpathy** 提出的理念构建。详见：[LLM Knowledge Bases](https://x.com/karpathy/status/2039805659525644595)

## 项目概述

`llm-notes` 将知识库根目录本身视为源目录。原始文件直接保留在知识库根目录中，`wiki/` 保存 LLM 编译后的文章、索引和词汇表，`outputs/` 保存问答、幻灯片和图像等生成产物。

与一些采用 `raw/` + `wiki/` 布局的方案不同，`llm-notes` 当前实现**不强制使用 `raw/` 目录**。如果目录中已经有文件，`/kb-init` 会直接以这些文件作为权威源材料，并自动初始化派生 wiki 结构。

## 核心能力


| 命令            | 作用                                                                              |
| ------------- | ------------------------------------------------------------------------------- |
| `/kb-init`    | 初始化知识库目录，创建 `wiki/`、`outputs/`、`CLAUDE.md` 和基础索引；如果目录已有内容，会自动编译现有材料             |
| `/kb-compile` | 读取知识库根目录中的源材料，先计算确定性的 source/article 编译计划，再生成或更新结构化 wiki 文章，并维护 `_index.md`、`_glossary.md`、`_recent.md` |
| `/kb-chat`    | 开启多轮 KB 对话，把完整对话轨迹保存到 `outputs/sessions/`，在同一会话里承接 follow-up，并把稳定结论沉淀回答案或 wiki |
| `/kb-qa`      | 基于现有 wiki 回答问题，需要时同时利用编译后的 wiki 与原始 source 的双层检索，并沿相关概念延伸知识网络；将答案保存到 `outputs/answers/`，并可选择回填到 wiki |
| `/kb-lint`    | 执行健康检查，识别孤立文章、失效 wikilinks、过时内容和未覆盖源文件，将报告保存到 `outputs/lint-report.md`，并自动修复安全项 |
| `/kb-slides`  | 基于 wiki 内容生成 Marp 幻灯片，保存到 `outputs/slides/`，可在 Obsidian 中配合 Marp 插件查看 |
| `/kb-viz`     | 基于 wiki 数据生成 matplotlib 图表和关系图，保存到 `outputs/images/`，可嵌入到 wiki 文章 |
| `/kb-search`  | 基于 TF-IDF 倒排索引对 wiki 做全文搜索；既可直接使用，也可作为 `/kb-qa` 等更大查询流程的检索加速器 |


## 设计原则

- **Markdown 优先**：关键内容都落在本地文件中，便于检查和版本控制。
- **源文件优先**：原始文件是权威来源；wiki 文章是可再生成的派生层。
- **LLM 持续维护**：摘要、索引、关联、术语表和回填内容由 LLM 维护。
- **Obsidian 友好**：目录结构和链接形式适合直接在 Obsidian 中浏览。
- **最小基础设施**：不要求数据库、服务层或向量存储即可开始使用。

## 适用场景

- 研究资料库：论文、网页存档、读书笔记、截图、图片等混合材料
- 代码库理解：架构说明、数据流梳理、关键模块索引
- 长周期主题研究：让多次问答和中间产物持续沉淀到知识库中
- 本地优先知识管理：希望所有内容都以可审阅的 Markdown 文件存在

## 环境要求

- [Claude Code](https://claude.ai/code)
- 一个已有源材料的目录，或一个准备作为知识库的空目录
- [Obsidian](https://obsidian.md/)（可选，但推荐）

## 安装

```bash
git clone https://github.com/Joshmomel/llm-notes.git
cd llm-notes
./install.sh
```

`install.sh` 会将仓库中的 skill 目录软链接到 `~/.claude/skills/`，并以 editable 模式安装本地 `llm_notes` Python 辅助包。现在这层实现已经覆盖 search、manifest、source/article compile planning 和 wiki/index helpers，因此核心 KB 行为可以逐步从 skill 文本约定迁到仓库内可版本化的本地代码。

## 快速开始

安装完成后，在 Claude Code 中打开任意一个你想作为知识库的目录，然后运行：

```bash
# 在 Claude Code 中
/kb-init .
/kb-chat "先梳理这个知识库的主线，并把 follow-up 放进同一会话"
/kb-qa "这个知识库里有哪些主要主题？"
/kb-lint
```

如果目录里已经有文件，`/kb-init` 会初始化知识库结构并自动编译现有材料。

如果目录是空的，`/kb-init` 会先创建知识库结构；你在目录中放入源文件后，再运行：

```bash
# 在 Claude Code 中
/kb-compile
/kb-qa "目前已经整理出了哪些关键概念？"
```

## 典型工作流

### 已有笔记或代码仓库

适用于你已经在一个目录中积累了文档、代码或研究资料的情况：

```bash
# 在 Claude Code 中
/kb-init .
/kb-chat "总结这里的核心主题和结构，并保持会话继续"
/kb-lint
```

### 从空目录开始

适用于你想从零建立新的知识库：

```bash
# 在 Claude Code 中
/kb-init .
# 将笔记、代码、PDF、图片或其他源文件放入当前目录
/kb-compile
/kb-qa "当前知识库中已经形成了哪些主题？"
```

### 保持在同一个 KB 会话里

如果你预期会连续追问同一个主题，更适合用 `/kb-chat`：

```bash
/kb-chat "比较这里的 dense attention 和 retrieval"
# -> 对话轨迹会累积到 outputs/sessions/YYYY-MM-DD-*.md
# -> 稳定结论仍然可以提炼到 outputs/answers/ 并回填 wiki/
```

## 生成后的知识库结构

```text
your-kb/
├── CLAUDE.md             # 该知识库的 LLM 操作说明
├── <source files...>     # 权威源材料保留在知识库根目录
├── wiki/
│   ├── _index.md
│   ├── _glossary.md
│   ├── _recent.md
│   └── <category>/
│       ├── _index.md
│       └── <article>.md
└── outputs/
    ├── _manifest.json
    ├── answers/
    ├── images/
    ├── sessions/
    └── slides/
```

重要说明：当前实现中，源文件直接保存在知识库根目录；`llm-notes` **不要求单独的 `raw/` 目录**。

`outputs/_manifest.json` 现在会同时跟踪编译状态的两侧：
- `sources` 记录源文件 digest、mtime、目标 wiki 文章，以及供后续 planning 使用的稳定 `article_targets`
- `articles` 记录文章的 title/category/slug，以及上次编译时使用的 source refs 和 source digests

这使 `/kb-compile` 不只能判断“哪些源文件变了”，还可以进一步判断“哪些既有文章受影响”以及“默认应该新建或刷新哪篇文章”。

## 仓库结构

```text
llm-notes/
├── llm_notes/
│   ├── chat.py
│   ├── compile.py
│   ├── manifest.py
│   ├── search.py
│   └── wiki.py
├── skills/
│   ├── kb-chat/
│   ├── kb-init/
│   ├── kb-compile/
│   ├── kb-qa/
│   ├── kb-lint/
│   ├── kb-slides/
│   ├── kb-viz/
│   └── kb-search/
├── tests/
│   ├── test_compile.py
│   ├── test_manifest.py
│   ├── test_search.py
│   └── test_wiki.py
├── pyproject.toml
├── install.sh
├── README.md
└── README.zh-CN.md
```

## 使用说明与边界

- 这是一个基于 prompt 与文件约定的工作流，不是硬编码的索引引擎。
- 知识库质量取决于源材料质量，以及 LLM 是否持续遵守知识库约定。
- `wiki/` 的价值会随着编译材料增加、问答结果回填和 lint 修复而逐步提高。
- 该方案尤其适合小到中等规模、可通过索引和摘要高效导航的知识库。

## 参考资料

- [LLM Knowledge Bases](https://x.com/karpathy/status/2039805659525644595)
- [graphify README](https://github.com/safishamsi/graphify/blob/v4/README.md)
- [WikiLLM README](https://github.com/wang-junjian/wikillm/blob/main/README.md)
