"""Local search implementation for llm-notes wiki content."""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

INDEX_VERSION = 1
INDEX_FILENAME = "_search_index.json"
WRAPPER_FILENAME = "_search.py"

TOKEN_RE = re.compile(r"\b\w+\b", re.UNICODE)
QUERY_TOKEN_RE = re.compile(r"\(|\)|\bAND\b|\bOR\b|\bNOT\b|\"(?:[^\"\\]|\\.)+\"|[^\s()]+", re.IGNORECASE)
OPERATORS = {"AND", "OR", "NOT"}

WRAPPER_TEMPLATE = """#!/usr/bin/env python3
\"\"\"Thin llm-notes search wrapper installed into a wiki directory.\"\"\"

from llm_notes.search import main


if __name__ == "__main__":
    raise SystemExit(main())
"""


@dataclass
class SearchResult:
    path: str
    title: str
    score: float
    snippet: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4 :].lstrip()
    return text


def tokenize_text(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


def extract_title(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
        if stripped.lower().startswith("title:"):
            return stripped.split(":", 1)[1].strip().strip('"').strip("'")
    return "(untitled)"


def article_files(wiki_dir: str | Path) -> list[Path]:
    root = Path(wiki_dir)
    return sorted(
        path
        for path in root.rglob("*.md")
        if path.is_file() and not path.name.startswith("_")
    )


def index_path(wiki_dir: str | Path) -> Path:
    return Path(wiki_dir) / INDEX_FILENAME


def install_wrapper(wiki_dir: str | Path) -> Path:
    root = Path(wiki_dir)
    root.mkdir(parents=True, exist_ok=True)
    wrapper_path = root / WRAPPER_FILENAME
    wrapper_path.write_text(WRAPPER_TEMPLATE, encoding="utf-8")
    wrapper_path.chmod(0o755)
    return wrapper_path


def build_index(wiki_dir: str | Path) -> dict[str, Any]:
    root = Path(wiki_dir)
    docs: dict[str, dict[str, Any]] = {}
    df: Counter[str] = Counter()
    postings: dict[str, list[str]] = {}

    for md_file in article_files(root):
        rel_path = str(md_file.relative_to(root))
        text = md_file.read_text(encoding="utf-8", errors="ignore")
        body = strip_frontmatter(text)
        tokens = tokenize_text(text)
        tf = Counter(tokens)
        docs[rel_path] = {
            "title": extract_title(text),
            "len": len(tokens),
            "mtime_ns": md_file.stat().st_mtime_ns,
            "tf": dict(tf),
            "body_preview": " ".join(body.split())[:800],
        }
        for token in tf:
            df[token] += 1
            postings.setdefault(token, []).append(rel_path)

    index = {
        "version": INDEX_VERSION,
        "generated_at": _now_iso(),
        "total": len(docs),
        "docs": docs,
        "df": dict(df),
        "postings": {token: sorted(paths) for token, paths in postings.items()},
    }

    target = index_path(root)
    target.write_text(json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return index


def load_index(wiki_dir: str | Path) -> dict[str, Any]:
    target = index_path(wiki_dir)
    if not target.exists():
        raise FileNotFoundError(f"No index found. Run: python3 {Path(wiki_dir) / WRAPPER_FILENAME} index")
    return json.loads(target.read_text(encoding="utf-8"))


def index_is_stale(wiki_dir: str | Path) -> bool:
    root = Path(wiki_dir)
    target = index_path(root)
    if not target.exists():
        return True

    try:
        index = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True

    if index.get("version") != INDEX_VERSION:
        return True

    current_articles = {str(path.relative_to(root)): path for path in article_files(root)}
    indexed_docs = index.get("docs", {})
    if set(current_articles) != set(indexed_docs):
        return True

    for rel_path, path in current_articles.items():
        if indexed_docs.get(rel_path, {}).get("mtime_ns") != path.stat().st_mtime_ns:
            return True
    return False


def _docs_for_token_group(index: dict[str, Any], token_group: list[str]) -> set[str]:
    if not token_group:
        return set()

    groups = []
    postings = index.get("postings", {})
    for token in token_group:
        groups.append(set(postings.get(token, [])))

    if not groups:
        return set()
    return set.intersection(*groups)


def _normalize_query_terms(token: str) -> list[str]:
    normalized = token.strip().strip('"').strip("'")
    return tokenize_text(normalized)


def _query_tokens(query: str) -> list[str | list[str]]:
    tokens: list[str | list[str]] = []
    for raw_token in QUERY_TOKEN_RE.findall(query):
        upper = raw_token.upper()
        if upper in OPERATORS or raw_token in {"(", ")"}:
            tokens.append(upper if upper in OPERATORS else raw_token)
            continue
        term_group = _normalize_query_terms(raw_token)
        if term_group:
            tokens.append(term_group)
    return tokens


def _insert_implicit_or(tokens: list[str | list[str]]) -> list[str | list[str]]:
    result: list[str | list[str]] = []
    previous_operand = False
    for token in tokens:
        current_operand = isinstance(token, list) or token == "(" or token == "NOT"
        if previous_operand and current_operand:
            result.append("AND" if token == "(" or token == "NOT" else "OR")
        result.append(token)
        previous_operand = isinstance(token, list) or token == ")"
    return result


def _to_rpn(tokens: list[str | list[str]]) -> list[str | list[str]]:
    precedence = {"OR": 1, "AND": 2, "NOT": 3}
    output: list[str | list[str]] = []
    operators: list[str] = []

    for token in tokens:
        if isinstance(token, list):
            output.append(token)
            continue
        if token == "(":
            operators.append(token)
            continue
        if token == ")":
            while operators and operators[-1] != "(":
                output.append(operators.pop())
            if operators and operators[-1] == "(":
                operators.pop()
            continue

        while operators and operators[-1] != "(" and precedence.get(operators[-1], 0) >= precedence[token]:
            output.append(operators.pop())
        operators.append(token)

    while operators:
        output.append(operators.pop())
    return output


def _positive_terms(tokens: list[str | list[str]]) -> list[str]:
    positive: list[str] = []
    skip_next = False
    for token in tokens:
        if token == "NOT":
            skip_next = True
            continue
        if isinstance(token, list):
            if not skip_next:
                positive.extend(token)
            skip_next = False
            continue
        if token in {"AND", "OR", "(", ")"}:
            skip_next = False
    return positive


def matching_documents(index: dict[str, Any], query: str) -> tuple[set[str], list[str]]:
    tokens = _query_tokens(query)
    if not tokens:
        return set(), []

    if not any(token in OPERATORS or token in {"(", ")"} for token in tokens if isinstance(token, str)):
        positive = [term for token in tokens if isinstance(token, list) for term in token]
        matches = set()
        for token_group in (token for token in tokens if isinstance(token, list)):
            matches |= _docs_for_token_group(index, token_group)
        return matches, positive

    normalized = _insert_implicit_or(tokens)
    positive = _positive_terms(normalized)
    rpn = _to_rpn(normalized)
    universe = set(index.get("docs", {}))
    stack: list[set[str]] = []

    try:
        for token in rpn:
            if isinstance(token, list):
                stack.append(_docs_for_token_group(index, token))
            elif token == "NOT":
                stack.append(universe - stack.pop())
            else:
                right = stack.pop()
                left = stack.pop()
                stack.append(left & right if token == "AND" else left | right)
    except IndexError:
        return set(), positive

    return (stack[-1] if stack else set()), positive


def _score_document(index: dict[str, Any], doc_path: str, terms: list[str]) -> float:
    doc = index["docs"][doc_path]
    total_docs = max(index.get("total", 0), 1)
    doc_len = max(doc.get("len", 0), 1)
    title = doc.get("title", "").lower()
    score = 0.0

    for term in terms:
        tf = doc.get("tf", {}).get(term, 0)
        df = index.get("df", {}).get(term, 0)
        idf = math.log((1 + total_docs) / (1 + df)) + 1
        score += (tf / doc_len) * idf
        if term in title:
            score += 0.25
    return score


def _snippet_for_doc(wiki_dir: str | Path, doc_path: str, terms: list[str], width: int = 180) -> str:
    text = (Path(wiki_dir) / doc_path).read_text(encoding="utf-8", errors="ignore")
    body = " ".join(strip_frontmatter(text).split())
    lowered = body.lower()

    for term in terms:
        position = lowered.find(term.lower())
        if position != -1:
            start = max(0, position - width // 2)
            end = min(len(body), position + width // 2)
            snippet = body[start:end].strip()
            if start > 0:
                snippet = "..." + snippet
            if end < len(body):
                snippet = snippet + "..."
            return snippet

    return (body[:width] + "...") if len(body) > width else body


def search_index(wiki_dir: str | Path, query: str, limit: int = 10) -> list[SearchResult]:
    index = load_index(wiki_dir)
    matches, positive_terms = matching_documents(index, query)
    if not matches:
        return []

    scored = sorted(
        (
            SearchResult(
                path=doc_path,
                title=index["docs"][doc_path]["title"],
                score=_score_document(index, doc_path, positive_terms),
                snippet=_snippet_for_doc(wiki_dir, doc_path, positive_terms),
            )
            for doc_path in matches
        ),
        key=lambda item: (-item.score, item.path),
    )
    return scored[:limit]


def _print_search_results(results: list[SearchResult]) -> None:
    if not results:
        print("No results found.")
        return

    for result in results:
        wikilink = result.path.removesuffix(".md")
        print(f"{result.score:0.3f}  [[{wikilink}]]  {result.title}")
        if result.snippet:
            print(f"       {result.snippet}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="llm-notes wiki search helpers")
    subparsers = parser.add_subparsers(dest="command", required=True)

    install_parser = subparsers.add_parser("install", help="install the wiki/_search.py wrapper")
    install_parser.add_argument("--wiki-dir", default="wiki")

    index_parser = subparsers.add_parser("index", help="build or rebuild the wiki search index")
    index_parser.add_argument("--wiki-dir", default="wiki")

    search_parser = subparsers.add_parser("search", help="query the wiki search index")
    search_parser.add_argument("query")
    search_parser.add_argument("--wiki-dir", default="wiki")
    search_parser.add_argument("--limit", type=int, default=10)
    search_parser.add_argument("--json", action="store_true")

    stale_parser = subparsers.add_parser("stale", help="check whether the index is stale")
    stale_parser.add_argument("--wiki-dir", default="wiki")

    args = parser.parse_args(argv)

    if args.command == "install":
        wrapper = install_wrapper(args.wiki_dir)
        print(f"Installed search wrapper -> {wrapper}")
        return 0

    if args.command == "index":
        index = build_index(args.wiki_dir)
        print(f"Indexed {index['total']} articles -> {index_path(args.wiki_dir)}")
        return 0

    if args.command == "stale":
        print("stale" if index_is_stale(args.wiki_dir) else "fresh")
        return 0

    if args.command == "search":
        results = search_index(args.wiki_dir, args.query, limit=args.limit)
        if args.json:
            print(
                json.dumps(
                    [result.__dict__ for result in results],
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            _print_search_results(results)
        return 0 if results else 1

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
