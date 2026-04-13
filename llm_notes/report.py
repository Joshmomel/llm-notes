"""Generate a KB dashboard report as Markdown."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from llm_notes.chat import list_chat_sessions
from llm_notes.compile import find_kb_root
from llm_notes.lint import run_lint
from llm_notes.wiki import list_articles

REPORT_RELATIVE_PATH = Path("outputs") / "KB_REPORT.md"


def report_path(kb_root: str | Path) -> Path:
    return Path(kb_root) / REPORT_RELATIVE_PATH


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


def _main_areas(articles: list[Any], limit: int = 5) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for article in articles:
        label = article.category or "_root"
        counts[label] += 1
    items = []
    for category, count in counts.most_common(limit):
        items.append(
            {
                "category": category,
                "label": "Root" if category == "_root" else category,
                "article_count": count,
            }
        )
    return items


def _pending_filing_summary(lint_payload: dict[str, Any], limit: int = 5) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for entry in lint_payload.get("pending_queue", [])[:limit]:
        recommendation = entry.get("recommendation") if isinstance(entry, dict) else None
        if isinstance(recommendation, dict):
            items.append(recommendation)
    return items


def _semantic_hotspot_summary(lint_payload: dict[str, Any], limit: int = 5) -> list[dict[str, Any]]:
    return list(lint_payload.get("semantic_queue", []))[:limit]


def _active_session_summary(kb_root: str | Path, limit: int = 5) -> list[dict[str, Any]]:
    sessions = list_chat_sessions(kb_root, status="active", limit=limit)
    items: list[dict[str, Any]] = []
    for session in sessions:
        promotion_lines = [
            item
            for item in _section_bullets(session.body, "Promotion Queue")
            if item != "No pending promotions."
        ]
        items.append(
            {
                "rel_path": session.rel_path,
                "title": session.title,
                "focus": session.focus,
                "turn_count": session.turn_count,
                "pending_promotions": len(promotion_lines),
            }
        )
    return items


def _section_bullets(body: str, heading: str) -> list[str]:
    import re

    pattern = re.compile(rf"^##\s+{re.escape(heading)}\s*$", re.MULTILINE)
    match = pattern.search(body)
    if match is None:
        return []
    next_section = re.compile(r"^##\s+.+$", re.MULTILINE).search(body, match.end())
    end = next_section.start() if next_section else len(body)
    lines = body[match.end():end].splitlines()
    items: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("- "):
            items.append(stripped[2:].strip())
    return items


def _next_actions(lint_payload: dict[str, Any], active_sessions: list[dict[str, Any]]) -> list[str]:
    actions: list[str] = []
    pending_queue = _pending_filing_summary(lint_payload, limit=5)
    semantic_queue = lint_payload.get("semantic_queue", [])
    stats = lint_payload["stats"]

    if pending_queue:
        top = pending_queue[0]
        actions.append(
            f"Run the top filing recommendation for `{top['answer_rel_path']}` ({top['action']})."
        )
    if semantic_queue:
        top = semantic_queue[0]
        targets = ", ".join(top["target_wikilinks"]) or "the top semantic issue"
        actions.append(f"Review semantic hotspot `{top['kind']}` affecting {targets}.")
    if stats.unprocessed_sources:
        actions.append(f"Compile {stats.unprocessed_sources} uncovered source file(s) into the wiki.")
    if active_sessions:
        actions.append(f"Continue or close the most active session: `{active_sessions[0]['rel_path']}`.")
    if not actions:
        actions.append("The KB is in a steady state. Add new sources or ask a new cross-cutting question.")
    return actions[:5]


def build_report_payload(kb_root: str | Path) -> dict[str, Any]:
    root = Path(kb_root).resolve()
    articles = list_articles(root)
    lint_payload = run_lint(root)
    active_sessions = _active_session_summary(root)

    return {
        "kb_root": str(root),
        "snapshot": {
            "articles": lint_payload["stats"].total_articles,
            "sources": lint_payload["stats"].total_sources,
            "unprocessed_sources": lint_payload["stats"].unprocessed_sources,
            "answers_total": lint_payload["stats"].total_answers,
            "answers_filed": lint_payload["stats"].filed_answers,
            "answers_pending": lint_payload["stats"].pending_answers,
            "active_sessions": len(active_sessions),
            "health_score": lint_payload["health_score"],
            "semantic_hotspots": lint_payload["stats"].semantic_hotspots,
        },
        "main_areas": _main_areas(articles),
        "pending_filing": _pending_filing_summary(lint_payload),
        "semantic_hotspots": _semantic_hotspot_summary(lint_payload),
        "active_sessions": active_sessions,
        "next_actions": _next_actions(lint_payload, active_sessions),
    }


def render_report_markdown(payload: dict[str, Any]) -> str:
    snapshot = payload["snapshot"]
    lines = [
        "# KB Report",
        "",
        f"Root: `{payload['kb_root']}`",
        "",
        "## Snapshot",
        "",
        f"- Articles: {snapshot['articles']}",
        f"- Sources: {snapshot['sources']}",
        f"- Unprocessed sources: {snapshot['unprocessed_sources']}",
        f"- Answers: {snapshot['answers_total']} total / {snapshot['answers_filed']} filed / {snapshot['answers_pending']} pending",
        f"- Active sessions: {snapshot['active_sessions']}",
        f"- Health score: {snapshot['health_score']}/10",
        f"- Semantic hotspots: {snapshot['semantic_hotspots']}",
        "",
        "## Main Areas",
        "",
    ]

    if payload["main_areas"]:
        for item in payload["main_areas"]:
            lines.append(f"- `{item['label']}` — {item['article_count']} article(s)")
    else:
        lines.append("- No compiled wiki areas yet.")

    lines.extend(["", "## Pending Filing", ""])
    if payload["pending_filing"]:
        for item in payload["pending_filing"]:
            lines.append(f"- `{item['action']}` — `{item['answer_rel_path']}`")
            if item.get("candidate_article"):
                lines.append(f"  - target: `{item['candidate_article']}`")
            lines.append(f"  - score: {item['score']:.2f}")
            lines.append(f"  - cmd: `{item['command']}`")
    else:
        lines.append("- No pending filing recommendations.")

    lines.extend(["", "## Semantic Hotspots", ""])
    if payload["semantic_hotspots"]:
        for item in payload["semantic_hotspots"]:
            targets = ", ".join(f"`{target}`" for target in item["target_wikilinks"]) or "-"
            lines.append(f"- `{item['kind']}` — action `{item['suggested_action']}` — {targets}")
            lines.append(f"  - score: {item['score']:.2f}")
            lines.append(f"  - reason: {item['reason']}")
    else:
        lines.append("- No high-priority semantic hotspots.")

    lines.extend(["", "## Active Sessions", ""])
    if payload["active_sessions"]:
        for item in payload["active_sessions"]:
            lines.append(f"- `{item['rel_path']}`")
            if item["focus"]:
                lines.append(f"  - focus: {item['focus']}")
            lines.append(f"  - turns: {item['turn_count']}")
            lines.append(f"  - pending promotions: {item['pending_promotions']}")
    else:
        lines.append("- No active transcript-backed sessions.")

    lines.extend(["", "## Next Actions", ""])
    for action in payload["next_actions"]:
        lines.append(f"- {action}")
    lines.append("")
    return "\n".join(lines)


def write_report(kb_root: str | Path) -> dict[str, Any]:
    root = Path(kb_root).resolve()
    payload = build_report_payload(root)
    target = report_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_report_markdown(payload), encoding="utf-8")
    return {
        "path": str(target),
        "rel_path": target.relative_to(root).as_posix(),
        **payload,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="llm-notes KB dashboard report")
    parser.add_argument("--kb-root")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    kb_root = _resolved_kb_root(args.kb_root)
    result = write_report(kb_root)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"KB report: {result['path']}")
        print(f"Health score: {result['snapshot']['health_score']}/10")
        for action in result["next_actions"][:3]:
            print(f"- {action}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
