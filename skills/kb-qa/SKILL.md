---
name: kb-qa
version: 0.1.0
description: |
  Ask questions against the knowledge base wiki. Navigates indexes,
  reads relevant articles, synthesizes answers with citations,
  saves to outputs/, and optionally files insights back into the wiki.
allowed-tools:
  - Read
  - Write
  - Edit
  - Glob
  - Grep
trigger: /kb-qa
---

# /kb-qa — Question Answering

Ask questions against the knowledge base. Answers are synthesized from wiki articles with citations.

## Usage

- `/kb-qa How do transformers handle long sequences?`
- `/kb-qa What authentication patterns does this codebase use?`
- `/kb-qa Compare the approaches discussed in the diffusion papers`

## Workflow

### Step 1: Detect KB Root

Find the nearest directory containing `wiki/`. If not found, tell the user to run `/kb-init` first.

### Step 2: Research

Follow the navigation protocol to find relevant content:

1. **Read `wiki/_index.md`** — identify relevant categories
2. **Read category `_index.md` files** — identify specific articles (read 1-3 category indexes)
3. **Read relevant articles** — read 3-10 articles that relate to the question
4. **Check source files if needed** — if wiki coverage is insufficient, read KB-root files directly while excluding `wiki/`, `outputs/`, hidden dirs, `CLAUDE.md`, and `.gitignore`
5. **Note gaps** — track any topics the wiki doesn't cover well

### Step 3: Synthesize Answer

Write a comprehensive answer:
- Use `[[wikilinks]]` to cite wiki articles inline
- Include specific details from the articles
- If you found conflicting information, note it
- If the wiki has gaps, mention what's missing

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

<Answer with [[wikilinks]] citations>

## Sources Consulted

- [[category/article]] — what it contributed to the answer
- [[category/other-article]] — what it contributed

## Gaps Identified

- Topics not covered in the wiki
- Areas that need more research
```

### Step 5: Offer to File Back

Ask the user: "File this back into the wiki?"

If yes:
1. Extract key insights from the answer
2. Create a new wiki article or enrich an existing one with the synthesized knowledge
3. Update all indexes (`_index.md`, `_glossary.md`, `_recent.md`)
4. Update the answer file: set `filed_to_wiki: true` and add a link to the destination article

This way explorations and queries always "add up" in the knowledge base.
