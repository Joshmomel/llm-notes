# llm-notes

LLM-powered personal knowledge base system. Source material goes in, a structured wiki comes out — compiled, indexed, and maintained entirely by an LLM.

Built as a set of [Claude Code](https://claude.ai/code) skills. Clone, install, and start using.

## How it works

1. You collect source material (articles, papers, code, images)
2. The LLM compiles it into a structured markdown wiki with summaries, backlinks, and cross-references
3. You ask questions against the wiki — answers cite sources and accumulate back into the knowledge base
4. The LLM runs health checks to find gaps, inconsistencies, and new topics to explore

Everything is viewable in [Obsidian](https://obsidian.md/).

## Install

```bash
git clone https://github.com/<user>/llm-notes.git
cd llm-notes
./install.sh
```

This symlinks the skills to `~/.claude/skills/` so they're available globally.

## Quick start

```bash
# In Claude Code, from any directory:
/kb-init .              # Initialize KB in current directory
# The current directory itself is the source root
# If the directory is empty, drop files here first
/kb-compile             # Compile into wiki
/kb-qa "your question"  # Ask questions
/kb-lint                # Health check
```

## Skills

| Skill | Description |
|-------|-------------|
| `/kb-init` | Initialize a knowledge base in any directory |
| `/kb-compile` | Compile source material from the current KB root into wiki articles |
| `/kb-qa` | Ask questions against the wiki, save answers, file back insights |
| `/kb-lint` | Health checks, stats, and exploration suggestions |

## Use cases

**Research notes** — Run `/kb-init` inside a folder that already contains your notes, or initialize an empty folder and drop files into it, then compile into a structured wiki and ask complex questions across all your sources.

**Code understanding** — Run `/kb-init` in a code repo, `/kb-compile` to generate architecture docs, then `/kb-qa` to ask questions about the codebase.

## Architecture

```
your-directory/
├── CLAUDE.md          # LLM operating instructions (auto-generated)
├── <your files>       # Source material lives directly in the KB root
├── wiki/              # LLM-compiled knowledge base
│   ├── _index.md      # Master index
│   ├── _glossary.md   # Term definitions
│   ├── _recent.md     # Recent updates
│   └── <category>/    # Topic directories with articles
└── outputs/           # Generated answers, slides, images
```

- **No database** — everything is markdown files
- **No RAG** — hierarchical indexes let the LLM navigate in 2-3 reads
- **No dependencies** — just Claude Code skills (structured prompts)
- The LLM writes and maintains the wiki. You rarely touch it directly.
