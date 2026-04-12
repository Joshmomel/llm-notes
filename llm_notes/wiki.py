"""Deterministic wiki/article helpers for llm-notes."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

REQUIRED_FRONTMATTER_FIELDS = ("title", "created", "updated", "sources", "tags")


@dataclass(frozen=True)
class Article:
    path: Path
    rel_path: str
    category: str
    slug: str
    metadata: dict[str, Any]
    body: str

    @property
    def title(self) -> str:
        value = self.metadata.get("title")
        return str(value).strip() if value else self.slug.replace("-", " ").title()

    @property
    def wikilink(self) -> str:
        return self.rel_path.removesuffix(".md")


@dataclass(frozen=True)
class ArticleWriteResult:
    path: Path
    rel_path: str
    wikilink: str
    status: str


def wiki_root(kb_root: str | Path) -> Path:
    return Path(kb_root) / "wiki"


def _normalize_scalar(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    return [str(value).strip()]


def _parse_inline_value(raw: str) -> Any:
    value = raw.strip()
    if not value:
        return ""
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [part.strip().strip('"').strip("'") for part in inner.split(",") if part.strip()]
    return value.strip('"').strip("'")


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text

    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text

    closing_index: int | None = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            closing_index = index
            break

    if closing_index is None:
        return {}, text

    metadata: dict[str, Any] = {}
    current_list_key: str | None = None

    for line in lines[1:closing_index]:
        if not line.strip():
            continue

        stripped = line.lstrip()
        if stripped.startswith("- ") and current_list_key:
            metadata.setdefault(current_list_key, [])
            metadata[current_list_key].append(stripped[2:].strip().strip('"').strip("'"))
            continue

        if ":" not in line:
            current_list_key = None
            continue

        key, raw_value = line.split(":", 1)
        key = key.strip()
        parsed = _parse_inline_value(raw_value)
        if raw_value.strip() == "":
            metadata[key] = []
            current_list_key = key
        else:
            metadata[key] = parsed
            current_list_key = None

    body = "\n".join(lines[closing_index + 1 :]).lstrip("\n")
    return metadata, body


def normalize_article_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(metadata)
    normalized["title"] = _normalize_scalar(normalized.get("title"))
    normalized["created"] = _normalize_scalar(normalized.get("created"))
    normalized["updated"] = _normalize_scalar(normalized.get("updated"))
    normalized["sources"] = sorted(set(_normalize_list(normalized.get("sources"))))
    normalized["tags"] = sorted(set(_normalize_list(normalized.get("tags"))))
    return normalized


def _format_scalar(value: Any) -> str:
    text = str(value)
    if not text:
        return '""'
    if any(char in text for char in ':#[]{},"\'' ) or text != text.strip():
        return json.dumps(text, ensure_ascii=False)
    return text


def dump_frontmatter(metadata: dict[str, Any]) -> str:
    normalized = normalize_article_metadata(metadata)
    ordered_keys = [key for key in REQUIRED_FRONTMATTER_FIELDS if key in normalized]
    ordered_keys.extend(sorted(key for key in normalized if key not in ordered_keys))

    lines = ["---"]
    for key in ordered_keys:
        value = normalized[key]
        if key == "tags":
            rendered = ", ".join(_format_scalar(item) for item in value)
            lines.append(f"{key}: [{rendered}]")
            continue

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


def serialize_article(metadata: dict[str, Any], body: str) -> str:
    frontmatter = dump_frontmatter(metadata)
    normalized_body = body.strip()
    if normalized_body:
        return f"{frontmatter}\n\n{normalized_body}\n"
    return f"{frontmatter}\n"


def slugify(text: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE).strip().lower()
    slug = re.sub(r"[-\s]+", "-", slug)
    return slug or "article"


def article_path(kb_root: str | Path, category: str, slug: str) -> Path:
    root = wiki_root(kb_root)
    return root / category / f"{slug}.md" if category else root / f"{slug}.md"


def _today() -> str:
    return date.today().isoformat()


def read_article(path: str | Path, kb_root: str | Path | None = None) -> Article:
    article_path_obj = Path(path)
    base = wiki_root(kb_root) if kb_root is not None else article_path_obj.parents[1]
    text = article_path_obj.read_text(encoding="utf-8", errors="ignore")
    metadata, body = parse_frontmatter(text)
    normalized = normalize_article_metadata(metadata)
    rel_path = article_path_obj.resolve().relative_to(base.resolve()).as_posix()
    parts = Path(rel_path).parts
    category = "/".join(parts[:-1])
    slug = Path(rel_path).stem
    return Article(article_path_obj, rel_path, category, slug, normalized, body)


def write_article(
    kb_root: str | Path,
    *,
    title: str,
    body: str,
    category: str = "",
    slug: str | None = None,
    sources: list[str] | None = None,
    tags: list[str] | None = None,
    created: str | None = None,
    updated: str | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> ArticleWriteResult:
    root = Path(kb_root)
    article_slug = slug or slugify(title)
    target = article_path(root, category, article_slug)
    target.parent.mkdir(parents=True, exist_ok=True)

    existing_metadata: dict[str, Any] = {}
    if target.exists():
        existing = read_article(target, root)
        existing_metadata = dict(existing.metadata)
        status = "updated"
    else:
        status = "created"

    effective_created = existing_metadata.get("created") or created or _today()
    effective_updated = updated or _today()
    merged_sources = sorted(set(_normalize_list(existing_metadata.get("sources")) + _normalize_list(sources)))
    merged_tags = sorted(set(_normalize_list(existing_metadata.get("tags")) + _normalize_list(tags)))

    metadata = dict(existing_metadata)
    metadata.update(extra_metadata or {})
    metadata.update(
        {
            "title": title,
            "created": effective_created,
            "updated": effective_updated,
            "sources": merged_sources,
            "tags": merged_tags,
        }
    )

    target.write_text(serialize_article(metadata, body), encoding="utf-8")
    rel_path = target.resolve().relative_to(wiki_root(root).resolve()).as_posix()
    return ArticleWriteResult(
        path=target,
        rel_path=rel_path,
        wikilink=rel_path.removesuffix(".md"),
        status=status,
    )


def list_articles(kb_root: str | Path) -> list[Article]:
    root = wiki_root(kb_root)
    if not root.exists():
        return []

    articles = []
    for path in sorted(root.rglob("*.md")):
        if path.name.startswith("_"):
            continue
        articles.append(read_article(path, kb_root))
    return articles


def article_inventory(kb_root: str | Path) -> dict[str, Any]:
    articles = list_articles(kb_root)
    by_source: dict[str, list[str]] = {}

    for article in articles:
        for source in article.metadata.get("sources", []):
            by_source.setdefault(source, []).append(article.rel_path)

    return {
        "articles": articles,
        "by_source": {source: sorted(paths) for source, paths in sorted(by_source.items())},
    }


def _display_category_name(category: str) -> str:
    if not category:
        return "Knowledge Base"
    label = category.replace("/", " / ").replace("-", " ").replace("_", " ")
    return label.title()


def render_category_index(category: str, articles: list[Article]) -> str:
    lines = [f"# {_display_category_name(category)}", "", "## Articles", ""]
    if not articles:
        lines.append("(No articles yet.)")
        return "\n".join(lines) + "\n"

    for article in sorted(articles, key=lambda item: item.title.lower()):
        lines.append(f"- [[{article.slug}]] — {article.title}")
    return "\n".join(lines) + "\n"


def update_category_index(kb_root: str | Path, category: str, articles: list[Article]) -> Path | None:
    if not category:
        return None

    target = wiki_root(kb_root) / category / "_index.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_category_index(category, articles), encoding="utf-8")
    return target


def render_master_index(articles: list[Article], total_sources: int) -> str:
    lines = ["# Knowledge Base Index", "", "## Categories", ""]
    by_category: dict[str, list[Article]] = {}
    for article in articles:
        by_category.setdefault(article.category or "_root", []).append(article)

    if not by_category:
        lines.append("(No categories yet. Run `/kb-compile` to compile source material into wiki articles.)")
    else:
        for category, category_articles in sorted(by_category.items()):
            if category == "_root":
                lines.append(f"- Root — {len(category_articles)} article(s)")
            else:
                lines.append(f"- [[{category}/_index]] — {len(category_articles)} article(s)")

    lines.extend(
        [
            "",
            "## Recent Updates",
            "",
            "(See [[_recent]] for the change log.)",
            "",
            "## Stats",
            "",
            f"- Total articles: {len(articles)}",
            f"- Total sources: {total_sources}",
        ]
    )
    return "\n".join(lines) + "\n"


def update_master_index(kb_root: str | Path, articles: list[Article], total_sources: int) -> Path:
    target = wiki_root(kb_root) / "_index.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_master_index(articles, total_sources), encoding="utf-8")
    return target


def load_recent_entries(kb_root: str | Path) -> list[str]:
    recent_path = wiki_root(kb_root) / "_recent.md"
    if not recent_path.exists():
        return []

    entries = []
    for line in recent_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            entries.append(stripped[2:])
    return entries


def write_recent_entries(kb_root: str | Path, entries: list[str]) -> Path:
    target = wiki_root(kb_root) / "_recent.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Recent Updates", ""]
    if entries:
        lines.extend(f"- {entry}" for entry in entries)
    else:
        lines.append("(No updates yet. This file is updated automatically when articles are compiled.)")
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def prepend_recent_entry(kb_root: str | Path, entry: str, limit: int = 100) -> Path:
    entries = [entry]
    for existing in load_recent_entries(kb_root):
        if existing != entry:
            entries.append(existing)
    return write_recent_entries(kb_root, entries[:limit])


def sync_indexes(kb_root: str | Path, total_sources: int) -> dict[str, Path]:
    articles = list_articles(kb_root)
    by_category: dict[str, list[Article]] = {}
    for article in articles:
        if article.category:
            by_category.setdefault(article.category, []).append(article)

    written: dict[str, Path] = {}
    for category, category_articles in sorted(by_category.items()):
        target = update_category_index(kb_root, category, category_articles)
        if target is not None:
            written[f"category:{category}"] = target

    written["master"] = update_master_index(kb_root, articles, total_sources)
    return written
