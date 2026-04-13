"""Deterministic candidate generation for semantic KB health checks."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from itertools import combinations
from pathlib import Path
from typing import Any

from llm_notes.answers import list_answers
from llm_notes.compile import find_kb_root
from llm_notes.wiki import Article, list_articles

SEMANTIC_JSON_RELATIVE_PATH = Path("outputs") / "lint-semantic-candidates.json"
SEMANTIC_MD_RELATIVE_PATH = Path("outputs") / "lint-semantic-candidates.md"

WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
CONFLICT_CUE_PAIRS = [
    ("prefer", "avoid"),
    ("recommended", "not recommended"),
    ("faster", "slower"),
    ("better", "worse"),
    ("increase", "decrease"),
    ("cheaper", "expensive"),
    ("efficient", "inefficient"),
    ("stable", "fragile"),
]


def semantic_json_path(kb_root: str | Path) -> Path:
    return Path(kb_root) / SEMANTIC_JSON_RELATIVE_PATH


def semantic_md_path(kb_root: str | Path) -> Path:
    return Path(kb_root) / SEMANTIC_MD_RELATIVE_PATH


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


def _section_key(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


def _split_sections(body: str) -> dict[str, str]:
    matches = list(SECTION_RE.finditer(body))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        sections[_section_key(match.group(1))] = body[start:end].strip()
    return sections


def _normalize_wikilink(raw: str) -> str:
    target = raw.strip()
    if "|" in target:
        target = target.split("|", 1)[0]
    if "#" in target:
        target = target.split("#", 1)[0]
    return target.strip()


def _extract_wikilinks(text: str) -> list[str]:
    links: list[str] = []
    for raw in WIKILINK_RE.findall(text):
        normalized = _normalize_wikilink(raw)
        if normalized:
            links.append(normalized)
    return links


def _bulletize(text: str) -> list[str]:
    items: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("- ", "* ")):
            items.append(stripped[2:].strip())
        else:
            items.append(stripped)
    return items


def _preview(text: str, limit: int = 320) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


def _token_set(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"\b\w+\b", text.lower(), flags=re.UNICODE)
        if len(token) >= 4
    }


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    overlap = left & right
    universe = left | right
    return len(overlap) / max(len(universe), 1)


def _normalize_title(title: str) -> str:
    normalized = re.sub(r"[^\w\s-]", "", title.lower()).strip()
    return re.sub(r"[-\s]+", " ", normalized)


def _severity_for_issue(kind: str, score: float) -> str:
    if kind in {"duplicate_concept_candidate", "merge_candidate", "conflict_candidate"}:
        return "warning" if score >= 0.55 else "info"
    if kind in {"split_candidate", "missing_data_candidate", "web_imputation_candidate"}:
        return "warning" if score >= 0.7 else "info"
    if kind in {"pending_answer_synthesis", "connection_candidate", "inconsistency_hotspot"}:
        return "warning" if score >= 0.6 else "info"
    return "info"


def _make_issue(
    *,
    kind: str,
    score: float,
    reason: str,
    target_wikilinks: list[str],
    suggested_action: str,
    severity: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    normalized_targets = sorted(set(target_wikilinks))
    digest = hashlib.sha1(
        f"{kind}|{'|'.join(normalized_targets)}|{suggested_action}".encode("utf-8")
    ).hexdigest()[:10]
    payload = {
        "issue_id": f"{kind}:{digest}",
        "kind": kind,
        "severity": severity or _severity_for_issue(kind, score),
        "score": round(min(max(score, 0.0), 1.0), 2),
        "reason": reason,
        "target_wikilinks": normalized_targets,
        "suggested_action": suggested_action,
    }
    payload.update(extra)
    return payload


def _article_snapshot(article: Article) -> dict[str, Any]:
    sections = _split_sections(article.body)
    summary = sections.get("summary", "")
    related = sections.get("related", "")
    open_questions = sections.get("open questions", "")
    outgoing_links = sorted(set(_extract_wikilinks(article.body)))
    return {
        "wikilink": article.wikilink,
        "title": article.title,
        "category": article.category,
        "tags": list(article.metadata.get("tags", [])),
        "sources": list(article.metadata.get("sources", [])),
        "derived_from_outputs": list(article.metadata.get("derived_from_outputs", []))
        if isinstance(article.metadata.get("derived_from_outputs"), list)
        else [],
        "outgoing_links": outgoing_links,
        "related_links": sorted(set(_extract_wikilinks(related))),
        "open_questions": _bulletize(open_questions),
        "summary_text": summary.strip(),
        "body_preview": _preview(article.body),
        "body_length": len(article.body),
        "title_key": _normalize_title(article.title),
        "body_tokens": sorted(_token_set(article.body)),
    }


def _pair_key(left: dict[str, Any], right: dict[str, Any]) -> tuple[str, str]:
    return tuple(sorted((left["wikilink"], right["wikilink"])))


def _inconsistency_candidates(snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for left, right in combinations(snapshots, 2):
        shared_tags = sorted(set(left["tags"]) & set(right["tags"]))
        shared_sources = sorted(set(left["sources"]) & set(right["sources"]))
        same_category = bool(left["category"] and left["category"] == right["category"])
        derived_overlap = bool(set(left["derived_from_outputs"]) & set(right["derived_from_outputs"]))
        if not (shared_tags or shared_sources or same_category or derived_overlap):
            continue

        score = 0.0
        reasons: list[str] = []
        if shared_tags:
            score += min(0.45, 0.15 * len(shared_tags))
            reasons.append(f"shared tags: {', '.join(shared_tags)}")
        if shared_sources:
            score += min(0.45, 0.20 * len(shared_sources))
            reasons.append(f"shared sources: {', '.join(shared_sources)}")
        if same_category:
            score += 0.15
            reasons.append("same category")
        if derived_overlap:
            score += 0.10
            reasons.append("shared derived outputs")

        candidates.append(
            _make_issue(
                kind="inconsistency_hotspot",
                score=score,
                reason="; ".join(reasons),
                target_wikilinks=[left["wikilink"], right["wikilink"]],
                suggested_action="review_conflict",
                left=left["wikilink"],
                right=right["wikilink"],
                shared_tags=shared_tags,
                shared_sources=shared_sources,
                same_category=same_category,
            )
        )

    return sorted(candidates, key=lambda item: (-item["score"], item["issue_id"]))[:15]


def _connection_candidates(snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for left, right in combinations(snapshots, 2):
        if right["wikilink"] in left["outgoing_links"] or left["wikilink"] in right["outgoing_links"]:
            continue
        shared_tags = sorted(set(left["tags"]) & set(right["tags"]))
        shared_sources = sorted(set(left["sources"]) & set(right["sources"]))
        if not (shared_tags or shared_sources):
            continue

        score = 0.0
        reasons: list[str] = []
        if shared_tags:
            score += min(0.60, 0.20 * len(shared_tags))
            reasons.append(f"shared tags: {', '.join(shared_tags)}")
        if shared_sources:
            score += min(0.60, 0.30 * len(shared_sources))
            reasons.append(f"shared sources: {', '.join(shared_sources)}")

        candidates.append(
            _make_issue(
                kind="connection_candidate",
                score=score,
                reason="; ".join(reasons),
                target_wikilinks=[left["wikilink"], right["wikilink"]],
                suggested_action="add_link",
                left=left["wikilink"],
                right=right["wikilink"],
                shared_tags=shared_tags,
                shared_sources=shared_sources,
            )
        )

    return sorted(candidates, key=lambda item: (-item["score"], item["issue_id"]))[:15]


def _duplicate_overlap_candidates(snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for left, right in combinations(snapshots, 2):
        shared_tags = sorted(set(left["tags"]) & set(right["tags"]))
        shared_sources = sorted(set(left["sources"]) & set(right["sources"]))
        shared_links = sorted(set(left["outgoing_links"]) & set(right["outgoing_links"]))
        title_match = left["title_key"] == right["title_key"]
        preview_overlap = _jaccard(set(left["body_tokens"]), set(right["body_tokens"]))
        same_category = bool(left["category"] and left["category"] == right["category"])

        score = 0.0
        reasons: list[str] = []
        if title_match:
            score += 0.35
            reasons.append("normalized titles match closely")
        if shared_sources:
            score += min(0.35, 0.18 * len(shared_sources))
            reasons.append(f"shared sources: {', '.join(shared_sources)}")
        if shared_tags:
            score += min(0.20, 0.08 * len(shared_tags))
            reasons.append(f"shared tags: {', '.join(shared_tags)}")
        if preview_overlap >= 0.25:
            score += min(0.25, preview_overlap)
            reasons.append(f"body overlap: {preview_overlap:.2f}")
        if shared_links:
            score += min(0.10, 0.05 * len(shared_links))
            reasons.append("overlapping related links")
        if same_category:
            score += 0.10
            reasons.append("same category")

        if score < 0.45:
            continue

        kind = "duplicate_concept_candidate" if title_match or (shared_sources and preview_overlap >= 0.25) else "merge_candidate"
        candidates.append(
            _make_issue(
                kind=kind,
                score=score,
                reason="; ".join(reasons),
                target_wikilinks=[left["wikilink"], right["wikilink"]],
                suggested_action="merge_articles",
                left=left["wikilink"],
                right=right["wikilink"],
                shared_tags=shared_tags,
                shared_sources=shared_sources,
                shared_links=shared_links,
                preview_overlap=round(preview_overlap, 2),
            )
        )

    return sorted(candidates, key=lambda item: (-item["score"], item["issue_id"]))[:15]


def _split_candidates(snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for snapshot in snapshots:
        score = 0.0
        reasons: list[str] = []
        if len(snapshot["tags"]) >= 4:
            score += 0.20
            reasons.append("many tags suggest multiple themes")
        if len(snapshot["sources"]) >= 4:
            score += 0.20
            reasons.append("many sources accumulated into one page")
        if len(snapshot["outgoing_links"]) >= 6:
            score += 0.15
            reasons.append("many outgoing links suggest broad scope")
        if len(snapshot["open_questions"]) >= 4:
            score += 0.20
            reasons.append("many open questions suggest unresolved subtopics")
        if snapshot["body_length"] >= 1600:
            score += 0.20
            reasons.append("long body may contain multiple article-sized sections")
        if " and " in snapshot["title_key"]:
            score += 0.10
            reasons.append("title combines multiple concepts")

        if score < 0.55:
            continue

        candidates.append(
            _make_issue(
                kind="split_candidate",
                score=score,
                reason="; ".join(reasons),
                target_wikilinks=[snapshot["wikilink"]],
                suggested_action="split_article",
                article=snapshot["wikilink"],
                source_count=len(snapshot["sources"]),
                tag_count=len(snapshot["tags"]),
                open_question_count=len(snapshot["open_questions"]),
            )
        )
    return sorted(candidates, key=lambda item: (-item["score"], item["issue_id"]))[:15]


def _cue_hits(text: str) -> set[str]:
    lowered = text.lower()
    hits: set[str] = set()
    for left, right in CONFLICT_CUE_PAIRS:
        if left in lowered:
            hits.add(left)
        if right in lowered:
            hits.add(right)
    return hits


def _conflict_candidates(snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for left, right in combinations(snapshots, 2):
        shared_tags = sorted(set(left["tags"]) & set(right["tags"]))
        shared_sources = sorted(set(left["sources"]) & set(right["sources"]))
        same_category = bool(left["category"] and left["category"] == right["category"])
        preview_overlap = _jaccard(set(left["body_tokens"]), set(right["body_tokens"]))

        if not (shared_tags or shared_sources or same_category or preview_overlap >= 0.18):
            continue

        left_text = f"{left['summary_text']} {left['body_preview']}".strip()
        right_text = f"{right['summary_text']} {right['body_preview']}".strip()
        left_hits = _cue_hits(left_text)
        right_hits = _cue_hits(right_text)

        matched_pairs: list[str] = []
        for positive, negative in CONFLICT_CUE_PAIRS:
            if (positive in left_hits and negative in right_hits) or (negative in left_hits and positive in right_hits):
                matched_pairs.append(f"{positive} vs {negative}")

        if not matched_pairs:
            continue

        score = 0.25
        reasons: list[str] = [f"opposing cues: {', '.join(matched_pairs)}"]
        if shared_tags:
            score += min(0.20, 0.08 * len(shared_tags))
            reasons.append(f"shared tags: {', '.join(shared_tags)}")
        if shared_sources:
            score += min(0.25, 0.12 * len(shared_sources))
            reasons.append(f"shared sources: {', '.join(shared_sources)}")
        if same_category:
            score += 0.10
            reasons.append("same category")
        if preview_overlap >= 0.18:
            score += min(0.20, preview_overlap)
            reasons.append(f"body overlap: {preview_overlap:.2f}")

        candidates.append(
            _make_issue(
                kind="conflict_candidate",
                score=score,
                reason="; ".join(reasons),
                target_wikilinks=[left["wikilink"], right["wikilink"]],
                suggested_action="review_conflict",
                left=left["wikilink"],
                right=right["wikilink"],
                shared_tags=shared_tags,
                shared_sources=shared_sources,
                cue_pairs=matched_pairs,
            )
        )

    return sorted(candidates, key=lambda item: (-item["score"], item["issue_id"]))[:15]


def _web_lookup_needed(question: str) -> bool:
    lowered = question.lower()
    triggers = (
        "missing",
        "unknown",
        "unclear",
        "benchmark",
        "date",
        "version",
        "citation",
        "evidence",
        "coverage",
        "compare",
    )
    return any(token in lowered for token in triggers)


def _missing_data_candidates(snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for snapshot in snapshots:
        if not snapshot["open_questions"]:
            continue
        score = min(1.0, 0.25 + 0.15 * len(snapshot["open_questions"]))
        candidates.append(
            _make_issue(
                kind="missing_data_candidate",
                score=score,
                reason="open questions section contains unresolved prompts",
                target_wikilinks=[snapshot["wikilink"]],
                suggested_action="research_gap",
                article=snapshot["wikilink"],
                questions=snapshot["open_questions"][:6],
            )
        )
    return sorted(candidates, key=lambda item: (-item["score"], item["issue_id"]))[:15]


def _imputation_candidates(snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for snapshot in snapshots:
        for question in snapshot["open_questions"]:
            if not _web_lookup_needed(question):
                continue
            candidates.append(
                _make_issue(
                    kind="web_imputation_candidate",
                    score=0.7,
                    reason="open question likely requires external verification or missing factual lookup",
                    target_wikilinks=[snapshot["wikilink"]],
                    suggested_action="research_gap",
                    article=snapshot["wikilink"],
                    prompt=question,
                )
            )
    return candidates[:15]


def _pending_answer_candidates(kb_root: Path) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for answer in list_answers(kb_root):
        if answer.filed_to_wiki:
            continue
        if len(answer.sources_consulted) < 2:
            continue
        candidates.append(
            _make_issue(
                kind="pending_answer_synthesis",
                score=0.6,
                reason="pending multi-source answer may contain reusable synthesis",
                target_wikilinks=answer.promotion_targets,
                suggested_action="promote_answer",
                answer=answer.rel_path,
                question=answer.question,
                candidate_targets=answer.promotion_targets,
            )
        )
    return candidates[:15]


def _flatten_candidate_groups(groups: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for values in groups.values():
        issues.extend(values)
    return sorted(
        issues,
        key=lambda item: (
            {"critical": 0, "warning": 1, "info": 2}.get(item["severity"], 3),
            -item["score"],
            item["issue_id"],
        ),
    )


def build_semantic_candidates(kb_root: str | Path) -> dict[str, Any]:
    root = Path(kb_root).resolve()
    articles = list_articles(root)
    snapshots = [_article_snapshot(article) for article in articles]

    candidate_groups = {
        "duplicate_candidates": _duplicate_overlap_candidates(snapshots),
        "split_candidates": _split_candidates(snapshots),
        "conflict_candidates": _conflict_candidates(snapshots),
        "inconsistency_hotspots": _inconsistency_candidates(snapshots),
        "connection_candidates": _connection_candidates(snapshots),
        "missing_data_candidates": _missing_data_candidates(snapshots),
        "web_imputation_candidates": _imputation_candidates(snapshots),
        "pending_answer_synthesis": _pending_answer_candidates(root),
    }

    payload = {
        "summary": {
            "total_articles": len(snapshots),
            "with_open_questions": sum(1 for snapshot in snapshots if snapshot["open_questions"]),
            "with_tags": sum(1 for snapshot in snapshots if snapshot["tags"]),
        },
        "articles": snapshots,
        "candidates": candidate_groups,
        "issues": _flatten_candidate_groups(candidate_groups),
    }
    return payload


def render_semantic_candidates_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    candidates = payload["candidates"]
    lines = [
        "# Semantic Lint Candidates",
        "",
        "This file is a deterministic shortlist for semantic KB health checks.",
        "Use it to drive Claude/Codex review for contradictions, missing data, connection discovery, and web-backed imputation.",
        "",
        "## Summary",
        "",
        f"- Total articles: {summary['total_articles']}",
        f"- Articles with open questions: {summary['with_open_questions']}",
        f"- Articles with tags: {summary['with_tags']}",
        "",
        "## Duplicate / Merge Candidates",
        "",
    ]

    duplicate_candidates = candidates["duplicate_candidates"]
    if duplicate_candidates:
        for item in duplicate_candidates:
            lines.append(
                f"- `{item['target_wikilinks'][0]}` vs `{item['target_wikilinks'][1]}` — "
                f"{item['kind']} — score {item['score']:.2f} — {item['reason']}"
            )
    else:
        lines.append("- None.")

    lines.extend(["", "## Split Candidates", ""])
    split_candidates = candidates["split_candidates"]
    if split_candidates:
        for item in split_candidates:
            lines.append(f"- `{item['target_wikilinks'][0]}` — score {item['score']:.2f} — {item['reason']}")
    else:
        lines.append("- None.")

    lines.extend(["", "## Conflict Candidates", ""])
    conflict_candidates = candidates["conflict_candidates"]
    if conflict_candidates:
        for item in conflict_candidates:
            lines.append(
                f"- `{item['target_wikilinks'][0]}` vs `{item['target_wikilinks'][1]}` — "
                f"score {item['score']:.2f} — {item['reason']}"
            )
    else:
        lines.append("- None.")

    lines.extend(["", "## Inconsistency Hotspots", ""])
    hotspots = candidates["inconsistency_hotspots"]
    if hotspots:
        for item in hotspots:
            lines.append(
                f"- `{item['target_wikilinks'][0]}` vs `{item['target_wikilinks'][1]}` — "
                f"score {item['score']:.2f} — {item['reason']}"
            )
    else:
        lines.append("- None.")

    lines.extend(["", "## Connection Candidates", ""])
    connections = candidates["connection_candidates"]
    if connections:
        for item in connections:
            lines.append(
                f"- `{item['target_wikilinks'][0]}` <-> `{item['target_wikilinks'][1]}` — "
                f"score {item['score']:.2f} — {item['reason']}"
            )
    else:
        lines.append("- None.")

    lines.extend(["", "## Missing Data Candidates", ""])
    missing = candidates["missing_data_candidates"]
    if missing:
        for item in missing:
            lines.append(f"- `{item['article']}` — score {item['score']:.2f}")
            for question in item["questions"]:
                lines.append(f"  - {question}")
    else:
        lines.append("- None.")

    lines.extend(["", "## Web Imputation Candidates", ""])
    imputation = candidates["web_imputation_candidates"]
    if imputation:
        for item in imputation:
            lines.append(f"- `{item['article']}` — {item['prompt']}")
    else:
        lines.append("- None.")

    lines.extend(["", "## Pending Answer Synthesis", ""])
    pending = candidates["pending_answer_synthesis"]
    if pending:
        for item in pending:
            lines.append(f"- `{item['answer']}` — {item['question']}")
    else:
        lines.append("- None.")

    lines.extend(
        [
            "",
            "## Agent Instructions",
            "",
            "- Review duplicate/merge candidates first to eliminate overlapping articles before deep semantic cleanup.",
            "- Review conflict candidates before assuming two similar articles can be merged safely.",
            "- Review the top inconsistency hotspots and cite the exact conflicting claims if any.",
            "- For split candidates, decide whether one article should become several narrower pages.",
            "- For connection candidates, decide whether the wiki should add mutual wikilinks or a new synthesis article.",
            "- For missing data candidates, confirm whether the gap is real, then recommend compile targets or follow-up questions.",
            "- Use web search only for explicit imputation candidates or when the wiki/source corpus clearly lacks a needed fact.",
        ]
    )
    lines.append("")
    return "\n".join(lines)


def write_semantic_candidates(kb_root: str | Path) -> dict[str, Any]:
    root = Path(kb_root).resolve()
    payload = build_semantic_candidates(root)

    json_path = semantic_json_path(root)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    md_path = semantic_md_path(root)
    md_path.write_text(render_semantic_candidates_markdown(payload), encoding="utf-8")

    return {
        "json_path": str(json_path),
        "json_rel_path": json_path.relative_to(root).as_posix(),
        "md_path": str(md_path),
        "md_rel_path": md_path.relative_to(root).as_posix(),
        "summary": payload["summary"],
        "candidate_counts": {key: len(value) for key, value in payload["candidates"].items()},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="llm-notes semantic lint helpers")
    parser.add_argument("--kb-root")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    kb_root = _resolved_kb_root(args.kb_root)
    result = write_semantic_candidates(kb_root)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Semantic candidate JSON: {result['json_path']}")
        print(f"Semantic candidate Markdown: {result['md_path']}")
        for key, value in sorted(result["candidate_counts"].items()):
            print(f"- {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
