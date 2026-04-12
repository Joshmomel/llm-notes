"""Helpers for transcript-backed KB chat sessions."""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from llm_notes.compile import find_kb_root
from llm_notes.wiki import parse_frontmatter, slugify

CHAT_FRONTMATTER_ORDER = (
    "title",
    "created",
    "updated",
    "session_id",
    "status",
    "focus",
    "turn_count",
    "sources_consulted",
    "answers_generated",
    "filed_wikilinks",
    "tags",
)


@dataclass(frozen=True)
class ChatSession:
    path: Path
    rel_path: str
    metadata: dict[str, Any]
    body: str

    @property
    def title(self) -> str:
        value = self.metadata.get("title")
        return str(value).strip() if value else "KB Chat"

    @property
    def session_id(self) -> str:
        value = self.metadata.get("session_id")
        return str(value).strip() if value else self.path.stem

    @property
    def status(self) -> str:
        value = self.metadata.get("status")
        return str(value).strip() if value else "active"

    @property
    def focus(self) -> str:
        value = self.metadata.get("focus")
        return str(value).strip() if value else ""

    @property
    def turn_count(self) -> int:
        return _normalize_int(self.metadata.get("turn_count"))

    @property
    def sources_consulted(self) -> list[str]:
        return _normalize_list(self.metadata.get("sources_consulted"))

    @property
    def answers_generated(self) -> list[str]:
        return _normalize_list(self.metadata.get("answers_generated"))

    @property
    def filed_wikilinks(self) -> list[str]:
        return _normalize_list(self.metadata.get("filed_wikilinks"))


def sessions_root(kb_root: str | Path) -> Path:
    return Path(kb_root) / "outputs" / "sessions"


def _now() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def _normalize_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    return [str(value).strip()]


def _normalize_int(value: Any) -> int:
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def _format_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return '""'
    text = str(value)
    if not text:
        return '""'
    if any(char in text for char in ':#[]{},"\'' ) or text != text.strip():
        return json.dumps(text, ensure_ascii=False)
    return text


def _dump_frontmatter(metadata: dict[str, Any]) -> str:
    ordered_keys = [key for key in CHAT_FRONTMATTER_ORDER if key in metadata]
    ordered_keys.extend(sorted(key for key in metadata if key not in ordered_keys))

    lines = ["---"]
    for key in ordered_keys:
        value = metadata[key]
        if isinstance(value, list):
            if not value:
                lines.append(f"{key}: []")
                continue
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {_format_scalar(item)}")
            continue
        lines.append(f"{key}: {_format_scalar(value)}")
    lines.append("---")
    return "\n".join(lines)


def _serialize_session(metadata: dict[str, Any], body: str) -> str:
    frontmatter = _dump_frontmatter(metadata)
    normalized_body = body.strip()
    if normalized_body:
        return f"{frontmatter}\n\n{normalized_body}\n"
    return f"{frontmatter}\n"


def _relative_to_root(path: str | Path, kb_root: str | Path) -> str:
    return Path(os.path.relpath(Path(path).resolve(), Path(kb_root).resolve())).as_posix()


def _session_filename(created_at: str, title: str, focus: str | None = None) -> str:
    day = created_at.split("T", 1)[0]
    stem = slugify(title or focus or "kb-chat")[:80]
    return f"{day}-{stem}.md"


def _next_available_session_path(kb_root: str | Path, created_at: str, title: str, focus: str | None = None) -> Path:
    root = sessions_root(kb_root)
    root.mkdir(parents=True, exist_ok=True)
    base = root / _session_filename(created_at, title, focus)
    if not base.exists():
        return base

    stem = base.stem
    for index in range(2, 1000):
        candidate = base.with_name(f"{stem}-{index}.md")
        if not candidate.exists():
            return candidate
    raise RuntimeError("Could not allocate a unique chat session path.")


def _default_session_body(title: str, focus: str) -> str:
    focus_text = focus or "Track a multi-turn KB conversation here."
    return (
        f"# {title}\n\n"
        "## Focus\n\n"
        f"{focus_text}\n\n"
        "## Transcript\n\n"
        "## Session Outputs\n\n"
        "- Run `python3 -m llm_notes.answers finalize ...` when a stable synthesis emerges.\n\n"
        "## Emerging Insights\n\n"
        "- Capture durable takeaways worth filing back into the wiki.\n\n"
        "## Follow-up Questions\n\n"
        "- Keep unresolved investigation threads here.\n"
    )


def create_chat_session(
    kb_root: str | Path,
    *,
    title: str,
    focus: str | None = None,
    created_at: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Path:
    root = Path(kb_root).resolve()
    created = created_at or _now()
    target = _next_available_session_path(root, created, title, focus)
    session_id = target.stem
    payload = {
        "title": title,
        "created": created,
        "updated": created,
        "session_id": session_id,
        "status": "active",
        "focus": focus or "",
        "turn_count": 0,
        "sources_consulted": [],
        "answers_generated": [],
        "filed_wikilinks": [],
        "tags": [],
    }
    if metadata:
        payload.update(metadata)
    target.write_text(_serialize_session(payload, _default_session_body(title, focus or "")), encoding="utf-8")
    return target


def _resolve_session_path(kb_root: str | Path, reference: str | Path) -> Path:
    root = Path(kb_root).resolve()
    ref = Path(reference)
    candidates: list[Path] = []

    if ref.is_absolute():
        candidates.append(ref)
    else:
        candidates.append(root / ref)
        candidates.append(sessions_root(root) / ref)
        if ref.suffix != ".md":
            candidates.append((root / ref).with_suffix(".md"))
            candidates.append((sessions_root(root) / ref).with_suffix(".md"))

    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.exists():
            return resolved

    raise RuntimeError(f"Chat session not found: {reference}")


def parse_chat_session(path: str | Path, kb_root: str | Path | None = None) -> ChatSession:
    session_path = Path(path).resolve()
    if kb_root is not None:
        rel_path = _relative_to_root(session_path, kb_root)
    else:
        rel_path = session_path.name

    text = session_path.read_text(encoding="utf-8", errors="ignore")
    metadata, body = parse_frontmatter(text)
    normalized = dict(metadata)
    normalized["turn_count"] = _normalize_int(normalized.get("turn_count"))
    normalized["sources_consulted"] = _normalize_list(normalized.get("sources_consulted"))
    normalized["answers_generated"] = _normalize_list(normalized.get("answers_generated"))
    normalized["filed_wikilinks"] = _normalize_list(normalized.get("filed_wikilinks"))
    normalized["tags"] = _normalize_list(normalized.get("tags"))
    return ChatSession(
        path=session_path,
        rel_path=rel_path,
        metadata=normalized,
        body=body,
    )


def list_chat_sessions(kb_root: str | Path, *, status: str | None = None, limit: int | None = None) -> list[ChatSession]:
    root = sessions_root(kb_root)
    if not root.exists():
        return []

    sessions = []
    for path in root.rglob("*.md"):
        if path.is_file():
            session = parse_chat_session(path, kb_root)
            if status and session.status != status:
                continue
            sessions.append(session)

    sessions.sort(key=lambda session: str(session.metadata.get("updated", "")), reverse=True)
    if limit is not None:
        return sessions[:limit]
    return sessions


def _section_bounds(body: str, heading: str) -> tuple[int, int, int] | None:
    pattern = re.compile(rf"^##\s+{re.escape(heading)}\s*$", re.MULTILINE)
    match = pattern.search(body)
    if match is None:
        return None
    next_section = re.compile(r"^##\s+.+$", re.MULTILINE).search(body, match.end())
    end = next_section.start() if next_section else len(body)
    return match.start(), match.end(), end


def _replace_section(body: str, heading: str, content: str) -> str:
    bounds = _section_bounds(body, heading)
    if bounds is None:
        addition = f"\n\n## {heading}\n\n{content.strip()}\n"
        return body.rstrip() + addition
    _, heading_end, section_end = bounds
    return body[:heading_end] + f"\n\n{content.strip()}\n" + body[section_end:]


def _append_transcript_block(body: str, block: str) -> str:
    bounds = _section_bounds(body, "Transcript")
    if bounds is None:
        return body.rstrip() + f"\n\n## Transcript\n\n{block.strip()}\n"

    _, heading_end, section_end = bounds
    existing = body[heading_end:section_end].strip()
    content = f"{existing}\n\n{block.strip()}" if existing else block.strip()
    return body[:heading_end] + f"\n\n{content}\n" + body[section_end:]


def _merge_lists(existing: list[str], incoming: list[str]) -> list[str]:
    merged = list(existing)
    for item in incoming:
        if item and item not in merged:
            merged.append(item)
    return merged


def append_chat_turn(
    kb_root: str | Path,
    *,
    session_path: str | Path,
    speaker: str,
    content: str,
    timestamp: str | None = None,
    sources_consulted: list[str] | None = None,
) -> Path:
    root = Path(kb_root).resolve()
    resolved = _resolve_session_path(root, session_path)
    session = parse_chat_session(resolved, root)

    role = speaker.strip().lower()
    if role not in {"user", "assistant", "system"}:
        raise RuntimeError(f"Unsupported speaker: {speaker}")
    event_time = timestamp or _now()
    transcript_block = f"### {role.title()} ({event_time})\n\n{content.strip()}"
    metadata = dict(session.metadata)
    metadata["updated"] = event_time
    metadata["turn_count"] = session.turn_count + 1
    metadata["sources_consulted"] = _merge_lists(
        session.sources_consulted,
        _normalize_list(sources_consulted),
    )
    updated_body = _append_transcript_block(session.body, transcript_block)
    resolved.write_text(_serialize_session(metadata, updated_body), encoding="utf-8")
    return resolved


def register_chat_artifacts(
    kb_root: str | Path,
    *,
    session_path: str | Path,
    answer_paths: list[str] | None = None,
    filed_wikilinks: list[str] | None = None,
    updated_at: str | None = None,
) -> Path:
    root = Path(kb_root).resolve()
    resolved = _resolve_session_path(root, session_path)
    session = parse_chat_session(resolved, root)

    normalized_answers: list[str] = []
    for answer in _normalize_list(answer_paths):
        answer_path = Path(answer)
        if not answer_path.is_absolute():
            candidate = root / answer_path
            normalized_answers.append(_relative_to_root(candidate, root) if candidate.exists() else answer_path.as_posix())
        else:
            normalized_answers.append(_relative_to_root(answer_path, root))

    wikilinks = _normalize_list(filed_wikilinks)
    metadata = dict(session.metadata)
    metadata["updated"] = updated_at or _now()
    metadata["answers_generated"] = _merge_lists(session.answers_generated, normalized_answers)
    metadata["filed_wikilinks"] = _merge_lists(session.filed_wikilinks, wikilinks)

    output_items = [f"Answer note: `{path}`" for path in normalized_answers]
    output_items.extend(f"Filed to wiki: [[{wikilink}]]" for wikilink in wikilinks)
    section_items = _merge_lists(_section_bullets(session.body, "Session Outputs"), output_items)
    updated_body = _replace_section(session.body, "Session Outputs", "\n".join(f"- {item}" for item in section_items))
    resolved.write_text(_serialize_session(metadata, updated_body), encoding="utf-8")
    return resolved


def close_chat_session(
    kb_root: str | Path,
    *,
    session_path: str | Path,
    status: str = "closed",
    updated_at: str | None = None,
) -> Path:
    root = Path(kb_root).resolve()
    resolved = _resolve_session_path(root, session_path)
    session = parse_chat_session(resolved, root)
    metadata = dict(session.metadata)
    metadata["status"] = status
    metadata["updated"] = updated_at or _now()
    resolved.write_text(_serialize_session(metadata, session.body), encoding="utf-8")
    return resolved


def _section_bullets(body: str, heading: str) -> list[str]:
    bounds = _section_bounds(body, heading)
    if bounds is None:
        return []
    _, heading_end, section_end = bounds
    lines = body[heading_end:section_end].splitlines()
    items: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("- "):
            items.append(stripped[2:].strip())
    return items


def _resolved_kb_root(kb_root: str | Path | None) -> Path:
    if kb_root is not None:
        root = Path(kb_root).resolve()
    else:
        detected = find_kb_root(".")
        if detected is None:
            raise RuntimeError("No knowledge base root found. Run /kb-init first or pass --kb-root.")
        root = detected
    if not (root / "wiki").is_dir():
        raise RuntimeError(f"{root} is not a knowledge base root. Missing wiki/ directory.")
    return root


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="llm-notes chat session helpers")
    subparsers = parser.add_subparsers(dest="command", required=True)

    start_parser = subparsers.add_parser("start", help="create a transcript-backed KB chat session")
    start_parser.add_argument("--kb-root")
    start_parser.add_argument("--title", required=True)
    start_parser.add_argument("--focus")
    start_parser.add_argument("--created")
    start_parser.add_argument("--metadata-json")

    append_parser = subparsers.add_parser("append", help="append a user or assistant turn to a chat session")
    append_parser.add_argument("--kb-root")
    append_parser.add_argument("--session", required=True)
    append_parser.add_argument("--speaker", choices=("user", "assistant", "system"), required=True)
    append_parser.add_argument("--timestamp")
    append_parser.add_argument("--source-consulted", action="append", default=[])
    append_body = append_parser.add_mutually_exclusive_group(required=True)
    append_body.add_argument("--content-file")
    append_body.add_argument("--content-stdin", action="store_true")

    link_parser = subparsers.add_parser("link-answer", help="register answer notes and filed wiki targets on a chat session")
    link_parser.add_argument("--kb-root")
    link_parser.add_argument("--session", required=True)
    link_parser.add_argument("--answer", action="append", default=[])
    link_parser.add_argument("--filed-wikilink", action="append", default=[])
    link_parser.add_argument("--updated")

    close_parser = subparsers.add_parser("close", help="close or archive a chat session")
    close_parser.add_argument("--kb-root")
    close_parser.add_argument("--session", required=True)
    close_parser.add_argument("--status", choices=("closed", "archived", "active"), default="closed")
    close_parser.add_argument("--updated")

    list_parser = subparsers.add_parser("list", help="list chat sessions")
    list_parser.add_argument("--kb-root")
    list_parser.add_argument("--status", choices=("active", "closed", "archived"))
    list_parser.add_argument("--limit", type=int)

    args = parser.parse_args(argv)
    kb_root = _resolved_kb_root(getattr(args, "kb_root", None))

    if args.command == "start":
        metadata = json.loads(args.metadata_json) if args.metadata_json else None
        session_path = create_chat_session(
            kb_root,
            title=args.title,
            focus=args.focus,
            created_at=args.created,
            metadata=metadata,
        )
        session = parse_chat_session(session_path, kb_root)
        print(
            json.dumps(
                {
                    "path": str(session.path),
                    "rel_path": session.rel_path,
                    "session_id": session.session_id,
                    "status": session.status,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "append":
        if args.content_file:
            content = Path(args.content_file).read_text(encoding="utf-8")
        else:
            import sys

            content = sys.stdin.read()
        session_path = append_chat_turn(
            kb_root,
            session_path=args.session,
            speaker=args.speaker,
            content=content,
            timestamp=args.timestamp,
            sources_consulted=args.source_consulted,
        )
        session = parse_chat_session(session_path, kb_root)
        print(
            json.dumps(
                {
                    "path": str(session.path),
                    "rel_path": session.rel_path,
                    "turn_count": session.turn_count,
                    "updated": session.metadata.get("updated"),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "link-answer":
        session_path = register_chat_artifacts(
            kb_root,
            session_path=args.session,
            answer_paths=args.answer,
            filed_wikilinks=args.filed_wikilink,
            updated_at=args.updated,
        )
        session = parse_chat_session(session_path, kb_root)
        print(
            json.dumps(
                {
                    "path": str(session.path),
                    "rel_path": session.rel_path,
                    "answers_generated": session.answers_generated,
                    "filed_wikilinks": session.filed_wikilinks,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "close":
        session_path = close_chat_session(
            kb_root,
            session_path=args.session,
            status=args.status,
            updated_at=args.updated,
        )
        session = parse_chat_session(session_path, kb_root)
        print(
            json.dumps(
                {
                    "path": str(session.path),
                    "rel_path": session.rel_path,
                    "status": session.status,
                    "updated": session.metadata.get("updated"),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "list":
        sessions = list_chat_sessions(kb_root, status=args.status, limit=args.limit)
        print(
            json.dumps(
                [
                    {
                        "path": str(session.path),
                        "rel_path": session.rel_path,
                        "session_id": session.session_id,
                        "title": session.title,
                        "status": session.status,
                        "updated": session.metadata.get("updated"),
                        "turn_count": session.turn_count,
                    }
                    for session in sessions
                ],
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
