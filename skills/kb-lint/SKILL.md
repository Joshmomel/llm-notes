---
name: kb-lint
version: 0.1.0
description: |
  Run health checks on the knowledge base. Reports stats, finds broken links,
  orphan articles, stale content, uncovered sources, and answer notes that
  should be filed back into the wiki. Auto-fixes safe bookkeeping issues.
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
- Total answer notes in `outputs/answers/`
- Filed vs pending answers
- High-value pending answers that should likely be promoted into `wiki/`

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
11. **Pending answer filing queue** — answer notes that remain in `outputs/answers/` but now look reusable enough to file into the wiki
12. **Filed answer target drift** — answers marked as filed whose destination wiki article no longer exists

Preferred deterministic helper:

```bash
python3 -m llm_notes.lint --kb-root <kb-root> --json
```

Use the helper output and generated report as the primary health-check result instead of hand-assembling the report.
The helper's JSON output now includes a structured `pending_queue` with executable filing recommendations.

### Step 3.5: Build Semantic Candidate Set

Before doing any semantic inconsistency or gap analysis, generate the deterministic candidate shortlist:

```bash
python3 -m llm_notes.semantic_lint --kb-root <kb-root> --json
```

This writes:

- `outputs/lint-semantic-candidates.json` — machine-readable candidate set
- `outputs/lint-semantic-candidates.md` — human-readable shortlist and review instructions

Use these files to focus the semantic review instead of scanning the whole wiki blindly.

The candidate set is specifically meant to drive:

- **Inconsistent facts** — article pairs with overlapping tags/sources/category likely to contain conflicting claims
- **Connection discovery** — article pairs that share tags/sources but still are not linked
- **Missing data** — articles whose `Open Questions` sections indicate unresolved gaps
- **Web-backed imputation** — open questions that likely require external verification or missing factual lookup
- **Pending answer synthesis** — unanswered filing opportunities still stuck in `outputs/answers/`

After reviewing the candidate set, write the semantic findings to:

- `outputs/lint-semantic.md`

This semantic report should be separate from the deterministic `outputs/lint-report.md`.

### Step 4: Auto-fix

Automatically fix what's safe to fix:
- **Index drift** — update `_index.md` files to match actual directory contents
- **Missing frontmatter** — add missing fields with sensible defaults
- **Orphan articles** — add them to the appropriate `_index.md`
- **Bookkeeping sync** — regenerate wiki indexes when you are asked to auto-fix or the report should refresh bookkeeping

For each auto-fix, note what was changed.

Preferred deterministic helper with safe fixes:

```bash
python3 -m llm_notes.lint --kb-root <kb-root> --fix --json
```

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
- Total answers: N
- Filed answers: N
- Pending answers: N
- High-value pending answers: N

## Health Score: X/10

## Issues Found

### Critical
- (broken links, missing files)

### Warning
- (stale articles, missing frontmatter)

### Info
- (uncovered sources, connection suggestions)

## Answer Filing Queue

- `outputs/answers/YYYY-MM-DD-slug.md` — score 0.80 — recommend `enrich` or `new`
- candidate target article if known
- exact command to execute the recommendation, for example:
  `python3 -m llm_notes.answers file --kb-root . --answer outputs/answers/YYYY-MM-DD-slug.md --mode enrich --article ml/attention`

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
- Number of high-value pending answers waiting to be filed
- Number of semantic hotspot candidates generated
- Top 3 suggested explorations
- The top 1-3 executable filing recommendations from the queue
- Note any auto-fixes that were applied
