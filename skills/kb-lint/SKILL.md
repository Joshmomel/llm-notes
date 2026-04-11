---
name: kb-lint
version: 0.1.0
description: |
  Run health checks on the knowledge base. Reports stats, finds broken links,
  orphan articles, stale content, inconsistencies, and suggests new topics
  to explore. Auto-fixes what it can.
allowed-tools:
  - Read
  - Write
  - Edit
  - Glob
  - Grep
  - Bash
  - WebSearch
trigger: /kb-lint
---

# /kb-lint — Health Checks, Stats & Suggestions

Run health checks on the knowledge base. Produces a report with stats, issues, and exploration suggestions.

## Usage

- `/kb-lint` — full lint report

## Workflow

### Step 1: Detect KB Root

Find the nearest directory containing `wiki/`. If not found, tell the user to run `/kb-init` first.

### Step 2: Gather Stats

Count and report:
- Total wiki articles (`.md` files in `wiki/`, excluding `_` prefixed files)
- Total source files (eligible files in the KB root, plus any user-targeted code paths if applicable)
- Unprocessed sources (not referenced in any wiki article's `sources:` frontmatter)
- Recently updated articles (from `wiki/_recent.md`)

### Step 3: Run Checks

Perform these checks, collecting issues:

1. **Orphan articles** — wiki articles not linked from any `_index.md` file
2. **Broken wikilinks** — `[[links]]` in wiki articles that point to nonexistent files
3. **Stale articles** — wiki articles whose source files have been modified more recently than the article's `updated` frontmatter date
4. **Missing frontmatter** — wiki articles lacking required YAML fields (title, created, updated, sources, tags)
5. **Uncovered sources** — eligible source files in the KB root not referenced by any wiki article
6. **Index drift** — `_index.md` files that don't list all articles actually in their directory, or list articles that don't exist
7. **Connection suggestions** — articles that share tags but don't link to each other via `[[wikilinks]]`
8. **Inconsistent data** — conflicting facts or claims across different wiki articles
9. **Missing data** — gaps in coverage that could be filled (suggest using web search to impute)
10. **Suggested explorations** — interesting questions to ask, new article candidates based on patterns in existing content, unexplored connections between concepts

### Step 4: Auto-fix

Automatically fix what's safe to fix:
- **Index drift** — update `_index.md` files to match actual directory contents
- **Missing frontmatter** — add missing fields with sensible defaults
- **Orphan articles** — add them to the appropriate `_index.md`

For each auto-fix, note what was changed.

### Step 5: Generate Report

Save report to `outputs/lint-report.md`:

```markdown
---
date: YYYY-MM-DD
---

# KB Health Report

## Stats

- Total articles: N
- Total sources: N
- Unprocessed sources: N
- Last updated: YYYY-MM-DD

## Health Score: X/10

## Issues Found

### Critical
- (broken links, missing files)

### Warning
- (stale articles, missing frontmatter)

### Info
- (uncovered sources, connection suggestions)

## Auto-fixed

- (what was automatically corrected)

## Suggested Explorations

- Questions worth investigating based on current wiki content
- New article candidates (topics referenced but not covered)
- Interesting connections between existing concepts
- Gaps that could be filled with further research
```

### Step 6: Print Summary

Print a brief summary to the user:
- Health score
- Number of issues by severity
- Top 3 suggested explorations
- Note any auto-fixes that were applied
