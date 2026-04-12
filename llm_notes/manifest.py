"""Manifest helpers for tracking compiled knowledge-base sources."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MANIFEST_VERSION = 2
MANIFEST_RELATIVE_PATH = Path("outputs") / "_manifest.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _body_content(content: bytes) -> bytes:
    """Strip YAML frontmatter from Markdown content, returning only the body."""
    text = content.decode(errors="replace")
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4 :].encode()
    return content


def manifest_path(kb_root: str | Path) -> Path:
    return Path(kb_root) / MANIFEST_RELATIVE_PATH


def default_manifest() -> dict[str, Any]:
    return {
        "version": MANIFEST_VERSION,
        "updated_at": None,
        "sources": {},
        "articles": {},
    }


def load_manifest(kb_root: str | Path) -> dict[str, Any]:
    path = manifest_path(kb_root)
    if not path.exists():
        return default_manifest()

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_manifest()

    manifest = default_manifest()
    manifest["version"] = int(data.get("version", MANIFEST_VERSION))
    manifest["updated_at"] = data.get("updated_at")
    manifest["sources"] = data.get("sources", {}) if isinstance(data.get("sources"), dict) else {}
    manifest["articles"] = data.get("articles", {}) if isinstance(data.get("articles"), dict) else {}
    return manifest


def save_manifest(kb_root: str | Path, manifest: dict[str, Any]) -> Path:
    path = manifest_path(kb_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = default_manifest()
    payload.update(manifest)
    payload["version"] = MANIFEST_VERSION
    payload["updated_at"] = _now_iso()
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return path


def source_digest(path: str | Path) -> str:
    """Return a stable digest for a source file.

    Markdown files ignore YAML frontmatter so metadata-only edits do not force
    downstream recompilation.
    """

    source_path = Path(path)
    raw = source_path.read_bytes()
    content = _body_content(raw) if source_path.suffix.lower() == ".md" else raw
    digest = hashlib.sha256()
    digest.update(content)
    digest.update(b"\x00")
    digest.update(str(source_path.resolve()).encode("utf-8"))
    return digest.hexdigest()


def _relative_to_root(path: str | Path, kb_root: str | Path) -> str:
    return Path(os.path.relpath(Path(path).resolve(), Path(kb_root).resolve())).as_posix()


def tracked_sources(manifest: dict[str, Any]) -> set[str]:
    sources = manifest.get("sources", {})
    if not isinstance(sources, dict):
        return set()
    return set(sources)


def tracked_articles(manifest: dict[str, Any]) -> set[str]:
    articles = manifest.get("articles", {})
    if not isinstance(articles, dict):
        return set()
    return set(articles)


def get_source_entry(
    manifest: dict[str, Any],
    kb_root: str | Path,
    source_path: str | Path,
) -> dict[str, Any] | None:
    rel_path = _relative_to_root(source_path, kb_root)
    entry = manifest.get("sources", {}).get(rel_path)
    return entry if isinstance(entry, dict) else None


def get_article_entry(
    manifest: dict[str, Any],
    kb_root: str | Path,
    article_path: str | Path,
) -> dict[str, Any] | None:
    rel_path = _relative_to_root(article_path, kb_root)
    entry = manifest.get("articles", {}).get(rel_path)
    return entry if isinstance(entry, dict) else None


def update_source_entry(
    manifest: dict[str, Any],
    kb_root: str | Path,
    source_path: str | Path,
    *,
    article_paths: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rel_path = _relative_to_root(source_path, kb_root)
    source = Path(source_path)
    existing = manifest.setdefault("sources", {}).get(rel_path)
    existing_articles = []
    existing_metadata: dict[str, Any] = {}
    if isinstance(existing, dict):
        existing_articles = existing.get("articles", []) if isinstance(existing.get("articles"), list) else []
        existing_metadata = existing.get("metadata", {}) if isinstance(existing.get("metadata"), dict) else {}

    entry: dict[str, Any] = {
        "digest": source_digest(source),
        "mtime_ns": source.stat().st_mtime_ns,
        "compiled_at": _now_iso(),
        "articles": sorted(set(existing_articles + list(article_paths or []))),
    }
    combined_metadata = dict(existing_metadata)
    combined_metadata.update(metadata or {})
    if combined_metadata:
        entry["metadata"] = combined_metadata
    manifest.setdefault("sources", {})[rel_path] = entry
    return entry


def update_article_entry(
    manifest: dict[str, Any],
    kb_root: str | Path,
    article_path: str | Path,
    *,
    source_paths: list[str | Path] | None = None,
    metadata: dict[str, Any] | None = None,
    title: str | None = None,
    category: str | None = None,
    slug: str | None = None,
) -> dict[str, Any]:
    root = Path(kb_root).resolve()
    rel_path = _relative_to_root(article_path, root)
    article_rel = rel_path.removeprefix("wiki/")
    article_parts = Path(article_rel).parts
    derived_slug = Path(article_rel).stem if article_parts else Path(rel_path).stem
    derived_category = "/".join(article_parts[:-1]) if len(article_parts) > 1 else ""
    wikilink = article_rel.removesuffix(".md")
    existing = manifest.setdefault("articles", {}).get(rel_path)
    existing_sources: list[str] = []
    existing_metadata: dict[str, Any] = {}
    if isinstance(existing, dict):
        existing_sources = existing.get("source_refs", []) if isinstance(existing.get("source_refs"), list) else []
        existing_metadata = existing.get("metadata", {}) if isinstance(existing.get("metadata"), dict) else {}

    normalized_sources = [
        _relative_to_root(source_path, root)
        for source_path in (source_paths or [])
    ]
    source_refs = sorted(set(existing_sources + normalized_sources))
    source_digests = {
        source_ref: source_digest(root / source_ref)
        for source_ref in source_refs
        if (root / source_ref).exists()
    }

    entry: dict[str, Any] = {
        "compiled_at": _now_iso(),
        "title": title or (existing.get("title") if isinstance(existing, dict) else None) or derived_slug.replace("-", " ").title(),
        "category": category if category is not None else (existing.get("category") if isinstance(existing, dict) else None) or derived_category,
        "slug": slug or (existing.get("slug") if isinstance(existing, dict) else None) or derived_slug,
        "wikilink": wikilink,
        "source_refs": source_refs,
        "source_digests": source_digests,
    }

    combined_metadata = dict(existing_metadata)
    combined_metadata.update(metadata or {})
    if combined_metadata:
        entry["metadata"] = combined_metadata

    manifest.setdefault("articles", {})[rel_path] = entry
    return entry


def source_is_stale(
    manifest: dict[str, Any],
    kb_root: str | Path,
    source_path: str | Path,
) -> bool:
    source = Path(source_path)
    if not source.exists():
        return True

    entry = get_source_entry(manifest, kb_root, source)
    if entry is None:
        return True

    recorded_digest = entry.get("digest")
    recorded_mtime = entry.get("mtime_ns")
    return recorded_digest != source_digest(source) or recorded_mtime != source.stat().st_mtime_ns
