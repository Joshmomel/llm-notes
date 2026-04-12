---
name: kb-qa
version: 0.1.4
description: |
  Ask questions against the knowledge base wiki. Reuses the wiki
  full-text search index only when broad or ambiguous questions need
  retrieval help, then navigates indexes, extends the local knowledge
  network through related links and neighboring concepts, reads
  relevant articles, synthesizes answers with citations, surfaces
  gaps and deep follow-up investigation threads, saves to outputs/,
  and optionally files insights back into the wiki.
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
trigger: /kb-qa
---

# /kb-qa — Question Answering

Ask questions against the knowledge base. Answers are synthesized from wiki articles with citations and should surface promising next questions, nearby concepts, and deeper investigation threads.

## Usage

- `/kb-qa How do transformers handle long sequences?`
- `/kb-qa What authentication patterns does this codebase use?`
- `/kb-qa Compare the approaches discussed in the diffusion papers`

## Workflow

### Step 1: Detect KB Root

Find the nearest directory containing `wiki/`. If not found, tell the user to run `/kb-init` first.

### Step 2: Research

Follow the navigation protocol to find relevant content:

1. **Read `wiki/_index.md`** — identify relevant categories and distill likely search terms
2. **Read category `_index.md` files** — confirm coverage and identify specific articles
3. **Use the `/kb-search` path only when it will materially improve recall**:
   - Prefer direct wiki navigation first for specific questions or small-to-medium knowledge bases
   - Reach for search when the question is broad, ambiguous, cross-cutting, or the candidate set is too large to navigate confidently from indexes alone
   - If `wiki/_search.py` is available and `python3 wiki/_search.py stale` prints `fresh`, run `python3 wiki/_search.py search "<question keywords>"` to shortlist candidate articles
   - If the wrapper or index is missing or stale, skip search during `/kb-qa` instead of installing or rebuilding infrastructure mid-answer
   - Treat search as a retrieval accelerator, not a substitute for reading the cited sources
4. **Read relevant articles** — read 3-10 articles that relate to the question, prioritizing high-ranked search hits when available
5. **Extend the knowledge network** — from the strongest seed articles, follow relevant `[[wikilinks]]`, backlinks, sibling articles in the same category, contrasting approaches, and prerequisite concepts for 1-2 hops to map nearby concepts that materially change the answer
6. **Track deep investigation threads** — note open loops, contradictions, edge cases, second-order implications, and unresolved comparisons worth pursuing beyond the initial answer
7. **Check source files if needed** — if wiki coverage is insufficient, read KB-root files directly while excluding `wiki/`, `outputs/`, hidden dirs, `CLAUDE.md`, and `.gitignore`
8. **Note gaps** — track any topics the wiki doesn't cover well
9. **Note next questions** — track concrete follow-up questions opened up by the evidence, contradictions, missing coverage, or network expansion

### Step 3: Synthesize Answer

Write a comprehensive answer:
- If the user is writing in another language, localize the section titles, but keep the same four-section structure and order
- Put any tables, comparisons, or richer exposition inside `## Main Conclusion`, not in place of the required skeleton
- Use `[[wikilinks]]` to cite wiki articles inline
- Include specific details from the articles
- If you found conflicting information, note it
- Distinguish the direct answer from adjacent but relevant concepts discovered during network expansion
- If the wiki has gaps, mention what's missing
- Include a `## Knowledge Network Extension` section with 3-7 related concepts, articles, or branches that should be traversed next, and say how each one connects to the question
- Include a `## Deep-Dive Threads` section with 3-7 concrete investigation threads that would deepen or stress-test the answer
- Include a `## Further Questions` section with 3-7 concrete next questions or investigation threads
- Make the follow-up questions specific to what you learned, not generic research boilerplate
- For each follow-up question, add a short clause about why it matters or what evidence would help answer it

### Step 4: Save Answer

Save to `outputs/answers/YYYY-MM-DD-slug.md`:

```markdown
---
title: "Answer: <question summary>"
date: YYYY-MM-DD
question: "<full question>"
sources_consulted:
  - wiki/category/article.md
  - wiki/category/other-article.md
filed_to_wiki: false
---

# <Question>

## Main Conclusion

<Direct answer with [[wikilinks]] citations. This section can contain comparisons, tables, and synthesized judgment, but it must stay under this heading.>

## Knowledge Network Extension

- [[category/adjacent-article]] — how it extends, reframes, or challenges the current answer
- [[category/prerequisite-concept]] — why this concept should be traversed next

## Deep-Dive Threads

- A concrete thread to pursue next — what contradiction, edge case, or comparison makes it worth deeper tracking
- Another multi-step investigation path — what evidence or source would move it forward

## Further Questions

- A specific follow-up question raised by the answer — why it matters
- Another question to investigate next — what evidence would resolve it

## Sources Consulted

- [[category/article]] — what it contributed to the answer
- [[category/other-article]] — what it contributed

## Gaps Identified

- Topics not covered in the wiki
- Areas that need more research
```

The short answer shown to the user in chat should mirror the same four sections, even if abbreviated.

Prefer the deterministic helper instead of hand-editing answer frontmatter yourself:

```bash
python3 -m llm_notes.answers save \
  --kb-root <kb-root> \
  --question "<full question>" \
  --source-consulted wiki/category/article.md \
  --source-consulted wiki/category/other-article.md \
  --body-stdin <<'EOF'
# <Question>

## Main Conclusion

...

## Knowledge Network Extension

...

## Deep-Dive Threads

...

## Further Questions

...

## Sources Consulted

...

## Gaps Identified

...
EOF
```

Default behavior: always save the answer note first. `outputs/answers/` is the audit layer for KB Q&A.

### Step 5: Offer to File Back

After saving the answer, decide whether it should be promoted into the wiki:

- Auto-file by default when the answer is clearly reusable synthesis:
  - it combines 2 or more sources
  - it establishes a durable comparison, taxonomy, decision, or concept link
  - it should obviously enrich an existing article or become a new article
- Do not auto-file low-value or ephemeral answers:
  - one-off operational answers
  - short fact lookups
  - answers that mostly repeat one existing article
- If the destination article is ambiguous or filing would be risky, ask the user before filing.

Prefer the deterministic filing helper:

```bash
python3 -m llm_notes.answers file \
  --kb-root <kb-root> \
  --answer outputs/answers/YYYY-MM-DD-slug.md \
  --mode auto
```

If you already know it should enrich a specific article:

```bash
python3 -m llm_notes.answers file \
  --kb-root <kb-root> \
  --answer outputs/answers/YYYY-MM-DD-slug.md \
  --mode enrich \
  --article category/article
```

The helper will:
1. Resolve consulted wiki articles back to canonical source files
2. Create a new wiki article or append a dated filed insight to an existing one
3. Update bookkeeping via the local helpers (`_index.md`, `_recent.md`, `outputs/_manifest.json`)
4. Mark the answer note as filed and record the destination wikilink

This way explorations and queries always "add up" in the knowledge base.
