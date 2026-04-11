# llm-notes

[English](README.md) | [简体中文](README.zh-CN.md)

`llm-notes` is a lightweight knowledge base workflow for [Claude Code](https://claude.ai/code). It turns a directory of notes, papers, code, screenshots, and other mixed source material into an LLM-maintained Markdown wiki. Q&A outputs, indexes, and health reports remain local files, making the system easy to inspect, version, and browse in [Obsidian](https://obsidian.md/).

This project is inspired by **Andrej Karpathy**'s idea. See: [LLM Knowledge Bases](https://x.com/karpathy/status/2039805659525644595)

## Overview

`llm-notes` treats the knowledge base root itself as the source root. Original files stay directly in the KB root, `wiki/` stores LLM-compiled articles, indexes, and glossary pages, and `outputs/` stores generated artifacts such as answers, slides, and images.

Unlike workflows that require a `raw/` + `wiki/` layout, the current implementation of `llm-notes` does **not** require a separate `raw/` directory. If a directory already contains files, `/kb-init` treats those files as the canonical source material and initializes the derived wiki structure around them.

## Core Capabilities


| Command       | Purpose                                                                                                                                                                         |
| ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `/kb-init`    | Initialize a knowledge base directory, create `wiki/`, `outputs/`, `CLAUDE.md`, and starter indexes, and auto-compile existing material when present                            |
| `/kb-compile` | Read source material from the KB root, create or update structured wiki articles, and maintain `_index.md`, `_glossary.md`, and `_recent.md`                                    |
| `/kb-qa`      | Answer questions against the wiki, reuse `/kb-search`'s TF-IDF index to shortlist relevant articles, extend the local knowledge network through related concepts, fall back to source files when coverage is insufficient, save answers to `outputs/answers/`, and optionally file insights back into the wiki |
| `/kb-lint`    | Run health checks, identify orphan articles, broken wikilinks, stale content, and uncovered sources, save a report to `outputs/lint-report.md`, and auto-fix safe issues        |
| `/kb-slides`  | Generate Marp-format slide decks from wiki content, save to `outputs/slides/`, viewable in Obsidian with the Marp plugin                                                       |
| `/kb-viz`     | Generate matplotlib charts and diagrams from wiki data, save to `outputs/images/`, embeddable in wiki articles                                                                  |
| `/kb-search`  | Full-text search across the wiki using a TF-IDF inverted index, usable directly or as a retrieval accelerator for `/kb-qa` and larger LLM queries                              |


## Design Principles

- **Markdown-first**: important knowledge lives in local files you can inspect and version.
- **Source-first**: original files are authoritative; wiki articles are derived and regenerable.
- **LLM-maintained**: summaries, indexes, backlinks, glossary entries, and filed-back insights are maintained by the LLM.
- **Obsidian-friendly**: the output structure and link style are designed to work well as a local Obsidian vault.
- **Minimal infrastructure**: no database, service layer, or mandatory vector store is required to get started.

## Use Cases

- Research vaults for papers, archived web articles, screenshots, reading notes, and mixed source material
- Codebase understanding, architecture notes, and navigable documentation for existing repositories
- Long-running topic investigations where each query should accumulate back into the knowledge base
- Local-first knowledge management where important outputs remain inspectable as Markdown files

## Requirements

- [Claude Code](https://claude.ai/code)
- A directory that already contains source material, or an empty directory you want to turn into a knowledge base
- [Obsidian](https://obsidian.md/) if you want the best browsing experience

## Installation

```bash
git clone https://github.com/Joshmomel/llm-notes.git
cd llm-notes
./install.sh
```

`install.sh` symlinks the skills in this repository into `~/.claude/skills/` and installs the local `llm_notes` Python helper package in editable mode. That package backs stable search and manifest helpers, so `/kb-search` no longer depends on generating an ad hoc script body inside each vault.

## Quick Start

After installation, open any directory you want to use as a knowledge base in Claude Code and run:

```bash
# inside Claude Code
/kb-init .
/kb-qa "What are the main themes in this knowledge base?"
/kb-lint
```

If the directory already contains files, `/kb-init` will initialize the KB structure and auto-compile the existing material.

If the directory is empty, `/kb-init` will create the KB structure first. After you add source files into that directory, run:

```bash
# inside Claude Code
/kb-compile
/kb-qa "What key concepts have been established so far?"
```

## Typical Workflows

### Existing Notes Or Repository

Use this when you already have documents, code, or research material in a directory:

```bash
# inside Claude Code
/kb-init .
/kb-qa "Summarize the main themes and structure here"
/kb-lint
```

### Start From An Empty Directory

Use this when you want to build a new knowledge base from scratch:

```bash
# inside Claude Code
/kb-init .
# add notes, code, PDFs, images, or other source files into this directory
/kb-compile
/kb-qa "What topics have emerged in the knowledge base so far?"
```

### Generate Slides From Wiki Content

```bash
/kb-slides "Introduction to Transformer Architecture"
# -> outputs/slides/2026-04-11-intro-transformers.md (Marp format)
# View in Obsidian with Marp plugin, or export: marp --pdf outputs/slides/*.md
```

### Visualize Data From Wiki

```bash
/kb-viz "Compare parameter counts across model architectures"
# -> outputs/images/2026-04-11-model-params.png
# Embed in wiki: ![[outputs/images/2026-04-11-model-params.png]]
```

### Search The Wiki

```bash
/kb-search "attention mechanism"
# -> Ranked results with TF-IDF scoring and snippet previews
# -> The same index can be reused by /kb-qa to narrow the reading set before synthesis
```

### Full Research Loop

A complete workflow combining all skills:

```bash
/kb-init .                           # Initialize and auto-compile
/kb-qa "What are the key findings?"  # Ask questions, file answers back
/kb-slides "Summary of findings"     # Generate a presentation
/kb-viz "Timeline of key events"     # Create a visualization
/kb-lint                             # Check health, get exploration suggestions
/kb-compile                          # Re-compile after adding new material
```

## Generated Knowledge Base Layout

```text
your-kb/
├── CLAUDE.md             # LLM operating instructions for this KB
├── <source files...>     # Canonical source material stays in the KB root
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
    └── slides/
```

Important detail: in the current implementation, source files live directly in the KB root. `llm-notes` does **not** require a separate `raw/` directory.

## Repository Layout

```text
llm-notes/
├── llm_notes/
│   ├── manifest.py
│   └── search.py
├── skills/
│   ├── kb-init/
│   ├── kb-compile/
│   ├── kb-qa/
│   ├── kb-lint/
│   ├── kb-slides/
│   ├── kb-viz/
│   └── kb-search/
├── tests/
│   ├── test_manifest.py
│   └── test_search.py
├── pyproject.toml
├── install.sh
├── README.md
└── README.zh-CN.md
```

## Scope And Limitations

- This is a prompt-and-files workflow, not a hard-coded indexing engine.
- Knowledge quality depends on the quality of the source material and on the LLM consistently following the KB conventions.
- The `wiki/` layer becomes more valuable over time as more material is compiled, more answers are filed back, and more lint issues are resolved.
- The current approach is especially well suited to small and medium-sized knowledge bases that can be navigated effectively through summaries and indexes.

## References

- [LLM Knowledge Bases](https://x.com/karpathy/status/2039805659525644595)
- [graphify README](https://github.com/safishamsi/graphify/blob/v4/README.md)
- [WikiLLM README](https://github.com/wang-junjian/wikillm/blob/main/README.md)
