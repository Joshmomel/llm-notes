---
name: kb-init
version: 0.1.0
description: |
  Initialize a knowledge base in any directory. Creates wiki/, outputs/,
  CLAUDE.md operating instructions, and starter index files.
allowed-tools:
  - Bash
  - Read
  - Write
  - Edit
  - Glob
trigger: /kb-init
---

# /kb-init — Initialize Knowledge Base

Initialize a knowledge base in the specified directory (default: current directory).

## Usage

- `/kb-init` or `/kb-init .` — initialize in current directory
- `/kb-init ~/research/topic-x` — initialize in a specific directory

## Workflow

1. **Check if KB already exists** — if `wiki/` already exists in the target directory, inform the user and stop (idempotent).

2. **Check if directory has existing files** — scan the target directory for existing files (`.md`, `.py`, `.ts`, `.js`, code files, documents, images, etc.), excluding hidden files/dirs and excluding KB infrastructure files that may already exist.
   - **If files exist:** Do NOT create `raw/`. The existing files in the directory ARE the source material. Treat the target directory itself as the source root and compile those files directly.
   - **If directory is empty:** Do NOT create `raw/`. Still treat the target directory itself as the source root, but tell the user to drop source files into the directory before running `/kb-compile`.

3. **Create directory structure:**
   ```
   <target>/
   ├── wiki/
   ├── outputs/
   │   ├── answers/
   │   ├── _manifest.json
   │   ├── slides/
   │   └── images/
   ```

3. **Create `wiki/_index.md`:**
   ```markdown
   # Knowledge Base Index

   ## Categories

   (No categories yet. Run `/kb-compile` to compile source material into wiki articles.)

   ## Recent Updates

   (No updates yet.)

   ## Stats

   - Total articles: 0
   - Total sources: 0
   ```

4. **Create `wiki/_glossary.md`:**
   ```markdown
   # Glossary

   (No terms yet. Terms are added automatically when articles are compiled.)
   ```

5. **Create `wiki/_recent.md`:**
   ```markdown
   # Recent Updates

   (No updates yet. This file is updated automatically when articles are compiled.)
   ```

6. **Create `outputs/_manifest.json`:**
   ```json
   {
     "version": 1,
     "updated_at": null,
     "sources": {}
   }
   ```

7. **Create `.gitignore`** (only if it doesn't exist):
   ```
   .obsidian/
   .DS_Store
   ```

8. **Create `CLAUDE.md`** with the following content:

   ```markdown
   # Knowledge Base

   This directory is an LLM-managed knowledge base, viewable in Obsidian.

   ## Structure

   - `<kb-root>` existing files and subdirectories — Source material. The KB root itself is the source root.
   - `wiki/` — LLM-compiled knowledge base. You (the LLM) are the primary author.
   - `outputs/` — Generated artifacts (answers, slides, images).

   ## Core Principles

   1. Every wiki article MUST have YAML frontmatter: title, created, updated, sources, tags
   2. Use Obsidian `[[wikilinks]]` for internal links (NOT markdown links)
   3. Use relative paths for images that match the real source location, for example `![[images/foo.png]]` or `![[assets/diagram.png]]`
   4. Never delete source data. Wiki articles are derived; source material in the KB root is canonical.
   5. Every wiki article MUST cite its sources in the `sources:` frontmatter field

   ## Navigation Protocol

   When answering questions or researching:
   1. Read `wiki/_index.md` to find relevant categories
   2. Read the category `_index.md` for specific articles
   3. Read the specific articles you need
   4. If wiki coverage is insufficient, inspect source files in the KB root while excluding `wiki/`, `outputs/`, hidden dirs, `CLAUDE.md`, and `.gitignore`
   5. Note any gaps for later compilation

   ## Wiki Article Format

   ---
   title: "Article Title"
   created: YYYY-MM-DD
   updated: YYYY-MM-DD
   sources:
     - notes/some-file.md
     - src/auth/login.ts
   tags: [topic1, topic2]
   ---

   Sections: Summary, Content, Sources, Related, Open Questions

   ## Index Maintenance

   After creating or updating any wiki article:
   1. Update `wiki/<category>/_index.md` (create category dir if needed)
   2. Update `wiki/_index.md` (master index — categories list, stats)
   3. Update `wiki/_glossary.md` with any new terms
   4. Update `wiki/_recent.md` with the change
   5. Update `outputs/_manifest.json` with source digests and destination article paths

   ## Available Skills

   - `/kb-compile` — Compile source material from the KB root into wiki articles
   - `/kb-chat` — Keep a multi-turn KB conversation transcript and promote stable synthesis back into the KB
   - `/kb-qa` — Ask questions against the wiki, save answers, optionally file back
   - `/kb-lint` — Run health checks, view stats, get exploration suggestions
   ```

8.5 **Install the project-local Claude Code control plane** so answer saving / filing is reinforced by local instructions and a PreToolUse hook:

```bash
python3 -m llm_notes.claude install --kb-root <target>
```

This keeps the KB workflow from depending only on skill text by also updating local `CLAUDE.md` guidance and `.claude/settings.json`.

9. **Auto-compile** — After initialization, automatically run the `/kb-compile` workflow to compile any existing source material in the directory into wiki articles. If the directory is empty, skip this step and explicitly tell the user the KB has no source files yet and they should drop files into the directory first.

10. **Print summary:**
   ```
   KB initialized in <target>/
   - Source mode: KB root (`<target>/`)
   - N files compiled into wiki articles (if files existed)
   - If no files existed, drop files into <target>/ and run /kb-compile
   - Run /kb-chat for transcript-backed follow-up conversations
   - Run /kb-qa to ask questions
   - Run /kb-lint for health checks
   - Open this directory in Obsidian to view
   ```
