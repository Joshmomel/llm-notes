---
name: kb-ingest
version: 0.1.0
description: |
  Import external material into a knowledge base. Supports a single `add`
  entrypoint that can ingest a URL, a local file, or pasted stdin text into
  an imports/ area with provenance.
allowed-tools:
  - Bash
  - Read
  - Write
trigger: /kb-ingest
---

# /kb-ingest — Import External Material

Use this when the user wants to bring new material into an existing KB before compiling it.

## Usage

- `/kb-ingest https://example.com/article`
- `/kb-ingest /path/to/local/file.pdf`
- `pbpaste | /kb-ingest --title "Copied note"`

## Workflow

1. Detect the KB root (`wiki/` must already exist).
2. Prefer the unified deterministic helper:

```bash
python3 -m llm_notes.ingest add --kb-root <kb-root> --json "<input>"
```

The helper auto-detects:
- URL input -> fetch into `imports/web/`
- local file path -> copy into `imports/files/`
- stdin with no input -> save into `imports/text/`

3. Use explicit modes only when auto-detection would be ambiguous:

### URL import

```bash
python3 -m llm_notes.ingest add --kb-root <kb-root> --mode url --json "<url>"
```

This writes a markdown source file into `imports/web/` with provenance frontmatter.

### File import

```bash
python3 -m llm_notes.ingest add --kb-root <kb-root> --mode file --json "<local-file-path>"
```

This copies the file into `imports/files/` and writes a `.import.json` provenance sidecar.

### Stdin import

```bash
pbpaste | python3 -m llm_notes.ingest add --kb-root <kb-root> --mode stdin --title "Copied note"
```

This writes a markdown file into `imports/text/`, optionally with `--source-url`.

4. Tell the user where the import landed.
5. After a successful import, decide whether to continue into compile:
   - If the user explicitly asked to import **and compile**, continue directly into `/kb-compile`.
   - If the user explicitly said import-only, stop after reporting the import result.
   - Otherwise, in Claude Code / Codex chat, ask a short follow-up question:
     - `Imported into <path>. Do you want me to run /kb-compile now?`

The point is:
- importing should stay safe and reversible
- compiling is the natural next step, but it should usually be user-confirmed in the interactive assistant flow
