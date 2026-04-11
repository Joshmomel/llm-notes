---
name: kb-search
version: 0.1.1
description: |
  Full-text search across the wiki. Uses the packaged `llm_notes.search`
  implementation and installs a thin `wiki/_search.py` wrapper as a stable
  CLI entrypoint. Can be used directly by the user or by the LLM as a retrieval
  primitive for `/kb-qa` and other larger queries.
allowed-tools:
  - Read
  - Bash
  - Glob
  - Grep
trigger: /kb-search
---

# /kb-search — Full-Text Search

Search across the wiki using a lightweight inverted-index search engine.
This is the preferred retrieval accelerator for `/kb-qa` on larger knowledge bases.

## Usage

- `/kb-search "attention mechanism"` — search for a term
- `/kb-search "transformer AND training"` — boolean search

## Workflow

### Step 1: Detect KB Root

Find the nearest directory containing `wiki/`. If not found, tell the user to run `/kb-init` first.

### Step 2: Check Search Index

Check if `wiki/_search.py` exists and whether the index is stale.

- If `wiki/_search.py` is missing, install the stable wrapper by running:
  `python3 -m llm_notes.search install --wiki-dir <kb-root>/wiki`
- Then check whether the index is stale by running:
  `python3 <kb-root>/wiki/_search.py stale`
- If the output is `stale`, rebuild it with:
  `python3 <kb-root>/wiki/_search.py index`

### Step 3: Run Search

```bash
python3 wiki/_search.py search "query terms"
```

The command outputs ranked results with file paths and snippet previews.

### Step 4: Present Results

Show the user:
- Ranked list of matching wiki articles
- Snippet preview for each match
- `[[wikilinks]]` to the articles

If the user wants to dive deeper into a result, read the full article and summarize.

---

## Search Wrapper

`wiki/_search.py` is now a thin, stable wrapper around the packaged
`llm_notes.search` implementation.

It provides:

- **`install` command** via `python3 -m llm_notes.search install --wiki-dir wiki`
- **`stale` command** — checks whether `wiki/_search_index.json` needs a rebuild
- **`index` command** — scans all `.md` files in `wiki/`, builds an inverted index, saves to `wiki/_search_index.json`
- **`search` command** — queries the index, returns ranked results with TF-IDF scoring, boolean operators, and snippet previews

The wrapper is intentionally tiny so the implementation stays versioned in this repository instead of being regenerated ad hoc inside each KB.
