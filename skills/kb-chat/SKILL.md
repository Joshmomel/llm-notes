---
name: kb-chat
version: 0.1.0
description: |
  Run a multi-turn knowledge-base chat. Keep the full transcript in
  outputs/sessions/, continue follow-up questions inside the same
  session, and promote stable synthesis back into outputs/answers/
  and the wiki when reusable conclusions emerge.
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
trigger: /kb-chat
---

# /kb-chat — Session-Based KB Chat

Use this when the user wants an ongoing conversation against the knowledge base and expects follow-up questions to accumulate instead of being treated as isolated one-off `/kb-qa` runs.

## Usage

- `/kb-chat How do these papers relate to each other?`
- `/kb-chat Compare the architecture tradeoffs here, then stay in session for follow-ups`
- `/kb-chat Let's reason through this codebase and keep the conversation filed back into the KB`

## Workflow

### Step 1: Detect KB Root

Find the nearest directory containing `wiki/`. If not found, tell the user to run `/kb-init` first.

### Step 2: Find Or Create The Active Chat Session

Prefer a single active transcript note per ongoing thread:

1. Check for an existing active session:

```bash
python3 -m llm_notes.chat list --kb-root <kb-root> --status active --limit 1
```

2. If there is no suitable active session, create one:

```bash
python3 -m llm_notes.chat start \
  --kb-root <kb-root> \
  --title "<short session title>" \
  --focus "<what this multi-turn discussion is trying to learn>"
```

3. Append the current user message to the session transcript before researching:

```bash
python3 -m llm_notes.chat append \
  --kb-root <kb-root> \
  --session <session rel_path or session_id> \
  --speaker user \
  --content-stdin <<'EOF'
<raw user message>
EOF
```

### Step 3: Research The KB

Use the same navigation discipline as `/kb-qa`:

1. Read `wiki/_index.md`
2. Read relevant category `_index.md` files
3. Use `/kb-search` only when the question is broad, ambiguous, or cross-cutting
4. Read the strongest 3-10 candidate articles
5. Extend the local knowledge network through `[[wikilinks]]`, sibling pages, contrasts, and prerequisites
6. Read KB-root source files directly when wiki coverage is insufficient
7. Track gaps, contradictions, and follow-up threads that arise during the session

### Step 4: Answer In-Session

Reply conversationally, but keep KB discipline:

- Ground claims in the articles you actually read
- Use inline `[[wikilinks]]` citations when referring to wiki pages
- Surface contradictions, gaps, and next questions
- For substantive turns, prefer the same four-section structure as `/kb-qa`:
  - `## Main Conclusion`
  - `## Knowledge Network Extension`
  - `## Deep-Dive Threads`
  - `## Further Questions`

### Step 5: Append The Assistant Turn

After you draft the reply, append it to the same session transcript:

```bash
python3 -m llm_notes.chat append \
  --kb-root <kb-root> \
  --session <session rel_path or session_id> \
  --speaker assistant \
  --source-consulted wiki/category/article.md \
  --source-consulted wiki/category/other-article.md \
  --content-stdin <<'EOF'
<assistant reply shown to the user>
EOF
```

### Step 6: Promote Stable Synthesis

When the session reaches a durable conclusion, comparison, taxonomy, or reusable concept link:

1. Save and auto-file a synthesized answer note:

```bash
python3 -m llm_notes.answers finalize \
  --kb-root <kb-root> \
  --question "<stable question distilled from the session>" \
  --source-consulted wiki/category/article.md \
  --source-consulted wiki/category/other-article.md \
  --mode auto \
  --body-stdin <<'EOF'
# <Distilled Question>

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

2. Register the generated answer note and any filed wiki targets back onto the session:

```bash
python3 -m llm_notes.chat link-answer \
  --kb-root <kb-root> \
  --session <session rel_path or session_id> \
  --answer outputs/answers/YYYY-MM-DD-slug.md \
  --filed-wikilink category/article
```

Promote when the insight is reusable. Do not promote transient chatter or purely operational turns.

### Step 7: Close The Session

When the user explicitly finishes the topic, close the session:

```bash
python3 -m llm_notes.chat close \
  --kb-root <kb-root> \
  --session <session rel_path or session_id> \
  --status closed
```

The goal is:
- `outputs/sessions/` keeps the auditable transcript
- `outputs/answers/` keeps distilled synthesis notes
- `wiki/` receives only stable, reusable knowledge
