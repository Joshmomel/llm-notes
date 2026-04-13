"""Dual-layer retrieval helpers for wiki and source material.

In auto mode this module returns retrieval suggestions, not hard routing
decisions. The calling LLM can inspect both result sets and decide which layer
to trust for the current question.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from llm_notes.compile import discover_sources, find_kb_root
from llm_notes.search import (
    SearchResult,
    _score_document,
    build_index,
    index_is_stale,
    load_index,
    matching_documents,
    search_index,
    tokenize_text,
)

SOURCE_INDEX_VERSION = 1
SOURCE_INDEX_RELATIVE_PATH = Path("outputs") / "_source_index.json"
MAX_SOURCE_BYTES = 200_000
MAX_CHUNK_LINES = 40
AUTO_SOURCE_ONLY_PATTERNS = (
    re.compile(r"\bwhere\b.+\b(source|code|file)\b", re.IGNORECASE),
    re.compile(r"\bwhich file\b", re.IGNORECASE),
    re.compile(r"\bexact implementation\b", re.IGNORECASE),
    re.compile(r"`[^`]+\.(?:py|ts|js|go|rs|java|md|txt)`"),
    re.compile(r"\b[\w./-]+\.(?:py|ts|js|go|rs|java|md|txt)\b"),
)
AUTO_HYBRID_TERMS = {
    "architecture",
    "class",
    "codebase",
    "compare",
    "data flow",
    "function",
    "how",
    "implementation",
    "module",
    "pattern",
    "tradeoff",
    "why",
}


@dataclass(frozen=True)
class SourceSearchResult:
    path: str
    title: str
    score: float
    snippet: str
    source_path: str
    chunk_id: str
    kind: str
    section: str


@dataclass(frozen=True)
class RetrievalSuggestion:
    mode: str
    reasons: list[str]


def source_index_path(kb_root: str | Path) -> Path:
    return Path(kb_root) / SOURCE_INDEX_RELATIVE_PATH


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _safe_read_source_text(path: Path, kind: str) -> str:
    if kind == "image":
        return ""

    try:
        raw = path.read_bytes()
    except OSError:
        return ""

    if kind == "paper":
        # Paper support stays lightweight in PR2: use filename-only indexing
        # unless the PDF was already converted to text upstream.
        return ""

    return raw[:MAX_SOURCE_BYTES].decode("utf-8", errors="ignore")


def _source_tokens(text: str) -> list[str]:
    tokens = tokenize_text(text)
    expanded: list[str] = []
    for token in tokens:
        expanded.append(token)
        if "_" in token:
            expanded.extend(part for part in token.split("_") if part and part != token)
    return expanded


def _fallback_title(source_path: str) -> str:
    stem = Path(source_path).stem.replace("_", " ").replace("-", " ").strip()
    return " ".join(part.capitalize() for part in stem.split()) or Path(source_path).name


def _markdown_sections(text: str) -> list[tuple[str, str]]:
    pattern = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)
    matches = list(pattern.finditer(text))
    if not matches:
        return []

    sections: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if body:
            sections.append((match.group(1).strip(), body))
    return sections


def _text_chunks(text: str) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        current.append(line)
        if len(current) >= MAX_CHUNK_LINES:
            chunk = "\n".join(current).strip()
            if chunk:
                chunks.append(chunk)
            current = []
    if current:
        chunk = "\n".join(current).strip()
        if chunk:
            chunks.append(chunk)
    return chunks


def _chunk_documents(source_path: str, kind: str, text: str) -> list[dict[str, Any]]:
    title = _fallback_title(source_path)
    docs: list[dict[str, Any]] = []

    if text and Path(source_path).suffix.lower() in {".md", ".rst", ".txt"}:
        sections = _markdown_sections(text)
        if sections:
            for index, (section_title, section_body) in enumerate(sections, start=1):
                docs.append(
                    {
                        "title": f"{title} — {section_title}",
                        "section": section_title,
                        "body": section_body,
                        "chunk_index": index,
                    }
                )
            return docs

    if text:
        for index, chunk in enumerate(_text_chunks(text), start=1):
            docs.append(
                {
                    "title": title,
                    "section": f"chunk {index}",
                    "body": chunk,
                    "chunk_index": index,
                }
            )
        if docs:
            return docs

    return [
        {
            "title": title,
            "section": kind,
            "body": f"{source_path} [{kind}]",
            "chunk_index": 1,
        }
    ]


def build_source_index(kb_root: str | Path, explicit_targets: list[str | Path] | None = None) -> dict[str, Any]:
    root = Path(kb_root).resolve()
    docs: dict[str, dict[str, Any]] = {}
    df: dict[str, int] = {}
    postings: dict[str, list[str]] = {}
    sources_meta: dict[str, dict[str, Any]] = {}

    for source in discover_sources(root, explicit_targets=explicit_targets):
        text = _safe_read_source_text(source.path, source.kind)
        chunks = _chunk_documents(source.rel_path, source.kind, text)
        chunk_ids: list[str] = []

        for chunk in chunks:
            doc_id = f"{source.rel_path}#chunk-{chunk['chunk_index']:03d}"
            chunk_ids.append(doc_id)
            tokens = _source_tokens(chunk["body"])
            tf: dict[str, int] = {}
            for token in tokens:
                tf[token] = tf.get(token, 0) + 1
            docs[doc_id] = {
                "title": chunk["title"],
                "path": source.rel_path,
                "kind": source.kind,
                "section": chunk["section"],
                "chunk_index": chunk["chunk_index"],
                "len": len(tokens),
                "mtime_ns": source.path.stat().st_mtime_ns,
                "tf": tf,
                "body_preview": " ".join(chunk["body"].split())[:800],
            }
            for token in tf:
                df[token] = df.get(token, 0) + 1
                postings.setdefault(token, []).append(doc_id)

        sources_meta[source.rel_path] = {
            "mtime_ns": source.path.stat().st_mtime_ns,
            "kind": source.kind,
            "chunks": chunk_ids,
        }

    index = {
        "version": SOURCE_INDEX_VERSION,
        "generated_at": _now_iso(),
        "total": len(docs),
        "docs": docs,
        "df": dict(sorted(df.items())),
        "postings": {token: sorted(paths) for token, paths in sorted(postings.items())},
        "sources": dict(sorted(sources_meta.items())),
    }
    target = source_index_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return index


def load_source_index(kb_root: str | Path) -> dict[str, Any]:
    target = source_index_path(kb_root)
    if not target.exists():
        raise FileNotFoundError(f"No source index found: {target}")
    return json.loads(target.read_text(encoding="utf-8"))


def source_index_is_stale(kb_root: str | Path, explicit_targets: list[str | Path] | None = None) -> bool:
    root = Path(kb_root).resolve()
    target = source_index_path(root)
    if not target.exists():
        return True

    try:
        index = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True

    if index.get("version") != SOURCE_INDEX_VERSION:
        return True

    current_sources = {record.rel_path: record for record in discover_sources(root, explicit_targets=explicit_targets)}
    indexed_sources = index.get("sources", {})
    if set(current_sources) != set(indexed_sources):
        return True

    for rel_path, record in current_sources.items():
        if indexed_sources.get(rel_path, {}).get("mtime_ns") != record.path.stat().st_mtime_ns:
            return True
    return False


def _source_snippet(index: dict[str, Any], doc_id: str, terms: list[str]) -> str:
    preview = index.get("docs", {}).get(doc_id, {}).get("body_preview", "")
    lowered = preview.lower()
    for term in terms:
        position = lowered.find(term.lower())
        if position != -1:
            start = max(0, position - 80)
            end = min(len(preview), position + 100)
            snippet = preview[start:end].strip()
            if start > 0:
                snippet = "..." + snippet
            if end < len(preview):
                snippet = snippet + "..."
            return snippet
    return preview


def search_source_index(kb_root: str | Path, query: str, limit: int = 10) -> list[SourceSearchResult]:
    index = load_source_index(kb_root)
    matches, positive_terms = matching_documents(index, query)
    if not matches:
        return []

    ranked = sorted(
        (
            SourceSearchResult(
                path=doc_id,
                title=index["docs"][doc_id]["title"],
                score=_score_document(index, doc_id, positive_terms),
                snippet=_source_snippet(index, doc_id, positive_terms),
                source_path=index["docs"][doc_id]["path"],
                chunk_id=doc_id.rsplit("#", 1)[-1],
                kind=index["docs"][doc_id]["kind"],
                section=index["docs"][doc_id]["section"],
            )
            for doc_id in matches
        ),
        key=lambda item: (-item.score, item.source_path, item.path),
    )

    per_source: dict[str, SourceSearchResult] = {}
    for result in ranked:
        if result.source_path not in per_source:
            per_source[result.source_path] = result
        if len(per_source) >= limit:
            break
    return list(per_source.values())


def consulted_sources_from_retrieval(payload: dict[str, Any], *, actual_mode: str) -> list[str]:
    """Return normalized sources_consulted paths for the chosen retrieval mode."""

    mode = {
        "wiki": "wiki_only",
        "source": "source_only",
        "hybrid": "hybrid",
        "wiki_only": "wiki_only",
        "source_only": "source_only",
    }.get(actual_mode, actual_mode)

    consulted: list[str] = []
    seen: set[str] = set()

    if mode in {"wiki_only", "hybrid"}:
        for result in payload.get("wiki_results", []):
            path = result.get("path")
            if not isinstance(path, str) or not path:
                continue
            normalized = f"wiki/{path}" if not path.startswith("wiki/") else path
            if normalized not in seen:
                consulted.append(normalized)
                seen.add(normalized)

    if mode in {"source_only", "hybrid"}:
        for result in payload.get("source_results", []):
            path = result.get("source_path")
            if not isinstance(path, str) or not path:
                continue
            if path not in seen:
                consulted.append(path)
                seen.add(path)

    return consulted


def consulted_sources_by_mode(payload: dict[str, Any]) -> dict[str, list[str]]:
    return {
        "wiki_only": consulted_sources_from_retrieval(payload, actual_mode="wiki_only"),
        "source_only": consulted_sources_from_retrieval(payload, actual_mode="source_only"),
        "hybrid": consulted_sources_from_retrieval(payload, actual_mode="hybrid"),
    }


def suggest_retrieval_mode(question: str, *, mode: str = "auto") -> RetrievalSuggestion:
    explicit_mode = {
        "wiki": "wiki_only",
        "source": "source_only",
        "hybrid": "hybrid",
        "wiki_only": "wiki_only",
        "source_only": "source_only",
    }
    if mode != "auto":
        normalized = explicit_mode.get(mode, mode)
        return RetrievalSuggestion(mode=normalized, reasons=["explicit mode override"])

    for pattern in AUTO_SOURCE_ONLY_PATTERNS:
        if pattern.search(question):
            return RetrievalSuggestion(mode="source_only", reasons=["question asks for exact source-level evidence"])

    lowered = question.lower()
    if any(term in lowered for term in AUTO_HYBRID_TERMS):
        return RetrievalSuggestion(mode="hybrid", reasons=["question likely needs both compiled wiki context and raw source detail"])

    return RetrievalSuggestion(mode="wiki_only", reasons=["question is answerable from compiled wiki context first"])


def plan_retrieval(question: str, *, mode: str = "auto") -> RetrievalSuggestion:
    """Backward-compatible alias for the retrieval suggestion helper."""

    return suggest_retrieval_mode(question, mode=mode)


def query_retrieval(
    kb_root: str | Path,
    question: str,
    *,
    mode: str = "auto",
    wiki_limit: int = 5,
    source_limit: int = 5,
) -> dict[str, Any]:
    root = Path(kb_root).resolve()
    suggestion = suggest_retrieval_mode(question, mode=mode)
    wiki_results: list[SearchResult] = []
    source_results: list[SourceSearchResult] = []
    executed_modes: list[str] = []

    run_wiki = mode == "auto" or suggestion.mode in {"wiki_only", "hybrid"}
    run_source = mode == "auto" or suggestion.mode in {"source_only", "hybrid"}

    if run_wiki:
        wiki_dir = root / "wiki"
        if index_is_stale(wiki_dir):
            build_index(wiki_dir)
        wiki_results = search_index(wiki_dir, question, limit=wiki_limit)
        executed_modes.append("wiki")

    if run_source:
        if source_index_is_stale(root):
            build_source_index(root)
        source_results = search_source_index(root, question, limit=source_limit)
        executed_modes.append("source")

    retrieval_trace = [f"wiki:{result.path}" for result in wiki_results]
    retrieval_trace.extend(f"source:{result.path}" for result in source_results)

    return {
        "plan_version": 2,
        "question": question,
        "mode": mode,
        "suggested_mode": suggestion.mode,
        "reasons": suggestion.reasons,
        "executed_modes": executed_modes,
        "wiki_results": [result.__dict__ for result in wiki_results],
        "source_results": [asdict(result) for result in source_results],
        "retrieval_trace": retrieval_trace,
        "sources_consulted_by_mode": consulted_sources_by_mode(
            {
                "wiki_results": [result.__dict__ for result in wiki_results],
                "source_results": [asdict(result) for result in source_results],
            }
        ),
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
    parser = argparse.ArgumentParser(description="llm-notes dual-layer retrieval helpers")
    subparsers = parser.add_subparsers(dest="command", required=True)

    index_parser = subparsers.add_parser("index-source", help="build or rebuild the source retrieval index")
    index_parser.add_argument("--kb-root")
    index_parser.add_argument("targets", nargs="*")

    stale_parser = subparsers.add_parser("source-stale", help="check whether the source retrieval index is stale")
    stale_parser.add_argument("--kb-root")

    query_parser = subparsers.add_parser("query", help="query wiki and/or source retrieval indexes")
    query_parser.add_argument("--kb-root")
    query_parser.add_argument("--question", required=True)
    query_parser.add_argument("--mode", choices=("auto", "wiki", "source", "hybrid", "wiki_only", "source_only"), default="auto")
    query_parser.add_argument("--wiki-limit", type=int, default=5)
    query_parser.add_argument("--source-limit", type=int, default=5)
    query_parser.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    kb_root = _resolved_kb_root(getattr(args, "kb_root", None))

    if args.command == "index-source":
        index = build_source_index(kb_root, explicit_targets=args.targets or None)
        print(f"Indexed {index['total']} source chunks -> {source_index_path(kb_root)}")
        return 0

    if args.command == "source-stale":
        print("stale" if source_index_is_stale(kb_root) else "fresh")
        return 0

    if args.command == "query":
        payload = query_retrieval(
            kb_root,
            args.question,
            mode=args.mode,
            wiki_limit=args.wiki_limit,
            source_limit=args.source_limit,
        )
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"mode request: {payload['mode']}")
            print(f"suggested mode: {payload['suggested_mode']}")
            for reason in payload["reasons"]:
                print(f"- {reason}")
            for result in payload["wiki_results"]:
                print(f"WIKI  {result['path']}  {result['title']}")
            for result in payload["source_results"]:
                print(f"SRC   {result['source_path']}  {result['section']}")
        return 0 if payload["wiki_results"] or payload["source_results"] else 1

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
