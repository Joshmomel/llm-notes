---
name: kb-qa
version: 0.1.3
description: |
  Ask questions against the knowledge base wiki. Reuses the wiki
  full-text search index when available to shortlist candidate
  articles, then navigates indexes, extends the local knowledge
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
2. **Reuse the `/kb-search` search path when possible**:
   - If `wiki/_search.py` is missing, create it using the same script contract as `/kb-search` and make it executable
   - If `wiki/_search_index.json` is missing or older than the newest wiki article, rebuild it with `python3 wiki/_search.py index`
   - Run `python3 wiki/_search.py search "<question keywords>"` to shortlist candidate articles
   - Treat search as a retrieval accelerator, not a substitute for reading the cited sources
3. **Read category `_index.md` files** — confirm coverage and identify specific articles (read 1-3 category indexes)
4. **Read relevant articles** — read 3-10 articles that relate to the question, prioritizing high-ranked search hits when available
5. **Extend the knowledge network** — from the strongest seed articles, follow relevant `[[wikilinks]]`, backlinks, sibling articles in the same category, contrasting approaches, and prerequisite concepts for 1-2 hops to map nearby concepts that materially change the answer
6. **Track deep investigation threads** — note open loops, contradictions, edge cases, second-order implications, and unresolved comparisons worth pursuing beyond the initial answer
7. **Check source files if needed** — if wiki coverage is insufficient, read KB-root files directly while excluding `wiki/`, `outputs/`, hidden dirs, `CLAUDE.md`, and `.gitignore`
8. **Note gaps** — track any topics the wiki doesn't cover well
9. **Note next questions** — track concrete follow-up questions opened up by the evidence, contradictions, missing coverage, or network expansion

### Step 3: Synthesize Answer

Write a comprehensive answer:
- The answer body must use the same four-part skeleton every time, in this exact order:
  1. `## Main Conclusion`
  2. `## Knowledge Network Extension`
  3. `## Deep-Dive Threads`
  4. `## Further Questions`
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

### Step 5: Offer to File Back

Ask the user: "File this back into the wiki?"

If yes:
1. Extract key insights from the answer
2. Create a new wiki article or enrich an existing one with the synthesized knowledge
3. Add or update wikilinks so the newly surfaced neighboring concepts become part of the wiki graph
4. Update all indexes (`_index.md`, `_glossary.md`, `_recent.md`)
5. Update the answer file: set `filed_to_wiki: true` and add a link to the destination article

This way explorations and queries always "add up" in the knowledge base.
