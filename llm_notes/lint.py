"""Lint helpers for llm-notes knowledge bases."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from llm_notes.answers import (
    assess_answer_for_filing,
    filing_recommendation_for_answer,
    list_answers,
    resolve_answer_sources,
)
from llm_notes.compile import discover_sources, find_kb_root, sync_kb_indexes
from llm_notes.semantic_lint import build_semantic_candidates
from llm_notes.wiki import article_inventory, list_articles, load_recent_entries

LINT_REPORT_RELATIVE_PATH = Path("outputs") / "lint-report.md"


@dataclass(frozen=True)
class LintIssue:
    severity: str
    category: str
    message: str


@dataclass(frozen=True)
class LintStats:
    total_articles: int
    total_sources: int
    unprocessed_sources: int
    last_updated: str
    total_answers: int
    filed_answers: int
    pending_answers: int
    high_value_pending_answers: int
    semantic_hotspots: int


def lint_report_path(kb_root: str | Path) -> Path:
    return Path(kb_root) / LINT_REPORT_RELATIVE_PATH


def _today() -> str:
    return date.today().isoformat()


def _last_updated(kb_root: str | Path) -> str:
    entries = load_recent_entries(kb_root)
    for entry in entries:
        if entry[:10].count("-") == 2:
            return entry[:10]
    return "unknown"


def _issue_counts(issues: list[LintIssue]) -> dict[str, int]:
    counts = {"critical": 0, "warning": 0, "info": 0}
    for issue in issues:
        counts[issue.severity] = counts.get(issue.severity, 0) + 1
    return counts


def _render_issue_block(issues: list[LintIssue], severity: str, title: str) -> list[str]:
    lines = [f"### {title}", ""]
    filtered = [issue for issue in issues if issue.severity == severity]
    if not filtered:
        lines.append("- None.")
        lines.append("")
        return lines

    for issue in filtered:
        lines.append(f"- **{issue.category}** — {issue.message}")
    lines.append("")
    return lines


def _suggested_explorations(kb_root: str | Path, pending_queue: list[dict[str, Any]]) -> list[str]:
    suggestions: list[str] = []
    for item in pending_queue[:5]:
        answer = item["answer"]
        assessment = item["assessment"]
        suggestion = f"{answer.question} — {assessment.action} `{answer.rel_path}`"
        if assessment.candidate_article:
            suggestion += f" (candidate: `{assessment.candidate_article}`)"
        suggestions.append(suggestion)

    if not suggestions:
        suggestions.append("Ask a cross-article question and let `/kb-qa` file the reusable synthesis back into the wiki.")
    return suggestions


def _health_score(
    *,
    unprocessed_sources: int,
    high_value_pending_answers: int,
    missing_filed_targets: int,
    unresolved_provenance: int,
    semantic_hotspots: int,
) -> int:
    score = 10.0
    if unprocessed_sources:
        score -= min(2.0, 0.5 * unprocessed_sources)
    if high_value_pending_answers:
        score -= min(3.0, 0.75 * high_value_pending_answers)
    if missing_filed_targets:
        score -= min(2.0, 1.0 * missing_filed_targets)
    if unresolved_provenance:
        score -= min(1.0, 0.5 * unresolved_provenance)
    if semantic_hotspots:
        score -= min(1.5, 0.25 * semantic_hotspots)
    return max(0, int(round(score)))


def run_lint(kb_root: str | Path, *, fix: bool = False) -> dict[str, Any]:
    root = Path(kb_root).resolve()
    articles = list_articles(root)
    sources = discover_sources(root)
    inventory = article_inventory(root)
    covered_sources = set(inventory["by_source"])
    uncovered_sources = [source.rel_path for source in sources if source.rel_path not in covered_sources]

    answers = list_answers(root)
    existing_wikilinks = {article.wikilink for article in articles}

    issues: list[LintIssue] = []
    pending_queue: list[dict[str, Any]] = []
    unresolved_provenance = 0
    missing_filed_targets = 0

    for rel_path in uncovered_sources:
        issues.append(LintIssue("warning", "uncovered source", f"`{rel_path}` is not referenced by any wiki article"))

    for answer in answers:
        assessment = assess_answer_for_filing(answer)
        resolved_sources = resolve_answer_sources(root, answer)

        if answer.filed_to_wiki:
            missing = [wikilink for wikilink in answer.filed_wikilinks if wikilink not in existing_wikilinks]
            if missing:
                missing_filed_targets += 1
                issues.append(
                    LintIssue(
                        "warning",
                        "filed answer target missing",
                        f"`{answer.rel_path}` points to missing wiki target(s): {', '.join(f'`{item}`' for item in missing)}",
                    )
                )
            continue

        if answer.sources_consulted and not resolved_sources:
            unresolved_provenance += 1
            issues.append(
                LintIssue(
                    "info",
                    "answer provenance unresolved",
                    f"`{answer.rel_path}` could not resolve canonical sources from its consulted references",
                )
            )

        if assessment.should_file:
            pending_queue.append(
                {
                    "answer": answer,
                    "assessment": assessment,
                    "recommendation": filing_recommendation_for_answer(answer, assessment=assessment),
                }
            )
            issues.append(
                LintIssue(
                    "warning",
                    "pending answer worth filing",
                    f"`{answer.rel_path}` scored {assessment.score:.2f} for `{assessment.action}` ({'; '.join(assessment.reasons)})",
                )
            )
        else:
            issues.append(
                LintIssue(
                    "info",
                    "pending answer",
                    f"`{answer.rel_path}` is still pending filing",
                )
            )

    auto_fixed: list[str] = []
    if fix:
        written = sync_kb_indexes(root)
        if written:
            auto_fixed.append(f"Regenerated {len(written)} wiki index file(s)")

    semantic_payload = build_semantic_candidates(root)
    semantic_queue = [
        issue
        for issue in semantic_payload["issues"]
        if issue["severity"] in {"warning", "critical"}
    ][:10]

    stats = LintStats(
        total_articles=len(articles),
        total_sources=len(sources),
        unprocessed_sources=len(uncovered_sources),
        last_updated=_last_updated(root),
        total_answers=len(answers),
        filed_answers=sum(1 for answer in answers if answer.filed_to_wiki),
        pending_answers=sum(1 for answer in answers if not answer.filed_to_wiki),
        high_value_pending_answers=len(pending_queue),
        semantic_hotspots=len(semantic_queue),
    )
    health_score = _health_score(
        unprocessed_sources=stats.unprocessed_sources,
        high_value_pending_answers=stats.high_value_pending_answers,
        missing_filed_targets=missing_filed_targets,
        unresolved_provenance=unresolved_provenance,
        semantic_hotspots=stats.semantic_hotspots,
    )

    payload = {
        "stats": stats,
        "health_score": health_score,
        "issues": issues,
        "issue_counts": _issue_counts(issues),
        "auto_fixed": auto_fixed,
        "pending_queue": pending_queue,
        "semantic_queue": semantic_queue,
        "semantic_candidate_counts": {key: len(value) for key, value in semantic_payload["candidates"].items()},
        "suggested_explorations": _suggested_explorations(root, pending_queue),
    }
    return payload


def render_report(kb_root: str | Path, result: dict[str, Any]) -> str:
    stats: LintStats = result["stats"]
    issues: list[LintIssue] = result["issues"]
    pending_queue: list[dict[str, Any]] = result["pending_queue"]
    semantic_queue: list[dict[str, Any]] = result["semantic_queue"]

    lines = [
        "---",
        f"date: {_today()}",
        "---",
        "",
        "# KB Health Report",
        "",
        "## Stats",
        "",
        f"- Total articles: {stats.total_articles}",
        f"- Total sources: {stats.total_sources}",
        f"- Unprocessed sources: {stats.unprocessed_sources}",
        f"- Last updated: {stats.last_updated}",
        f"- Total answers: {stats.total_answers}",
        f"- Filed answers: {stats.filed_answers}",
        f"- Pending answers: {stats.pending_answers}",
        f"- High-value pending answers: {stats.high_value_pending_answers}",
        f"- Semantic hotspots: {stats.semantic_hotspots}",
        "",
        f"## Health Score: {result['health_score']}/10",
        "",
        "## Issues Found",
        "",
    ]

    lines.extend(_render_issue_block(issues, "critical", "Critical"))
    lines.extend(_render_issue_block(issues, "warning", "Warning"))
    lines.extend(_render_issue_block(issues, "info", "Info"))

    lines.extend(["## Answer Filing Queue", ""])
    if pending_queue:
        for item in pending_queue:
            answer = item["answer"]
            assessment = item["assessment"]
            recommendation = item["recommendation"]
            lines.append(
                f"- `{answer.rel_path}` — score {assessment.score:.2f} — recommend `{assessment.action}` — {answer.question}"
            )
            lines.append(f"  Reasons: {'; '.join(assessment.reasons)}")
            if assessment.candidate_article:
                lines.append(f"  Candidate target: `{assessment.candidate_article}`")
            lines.append(f"  Command: `{recommendation['command']}`")
    else:
        lines.append("- No high-value pending answers.")
    lines.append("")

    lines.extend(["## Semantic Hotspots", ""])
    if semantic_queue:
        for issue in semantic_queue:
            targets = ", ".join(f"`{target}`" for target in issue["target_wikilinks"]) or "-"
            lines.append(
                f"- `{issue['kind']}` — score {issue['score']:.2f} — action `{issue['suggested_action']}` — {targets}"
            )
            lines.append(f"  Reason: {issue['reason']}")
    else:
        lines.append("- No high-priority semantic hotspots.")
    lines.append("")

    lines.extend(["## Auto-fixed", ""])
    if result["auto_fixed"]:
        for item in result["auto_fixed"]:
            lines.append(f"- {item}")
    else:
        lines.append("- None.")
    lines.append("")

    lines.extend(["## Suggested Explorations", ""])
    for suggestion in result["suggested_explorations"]:
        lines.append(f"- {suggestion}")
    lines.append("")
    return "\n".join(lines)


def write_report(kb_root: str | Path, *, fix: bool = False) -> dict[str, Any]:
    root = Path(kb_root).resolve()
    result = run_lint(root, fix=fix)
    report_path = lint_report_path(root)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(root, result), encoding="utf-8")
    return {
        "path": str(report_path),
        "rel_path": report_path.relative_to(root).as_posix(),
        "health_score": result["health_score"],
        "issue_counts": result["issue_counts"],
        "stats": {
            "total_articles": result["stats"].total_articles,
            "total_sources": result["stats"].total_sources,
            "unprocessed_sources": result["stats"].unprocessed_sources,
            "last_updated": result["stats"].last_updated,
            "total_answers": result["stats"].total_answers,
            "filed_answers": result["stats"].filed_answers,
            "pending_answers": result["stats"].pending_answers,
            "high_value_pending_answers": result["stats"].high_value_pending_answers,
            "semantic_hotspots": result["stats"].semantic_hotspots,
        },
        "pending_queue": [
            item["recommendation"]
            for item in result["pending_queue"]
        ],
        "semantic_queue": result["semantic_queue"],
        "semantic_candidate_counts": result["semantic_candidate_counts"],
        "suggested_explorations": result["suggested_explorations"],
        "auto_fixed": result["auto_fixed"],
    }


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
    parser = argparse.ArgumentParser(description="llm-notes lint helpers")
    parser.add_argument("--kb-root")
    parser.add_argument("--fix", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    kb_root = _resolved_kb_root(args.kb_root)
    result = write_report(kb_root, fix=args.fix)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Health score: {result['health_score']}/10")
        counts = result["issue_counts"]
        print(
            f"Issues: {counts.get('critical', 0)} critical, "
            f"{counts.get('warning', 0)} warning, {counts.get('info', 0)} info"
        )
        for suggestion in result["suggested_explorations"][:3]:
            print(f"- {suggestion}")
        if result["auto_fixed"]:
            print("Auto-fixed:")
            for item in result["auto_fixed"]:
                print(f"- {item}")
        print(f"Report: {result['path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
