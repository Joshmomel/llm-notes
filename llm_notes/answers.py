"""Helpers for saving KB answers and filing them back into the wiki."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from llm_notes.compile import find_kb_root, write_compiled_article
from llm_notes.wiki import parse_frontmatter, read_article, slugify

ANSWER_FRONTMATTER_ORDER = (
    "title",
    "date",
    "question",
    "retrieval_mode",
    "retrieval_trace",
    "sources_consulted",
    "filing_status",
    "filed_to_wiki",
    "filed_wikilinks",
    "filed_at",
    "promotion_score",
    "promotion_reason",
    "promotion_mode",
    "promotion_targets",
)

SECTION_ALIASES = {
    "main_conclusion": {"main conclusion", "核心结论", "主要结论"},
    "knowledge_network_extension": {"knowledge network extension", "知识网络扩展", "知识网络延展"},
    "deep_dive_threads": {"deep-dive threads", "deep dive threads", "深挖线索", "深度追踪"},
    "further_questions": {"further questions", "后续问题", "进一步问题"},
    "sources_consulted": {"sources consulted", "查阅来源", "参考来源"},
    "gaps_identified": {"gaps identified", "识别出的缺口", "知识缺口"},
}


@dataclass(frozen=True)
class AnswerNote:
    path: Path
    rel_path: str
    metadata: dict[str, Any]
    body: str
    sections: dict[str, str]

    @property
    def title(self) -> str:
        value = self.metadata.get("title")
        return str(value).strip() if value else "Answer"

    @property
    def question(self) -> str:
        value = self.metadata.get("question")
        return str(value).strip() if value else self.title

    @property
    def note_date(self) -> str:
        value = self.metadata.get("date")
        return str(value).strip() if value else date.today().isoformat()

    @property
    def sources_consulted(self) -> list[str]:
        value = self.metadata.get("sources_consulted")
        return _normalize_list(value)

    @property
    def retrieval_mode(self) -> str:
        value = self.metadata.get("retrieval_mode")
        return str(value).strip() if value else ""

    @property
    def retrieval_trace(self) -> list[str]:
        return _normalize_list(self.metadata.get("retrieval_trace"))

    @property
    def filed_to_wiki(self) -> bool:
        return _normalize_bool(self.metadata.get("filed_to_wiki"))

    @property
    def filing_status(self) -> str:
        value = self.metadata.get("filing_status")
        return str(value).strip() if value else "pending"

    @property
    def filed_wikilinks(self) -> list[str]:
        return _normalize_list(self.metadata.get("filed_wikilinks"))

    @property
    def promotion_mode(self) -> str:
        value = self.metadata.get("promotion_mode")
        return str(value).strip() if value else ""

    @property
    def promotion_targets(self) -> list[str]:
        return _normalize_list(self.metadata.get("promotion_targets"))

    @property
    def promotion_score(self) -> float | None:
        return _normalize_float(self.metadata.get("promotion_score"))


@dataclass(frozen=True)
class FilingAssessment:
    score: float
    action: str
    should_file: bool
    reasons: list[str]
    candidate_article: str | None = None


def answers_root(kb_root: str | Path) -> Path:
    return Path(kb_root) / "outputs" / "answers"


def _today() -> str:
    return date.today().isoformat()


def _normalize_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    return [str(value).strip()]


def _normalize_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _normalize_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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
    ordered_keys = [key for key in ANSWER_FRONTMATTER_ORDER if key in metadata]
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


def _serialize_answer(metadata: dict[str, Any], body: str) -> str:
    frontmatter = _dump_frontmatter(metadata)
    normalized_body = body.strip()
    if normalized_body:
        return f"{frontmatter}\n\n{normalized_body}\n"
    return f"{frontmatter}\n"


def _relative_to_root(path: str | Path, kb_root: str | Path) -> str:
    return Path(os.path.relpath(Path(path).resolve(), Path(kb_root).resolve())).as_posix()


def _section_key(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


def _split_sections(body: str) -> dict[str, str]:
    pattern = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
    matches = list(pattern.finditer(body))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        sections[_section_key(match.group(1))] = body[start:end].strip()
    return sections


def _canonical_section(sections: dict[str, str], canonical: str) -> str:
    aliases = SECTION_ALIASES.get(canonical, {canonical})
    for alias in aliases:
        content = sections.get(_section_key(alias))
        if content:
            return content
    return ""


def _question_slug(question: str) -> str:
    return slugify(question)[:80] or "answer"


def _answer_filename(answer_date: str, question: str) -> str:
    return f"{answer_date}-{_question_slug(question)}.md"


def _next_available_answer_path(kb_root: str | Path, answer_date: str, question: str) -> Path:
    root = answers_root(kb_root)
    root.mkdir(parents=True, exist_ok=True)
    base = root / _answer_filename(answer_date, question)
    if not base.exists():
        return base

    stem = base.stem
    for index in range(2, 1000):
        candidate = base.with_name(f"{stem}-{index}.md")
        if not candidate.exists():
            return candidate
    raise RuntimeError("Could not allocate a unique answer path.")


def save_answer(
    kb_root: str | Path,
    *,
    question: str,
    body: str,
    title: str | None = None,
    answer_date: str | None = None,
    sources_consulted: list[str] | None = None,
    retrieval_mode: str | None = None,
    retrieval_trace: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> Path:
    root = Path(kb_root).resolve()
    note_date = answer_date or _today()
    target = _next_available_answer_path(root, note_date, question)
    payload = {
        "title": title or f"Answer: {question}",
        "date": note_date,
        "question": question,
        "retrieval_mode": retrieval_mode or "",
        "retrieval_trace": sorted(set(_normalize_list(retrieval_trace))),
        "sources_consulted": sorted(set(_normalize_list(sources_consulted))),
        "filing_status": "pending",
        "filed_to_wiki": False,
        "filed_wikilinks": [],
    }
    if metadata:
        payload.update(metadata)
    target.write_text(_serialize_answer(payload, body), encoding="utf-8")
    return target


def parse_answer(path: str | Path, kb_root: str | Path | None = None) -> AnswerNote:
    note_path = Path(path).resolve()
    if kb_root is not None:
        rel_path = _relative_to_root(note_path, kb_root)
    else:
        rel_path = note_path.name

    text = note_path.read_text(encoding="utf-8", errors="ignore")
    metadata, body = parse_frontmatter(text)
    normalized = dict(metadata)
    normalized["sources_consulted"] = _normalize_list(normalized.get("sources_consulted"))
    normalized["retrieval_trace"] = _normalize_list(normalized.get("retrieval_trace"))
    normalized["filed_wikilinks"] = _normalize_list(normalized.get("filed_wikilinks"))
    normalized["promotion_targets"] = _normalize_list(normalized.get("promotion_targets"))
    normalized["filed_to_wiki"] = _normalize_bool(normalized.get("filed_to_wiki"))
    normalized["promotion_score"] = _normalize_float(normalized.get("promotion_score"))
    normalized["retrieval_mode"] = str(normalized.get("retrieval_mode") or "").strip()
    normalized["filing_status"] = str(normalized.get("filing_status") or "pending").strip()
    return AnswerNote(
        path=note_path,
        rel_path=rel_path,
        metadata=normalized,
        body=body,
        sections=_split_sections(body),
    )


def list_answers(kb_root: str | Path) -> list[AnswerNote]:
    root = answers_root(kb_root)
    if not root.exists():
        return []

    notes = []
    for path in sorted(root.rglob("*.md")):
        if path.is_file():
            notes.append(parse_answer(path, kb_root))
    return notes


def assess_answer_for_filing(answer: AnswerNote) -> FilingAssessment:
    if answer.filed_to_wiki:
        return FilingAssessment(
            score=1.0,
            action="already_filed",
            should_file=False,
            reasons=["already filed"],
            candidate_article=answer.filed_wikilinks[0] if answer.filed_wikilinks else None,
        )

    score = 0.0
    reasons: list[str] = []

    if answer.promotion_score is not None:
        score = max(score, answer.promotion_score)
        reasons.append(f"metadata promotion_score={answer.promotion_score:.2f}")

    if len(answer.sources_consulted) >= 2:
        score += 0.35
        reasons.append("multi-source synthesis")

    main = _canonical_section(answer.sections, "main_conclusion")
    if len(main) >= 160:
        score += 0.20
        reasons.append("substantive main conclusion")

    related_count = len(_bulletize(_canonical_section(answer.sections, "knowledge_network_extension")))
    if related_count >= 1:
        score += 0.15
        reasons.append("captures related concepts")

    open_count = len(_bulletize(_canonical_section(answer.sections, "deep_dive_threads")))
    open_count += len(_bulletize(_canonical_section(answer.sections, "further_questions")))
    open_count += len(_bulletize(_canonical_section(answer.sections, "gaps_identified")))
    if open_count >= 2:
        score += 0.15
        reasons.append("captures follow-up investigation")

    if answer.promotion_targets:
        score += 0.15
        reasons.append("has destination candidate")

    final_score = min(round(score, 2), 1.0)
    candidate_article = _auto_article_reference(answer)
    if answer.promotion_mode == "enrich" and candidate_article:
        action = "enrich"
        reasons.append("explicit promotion_mode=enrich")
    elif answer.promotion_mode == "new":
        action = "new"
        reasons.append("explicit promotion_mode=new")
    elif final_score >= 0.55:
        action = "enrich" if candidate_article else "new"
        reasons.append(
            "has destination candidate" if candidate_article else "high-value synthesis without destination candidate"
        )
    else:
        action = "pending"

    should_file = final_score >= 0.55 or answer.promotion_mode in {"enrich", "new"}

    return FilingAssessment(
        score=final_score,
        action=action,
        should_file=should_file,
        reasons=reasons or ["no strong filing signals"],
        candidate_article=candidate_article,
    )


def filing_recommendation_for_answer(
    answer: AnswerNote,
    *,
    assessment: FilingAssessment | None = None,
) -> dict[str, Any] | None:
    effective_assessment = assessment or assess_answer_for_filing(answer)
    if not effective_assessment.should_file or effective_assessment.action not in {"new", "enrich"}:
        return None

    args = [
        "python3",
        "-m",
        "llm_notes.answers",
        "file",
        "--kb-root",
        ".",
        "--answer",
        answer.rel_path,
    ]
    if effective_assessment.action == "enrich":
        args.extend(["--mode", "enrich"])
        if effective_assessment.candidate_article:
            args.extend(["--article", effective_assessment.candidate_article])
    else:
        args.extend(["--mode", "new", "--title", answer.title])

    return {
        "answer_rel_path": answer.rel_path,
        "question": answer.question,
        "score": effective_assessment.score,
        "action": effective_assessment.action,
        "candidate_article": effective_assessment.candidate_article,
        "reasons": effective_assessment.reasons,
        "command_args": args,
        "command": " ".join(shlex.quote(arg) for arg in args),
    }


def _resolve_existing_path(kb_root: Path, reference: str) -> Path | None:
    ref = Path(reference)
    candidates: list[Path] = []
    if ref.is_absolute():
        candidates.append(ref)
    else:
        candidates.append(kb_root / ref)
        if not reference.startswith("wiki/"):
            candidates.append(kb_root / "wiki" / ref)
        if ref.suffix != ".md":
            candidates.append((kb_root / ref).with_suffix(".md"))
            if not reference.startswith("wiki/"):
                candidates.append((kb_root / "wiki" / ref).with_suffix(".md"))

    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.exists():
            return resolved
    return None


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _article_wikilink(path: str | Path, kb_root: str | Path) -> str:
    article = Path(path).resolve()
    return article.relative_to((Path(kb_root) / "wiki").resolve()).as_posix().removesuffix(".md")


def resolve_answer_sources(kb_root: str | Path, answer: AnswerNote) -> list[str]:
    root = Path(kb_root).resolve()
    wiki_root = root / "wiki"
    resolved: set[str] = set()

    for reference in answer.sources_consulted:
        target = _resolve_existing_path(root, reference)
        if target is None:
            continue
        if _is_within(target, wiki_root):
            article = read_article(target, root)
            resolved.update(_normalize_list(article.metadata.get("sources")))
            continue
        if _is_within(target, root):
            rel_path = _relative_to_root(target, root)
            if not rel_path.startswith("outputs/") and not rel_path.startswith("wiki/"):
                resolved.add(rel_path)

    return sorted(resolved)


def _first_paragraph(text: str) -> str:
    for block in re.split(r"\n\s*\n", text.strip()):
        stripped = block.strip()
        if stripped:
            return stripped
    return ""


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


def render_answer_article_body(answer: AnswerNote, resolved_sources: list[str]) -> str:
    main = _canonical_section(answer.sections, "main_conclusion")
    related = _canonical_section(answer.sections, "knowledge_network_extension")
    deep_dive = _canonical_section(answer.sections, "deep_dive_threads")
    further = _canonical_section(answer.sections, "further_questions")
    gaps = _canonical_section(answer.sections, "gaps_identified")

    summary = _first_paragraph(main) or f"Filed answer derived from the question: {answer.question}"
    source_lines = resolved_sources or answer.sources_consulted

    lines = ["## Summary", "", summary, "", "## Content", ""]
    lines.append(main or f"Question addressed: {answer.question}")
    lines.extend(["", "## Sources", ""])
    if source_lines:
        for source in source_lines:
            lines.append(f"- `{source}`")
    else:
        lines.append("- No canonical sources could be resolved from this answer.")
    lines.append(f"- Derived insight from `{answer.rel_path}`")

    lines.extend(["", "## Related", ""])
    related_items = _bulletize(related)
    if related_items:
        for item in related_items:
            prefix = item if item.startswith("[[") else f"- {item}"
            lines.append(prefix if prefix.startswith("- ") else f"- {prefix}")
    else:
        lines.append("- No related concepts were captured in the answer.")

    lines.extend(["", "## Open Questions", ""])
    open_items = _bulletize(deep_dive) + _bulletize(further) + _bulletize(gaps)
    if open_items:
        for item in open_items:
            lines.append(f"- {item}")
    else:
        lines.append("- No open questions were captured in the answer.")

    return "\n".join(lines)


def _render_filed_insight(answer: AnswerNote, resolved_sources: list[str]) -> str:
    lines = [f"### Filed Insight ({answer.note_date})", "", f"**Question:** {answer.question}", ""]
    main = _canonical_section(answer.sections, "main_conclusion")
    if main:
        lines.extend(["#### Main Conclusion", "", main, ""])

    related = _canonical_section(answer.sections, "knowledge_network_extension")
    if related:
        lines.extend(["#### Knowledge Network Extension", ""])
        for item in _bulletize(related):
            lines.append(f"- {item}")
        lines.append("")

    deep_dive = _canonical_section(answer.sections, "deep_dive_threads")
    further = _canonical_section(answer.sections, "further_questions")
    gaps = _canonical_section(answer.sections, "gaps_identified")
    open_items = _bulletize(deep_dive) + _bulletize(further) + _bulletize(gaps)
    if open_items:
        lines.extend(["#### Follow-up Threads", ""])
        for item in open_items:
            lines.append(f"- {item}")
        lines.append("")

    source_lines = resolved_sources or answer.sources_consulted
    lines.extend(["#### Provenance", ""])
    for source in source_lines:
        lines.append(f"- `{source}`")
    lines.append(f"- Derived from `{answer.rel_path}`")
    return "\n".join(lines).rstrip()


def _append_filed_insight(existing_body: str, insight_block: str) -> str:
    marker = "## Filed Insights"
    stripped_body = existing_body.rstrip()
    if marker not in stripped_body:
        if stripped_body:
            return f"{stripped_body}\n\n{marker}\n\n{insight_block}"
        return f"{marker}\n\n{insight_block}"
    return f"{stripped_body}\n\n{insight_block}"


def _merge_metadata_list(metadata: dict[str, Any], key: str, value: str) -> list[str]:
    existing = _normalize_list(metadata.get(key))
    return sorted(set(existing + [value]))


def _article_title_from_answer(answer: AnswerNote) -> str:
    title = answer.title
    if title.lower().startswith("answer:"):
        title = title.split(":", 1)[1].strip()
    return title or answer.question


def _auto_article_reference(answer: AnswerNote) -> str | None:
    for reference in answer.promotion_targets:
        if reference:
            return reference
    return None


def mark_answer_filed(
    answer_path: str | Path,
    *,
    kb_root: str | Path,
    filed_wikilinks: list[str],
    filing_status: str = "filed",
) -> Path:
    answer = parse_answer(answer_path, kb_root)
    metadata = dict(answer.metadata)
    metadata["filed_to_wiki"] = True
    metadata["filing_status"] = filing_status
    metadata["filed_at"] = _today()
    metadata["filed_wikilinks"] = sorted(set(answer.filed_wikilinks + filed_wikilinks))
    answer.path.write_text(_serialize_answer(metadata, answer.body), encoding="utf-8")
    return answer.path


def finalize_answer(
    kb_root: str | Path,
    *,
    question: str,
    body: str,
    title: str | None = None,
    answer_date: str | None = None,
    sources_consulted: list[str] | None = None,
    retrieval_mode: str | None = None,
    retrieval_trace: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    auto_file: bool = True,
    file_mode: str = "auto",
    article: str | None = None,
    category: str | None = None,
    slug: str | None = None,
    tags: list[str] | None = None,
    refresh_lint: bool = True,
    refresh_semantic_candidates: bool = False,
) -> dict[str, Any]:
    root = Path(kb_root).resolve()
    answer_path = save_answer(
        root,
        question=question,
        body=body,
        title=title,
        answer_date=answer_date,
        sources_consulted=sources_consulted,
        retrieval_mode=retrieval_mode,
        retrieval_trace=retrieval_trace,
        metadata=metadata,
    )
    answer = parse_answer(answer_path, root)
    assessment = assess_answer_for_filing(answer)

    filing_result: dict[str, Any] | None = None
    should_attempt_file = auto_file and (
        assessment.should_file
        or file_mode != "auto"
        or bool(article)
        or bool(answer.promotion_mode)
        or bool(answer.promotion_targets)
    )
    if should_attempt_file:
        effective_mode = file_mode
        effective_article = article
        if file_mode == "auto" and assessment.action in {"new", "enrich"}:
            effective_mode = assessment.action
            if effective_mode == "enrich" and not effective_article:
                effective_article = assessment.candidate_article
        filing_result = file_answer(
            root,
            answer_path=answer_path,
            mode=effective_mode,
            article=effective_article,
            title=title,
            category=category,
            slug=slug,
            tags=tags,
        )

    lint_result: dict[str, Any] | None = None
    if refresh_lint:
        from llm_notes.lint import write_report

        lint_result = write_report(root)

    semantic_result: dict[str, Any] | None = None
    if refresh_semantic_candidates:
        from llm_notes.semantic_lint import write_semantic_candidates

        semantic_result = write_semantic_candidates(root)

    from llm_notes.report import write_report as write_kb_report

    kb_report = write_kb_report(root)

    final_answer = parse_answer(answer_path, root)
    return {
        "answer_path": str(answer_path),
        "answer_rel_path": final_answer.rel_path,
        "retrieval_mode": final_answer.retrieval_mode,
        "retrieval_trace": final_answer.retrieval_trace,
        "filed_to_wiki": final_answer.filed_to_wiki,
        "filing_status": final_answer.filing_status,
        "filed_wikilinks": final_answer.filed_wikilinks,
        "assessment": {
            "score": assessment.score,
            "action": assessment.action,
            "should_file": assessment.should_file,
            "reasons": assessment.reasons,
            "candidate_article": assessment.candidate_article,
        },
        "filing_result": filing_result,
        "lint_result": lint_result,
        "semantic_result": semantic_result,
        "kb_report": {
            "path": kb_report["path"],
            "rel_path": kb_report["rel_path"],
        },
    }


def file_answer(
    kb_root: str | Path,
    *,
    answer_path: str | Path,
    mode: str = "auto",
    article: str | None = None,
    title: str | None = None,
    category: str | None = None,
    slug: str | None = None,
    tags: list[str] | None = None,
) -> dict[str, str]:
    root = Path(kb_root).resolve()
    answer = parse_answer(answer_path, root)
    resolved_sources = resolve_answer_sources(root, answer)

    target_reference = article or (mode in {"auto", "enrich"} and _auto_article_reference(answer))
    target_article = _resolve_existing_path(root, target_reference) if target_reference else None

    if mode == "enrich" and target_article is None:
        raise RuntimeError("Enrich mode requires an existing --article target or promotion_targets metadata.")

    if target_article is not None:
        existing = read_article(target_article, root)
        derived_from_outputs = _merge_metadata_list(existing.metadata, "derived_from_outputs", answer.rel_path)
        if answer.rel_path in _normalize_list(existing.metadata.get("derived_from_outputs")):
            mark_answer_filed(answer.path, kb_root=root, filed_wikilinks=[existing.wikilink])
            return {
                "answer_path": str(answer.path),
                "article_path": str(existing.path),
                "wikilink": existing.wikilink,
                "status": "already_filed",
            }

        updated_body = _append_filed_insight(existing.body, _render_filed_insight(answer, resolved_sources))
        result = write_compiled_article(
            root,
            title=existing.title,
            body=updated_body,
            category=existing.category,
            slug=existing.slug,
            sources=resolved_sources,
            tags=tags or [],
            created=existing.metadata.get("created"),
            updated=answer.note_date,
            metadata={"derived_from_outputs": derived_from_outputs},
        )
    else:
        effective_title = title or _article_title_from_answer(answer)
        effective_category = category or ""
        result = write_compiled_article(
            root,
            title=effective_title,
            body=render_answer_article_body(answer, resolved_sources),
            category=effective_category,
            slug=slug,
            sources=resolved_sources,
            tags=tags or [],
            created=answer.note_date,
            updated=answer.note_date,
            metadata={"derived_from_outputs": [answer.rel_path]},
        )

    mark_answer_filed(answer.path, kb_root=root, filed_wikilinks=[result["wikilink"]])
    return {
        "answer_path": str(answer.path),
        "article_path": result["path"],
        "wikilink": result["wikilink"],
        "status": result["status"],
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
    parser = argparse.ArgumentParser(description="llm-notes answer helpers")
    subparsers = parser.add_subparsers(dest="command", required=True)

    save_parser = subparsers.add_parser("save", help="save a KB answer into outputs/answers/")
    save_parser.add_argument("--kb-root")
    save_parser.add_argument("--question", required=True)
    save_parser.add_argument("--title")
    save_parser.add_argument("--date")
    save_parser.add_argument("--source-consulted", action="append", default=[])
    save_parser.add_argument("--retrieval-mode")
    save_parser.add_argument("--retrieval-trace", action="append", default=[])
    save_parser.add_argument("--metadata-json")
    save_body = save_parser.add_mutually_exclusive_group(required=True)
    save_body.add_argument("--body-file")
    save_body.add_argument("--body-stdin", action="store_true")

    finalize_parser = subparsers.add_parser(
        "finalize",
        help="save an answer, auto-file reusable synthesis, and refresh lint state",
    )
    finalize_parser.add_argument("--kb-root")
    finalize_parser.add_argument("--question", required=True)
    finalize_parser.add_argument("--title")
    finalize_parser.add_argument("--date")
    finalize_parser.add_argument("--source-consulted", action="append", default=[])
    finalize_parser.add_argument("--retrieval-mode")
    finalize_parser.add_argument("--retrieval-trace", action="append", default=[])
    finalize_parser.add_argument("--metadata-json")
    finalize_parser.add_argument("--mode", choices=("auto", "new", "enrich"), default="auto")
    finalize_parser.add_argument("--article")
    finalize_parser.add_argument("--category")
    finalize_parser.add_argument("--slug")
    finalize_parser.add_argument("--tag", action="append", default=[])
    finalize_parser.add_argument("--no-auto-file", action="store_true")
    finalize_parser.add_argument("--no-refresh-lint", action="store_true")
    finalize_parser.add_argument("--refresh-semantic-candidates", action="store_true")
    finalize_body = finalize_parser.add_mutually_exclusive_group(required=True)
    finalize_body.add_argument("--body-file")
    finalize_body.add_argument("--body-stdin", action="store_true")

    file_parser = subparsers.add_parser("file", help="promote an answer note into the wiki")
    file_parser.add_argument("--kb-root")
    file_parser.add_argument("--answer", required=True)
    file_parser.add_argument("--mode", choices=("auto", "new", "enrich"), default="auto")
    file_parser.add_argument("--article")
    file_parser.add_argument("--title")
    file_parser.add_argument("--category")
    file_parser.add_argument("--slug")
    file_parser.add_argument("--tag", action="append", default=[])

    args = parser.parse_args(argv)
    kb_root = _resolved_kb_root(getattr(args, "kb_root", None))

    if args.command == "save":
        metadata = json.loads(args.metadata_json) if args.metadata_json else None
        if args.body_file:
            body = Path(args.body_file).read_text(encoding="utf-8")
        else:
            import sys

            body = sys.stdin.read()
        output_path = save_answer(
            kb_root,
            question=args.question,
            body=body,
            title=args.title,
            answer_date=args.date,
            sources_consulted=args.source_consulted,
            retrieval_mode=args.retrieval_mode,
            retrieval_trace=args.retrieval_trace,
            metadata=metadata,
        )
        print(
            json.dumps(
                {
                    "path": str(output_path),
                    "rel_path": _relative_to_root(output_path, kb_root),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "finalize":
        metadata = json.loads(args.metadata_json) if args.metadata_json else None
        if args.body_file:
            body = Path(args.body_file).read_text(encoding="utf-8")
        else:
            import sys

            body = sys.stdin.read()
        result = finalize_answer(
            kb_root,
            question=args.question,
            body=body,
            title=args.title,
            answer_date=args.date,
            sources_consulted=args.source_consulted,
            retrieval_mode=args.retrieval_mode,
            retrieval_trace=args.retrieval_trace,
            metadata=metadata,
            auto_file=not args.no_auto_file,
            file_mode=args.mode,
            article=args.article,
            category=args.category,
            slug=args.slug,
            tags=args.tag,
            refresh_lint=not args.no_refresh_lint,
            refresh_semantic_candidates=args.refresh_semantic_candidates,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "file":
        result = file_answer(
            kb_root,
            answer_path=args.answer,
            mode=args.mode,
            article=args.article,
            title=args.title,
            category=args.category,
            slug=args.slug,
            tags=args.tag,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
