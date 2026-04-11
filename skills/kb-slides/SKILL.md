---
name: kb-slides
version: 0.1.0
description: |
  Generate Marp slide decks from wiki content. Reads wiki articles,
  synthesizes key points into presentation format, and saves to outputs/slides/.
  Viewable in Obsidian with the Marp plugin.
allowed-tools:
  - Read
  - Write
  - Edit
  - Glob
  - Grep
trigger: /kb-slides
---

# /kb-slides — Generate Slide Decks

Generate Marp-format slide decks from wiki content.

## Usage

- `/kb-slides "Introduction to Transformers"` — generate slides on a topic
- `/kb-slides wiki/ai/attention.md` — generate slides from a specific article
- `/kb-slides` — ask user what topic to present

## Workflow

### Step 1: Detect KB Root

Find the nearest directory containing `wiki/`. If not found, tell the user to run `/kb-init` first.

### Step 2: Research Topic

1. Read `wiki/_index.md` to find relevant categories
2. Read relevant articles (same navigation protocol as `/kb-qa`)
3. Gather key points, data, and relationships

### Step 3: Generate Slide Deck

Create a Marp-format markdown file at `outputs/slides/YYYY-MM-DD-slug.md`:

```markdown
---
marp: true
theme: default
paginate: true
---

# Slide Title

Subtitle or context

---

## Key Point 1

- Bullet points
- Keep slides concise
- One idea per slide

---

## Key Point 2

Content with `[[wikilinks]]` to source articles

---

## Summary

- Recap of main points
- Links to wiki articles for deeper reading

---

## Sources

- [[category/article]] — what it contributed
```

### Guidelines

- **One idea per slide** — keep content concise
- **5-15 slides** typical range
- **Use `---`** to separate slides (Marp format)
- **Include source citations** as `[[wikilinks]]` on the final slide
- **Images:** use `![](path)` (standard markdown, not wikilinks — Marp requires this)
- Viewable in Obsidian with the Marp Slides plugin, or export via `marp` CLI

### Step 4: Report

Print:
- Path to generated slide deck
- Number of slides
- Source articles used
