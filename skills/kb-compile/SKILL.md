---
name: kb-compile
version: 0.1.0
description: |
  Compile source material into wiki articles. Reads files from the KB root,
  code files, or any source content, generates structured wiki articles with
  frontmatter, and updates all indexes. Supports both research notes and code
  repositories.
allowed-tools:
  - Read
  - Write
  - Edit
  - Glob
  - Grep
  - Bash
trigger: /kb-compile
---

# /kb-compile — Compile Source Material into Wiki

Reads source material and compiles it into structured wiki articles.

## Usage

- `/kb-compile` — compile all unprocessed source material
- `/kb-compile some-article.md` — compile a specific file
- `/kb-compile src/` — compile from a code directory

## Workflow

### Step 1: Detect KB Root

Find the nearest directory containing `wiki/`. If not found, tell the user to run `/kb-init` first.

### Step 2: Find Uncompiled Sources

If no specific file is given, find source material not yet compiled:

1. **Determine the primary source root**
   - Always use the KB root itself as the source root
2. **Scan source files in the primary source root**
   - Include `.md`, `.txt`, `.pdf`, common code files, images, and other user-authored source material
   - Exclude `wiki/`, `outputs/`, hidden files/dirs, `CLAUDE.md`, `.gitignore`, and other KB-generated infrastructure
3. **Scan code files outside the primary source root if the user explicitly points to them** — for example `.py`, `.ts`, `.js`, `.go`, `.rs`, `.java`, `.md`

To check what's already compiled:
- Prefer `outputs/_manifest.json` if it exists:
  - compare recorded `digest` / `mtime_ns` values to detect new or stale sources
  - treat any missing manifest entry as uncompiled
- Fall back to reading wiki articles' frontmatter `sources:` fields only when the manifest is missing
- Store source paths relative to the KB root

If nothing to compile, inform the user.

Preferred deterministic entrypoint:

```bash
python3 -m llm_notes.compile plan --kb-root <kb-root> --json
```

Use the JSON result to drive the rest of the compile workflow:
- `new_sources` and `stale_sources` are the sources that need attention
- `unchanged_sources` can be skipped
- `manifest_in_use` tells you whether the plan came from `outputs/_manifest.json` or a fallback scan of existing article `sources:`

### Step 3: Read and Classify

For each source file:
1. Read the file content
2. Determine topics, concepts, and tags
3. Read `wiki/_index.md` to find existing related categories and articles
4. Decide: create a new article, or enrich an existing one?

### Step 4: Write Wiki Article

Create or update a wiki article with this structure:

```markdown
---
title: "Article Title"
created: YYYY-MM-DD
updated: YYYY-MM-DD
sources:
  - notes/path-to-source.md
  - src/path-to-code.ts
tags: [concept1, concept2]
---

## Summary

2-3 sentence overview of the topic.

## Content

Main content organized with headers. Use `[[wikilinks]]` to link related articles.

For code sources: explain architecture, key patterns, data flow, important functions.
For research sources: summarize findings, key concepts, methodologies.

## Sources

- `notes/path-to-source.md` — description of what this source contributed
- `src/path-to-code.ts` — description

## Related

- [[other-article]] — how it relates
- [[another-article]] — how it relates

## Open Questions

- Questions that came up during compilation
- Gaps that could be filled with more research
```

**Image handling:** If the source material contains or references images, use Obsidian-style image embeds that match the actual source path, for example `![[images/diagram.png]]` or `![[assets/diagram.png]]`.

Preferred deterministic article write:

1. Draft the article body content first, excluding YAML frontmatter.
2. Write it through the local helper instead of hand-editing article metadata and bookkeeping files yourself:

```bash
python3 -m llm_notes.compile write-article \
  --kb-root <kb-root> \
  --category <category> \
  --title "<Article Title>" \
  --source <source-path> \
  --tag <tag> \
  --body-stdin <<'EOF'
## Summary

2-3 sentence overview.

## Content

Main content with `[[wikilinks]]`.

## Sources

- `path/to/source.md` — what it contributed

## Related

- [[other-article]] — how it relates

## Open Questions

- Questions or gaps
EOF
```

The helper will:
- write or update the target wiki article
- preserve `created` on existing articles and refresh `updated`
- merge `sources` and `tags`
- update `outputs/_manifest.json`
- prepend a standardized `_recent.md` entry
- sync category and master indexes

### Step 5: Update Indexes

After writing the article:

1. **Category index** — Update or create `wiki/<category>/_index.md`:
   ```markdown
   # Category Name

   ## Articles

   - [[article-name]] — one-line description
   ```

2. **Master index** — Update `wiki/_index.md`:
   - Add category if new
   - Update article count
   - Update total sources count

3. **Glossary** — Add any new terms to `wiki/_glossary.md`:
   ```markdown
   ## Term Name
   Definition. See: [[related-article]]
   ```

4. **Recent updates** — Prepend to `wiki/_recent.md`:
   ```markdown
   - YYYY-MM-DD [[category/article-name]] — new / updated
   ```

5. **Manifest** — Update `outputs/_manifest.json`:
   - For every compiled source, store its relative path, content digest, source mtime, compile timestamp, and destination wiki articles
   - Keep the manifest deterministic and machine-readable so later `/kb-compile` and `/kb-lint` runs can diff source changes without reparsing every article

Fallback deterministic entrypoints after manual article writes:

```bash
python3 -m llm_notes.compile record --kb-root <kb-root> --source <source-path> --article <wiki/article.md>
python3 -m llm_notes.compile sync-indexes --kb-root <kb-root>
```

### Step 6: Report

After compilation, print:
- How many sources were compiled
- Which wiki articles were created or updated
- Any open questions or suggested follow-ups
