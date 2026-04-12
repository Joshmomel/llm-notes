"""Source discovery and manifest-driven source/article planning for llm-notes."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

from llm_notes.manifest import (
    load_manifest,
    manifest_path,
    save_manifest,
    source_is_stale,
    update_article_entry,
    update_source_entry,
)
from llm_notes.wiki import article_inventory, prepend_recent_entry, slugify, sync_indexes, write_article

CODE_EXTENSIONS = {
    ".c",
    ".cc",
    ".cpp",
    ".cs",
    ".cxx",
    ".ex",
    ".go",
    ".h",
    ".hpp",
    ".java",
    ".jl",
    ".js",
    ".jsx",
    ".kt",
    ".lua",
    ".m",
    ".md",
    ".php",
    ".ps1",
    ".py",
    ".rb",
    ".rs",
    ".scala",
    ".swift",
    ".ts",
    ".tsx",
    ".txt",
    ".zig",
}
DOCUMENT_EXTENSIONS = {".md", ".rst", ".txt"}
PAPER_EXTENSIONS = {".pdf"}
IMAGE_EXTENSIONS = {".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp"}
SUPPORTED_EXTENSIONS = CODE_EXTENSIONS | DOCUMENT_EXTENSIONS | PAPER_EXTENSIONS | IMAGE_EXTENSIONS

SKIP_DIR_NAMES = {
    ".cursor",
    ".git",
    ".idea",
    ".obsidian",
    ".venv",
    "__pycache__",
    "node_modules",
    "outputs",
    "wiki",
}
SKIP_FILE_NAMES = {
    ".DS_Store",
    ".gitignore",
    "CLAUDE.md",
}


@dataclass(frozen=True)
class SourceRecord:
    path: Path
    rel_path: str
    kind: str


@dataclass(frozen=True)
class CompilationPlan:
    all_sources: list[SourceRecord]
    new_sources: list[SourceRecord]
    stale_sources: list[SourceRecord]
    unchanged_sources: list[SourceRecord]
    impacted_articles: list["ImpactedArticle"]
    planned_articles: list["ArticlePlan"]
    compiled_source_refs: set[str]
    manifest_in_use: bool


@dataclass(frozen=True)
class ImpactedArticle:
    article_path: str
    wikilink: str
    title: str
    category: str
    slug: str
    source_rel_paths: list[str]
    reasons: list[str]


@dataclass(frozen=True)
class ArticlePlan:
    action: str
    article_path: str
    wikilink: str
    title: str
    category: str
    slug: str
    source_rel_paths: list[str]
    reasons: list[str]


def find_kb_root(start: str | Path = ".") -> Path | None:
    current = Path(start).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "wiki").is_dir():
            return candidate
    return None


def classify_source(path: str | Path) -> str | None:
    ext = Path(path).suffix.lower()
    if ext in PAPER_EXTENSIONS:
        return "paper"
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in DOCUMENT_EXTENSIONS:
        return "document"
    if ext in CODE_EXTENSIONS:
        return "code"
    return None


def _normalized_rel_path_fallback(path: Path, kb_root: Path) -> str:
    try:
        return path.resolve().relative_to(kb_root.resolve()).as_posix()
    except ValueError:
        import os

        return Path(os.path.relpath(path.resolve(), kb_root.resolve())).as_posix()


def _is_within_root(path: Path, kb_root: Path) -> bool:
    try:
        path.resolve().relative_to(kb_root.resolve())
        return True
    except ValueError:
        return False


def _should_skip_path(path: Path, kb_root: Path) -> bool:
    rel_path = _normalized_rel_path_fallback(path, kb_root)
    parts = Path(rel_path).parts
    if path.name.startswith("."):
        return True
    if any(part.endswith(".egg-info") for part in parts[:-1]) or path.parent.name.endswith(".egg-info"):
        return True
    if any(part.startswith(".") and part not in {".github"} for part in parts[:-1]):
        return True
    if any(part in SKIP_DIR_NAMES for part in parts[:-1]):
        return True
    return path.name in SKIP_FILE_NAMES


def _iter_files(target: Path) -> Iterable[Path]:
    if target.is_file():
        yield target
        return

    if target.is_dir():
        for path in sorted(target.rglob("*")):
            if path.is_file():
                yield path


def discover_sources(kb_root: str | Path, explicit_targets: list[str | Path] | None = None) -> list[SourceRecord]:
    root = Path(kb_root).resolve()
    candidates = explicit_targets or [root]
    discovered: dict[str, SourceRecord] = {}

    for candidate in candidates:
        target = (root / candidate).resolve() if not Path(candidate).is_absolute() else Path(candidate).resolve()
        if not target.exists():
            continue

        for path in _iter_files(target):
            kind = classify_source(path)
            if kind is None:
                continue
            if _is_within_root(path, root):
                if _should_skip_path(path, root):
                    continue
            else:
                if any(part.startswith(".") for part in path.parts):
                    continue
            rel_path = _normalized_rel_path_fallback(path, root)
            discovered[rel_path] = SourceRecord(path=path, rel_path=rel_path, kind=kind)

    return [discovered[key] for key in sorted(discovered)]


def compiled_source_refs_from_wiki(kb_root: str | Path) -> set[str]:
    inventory = article_inventory(kb_root)
    return set(inventory["by_source"])


def _root_relative_article_ref(article_ref: str | Path) -> str:
    ref = Path(article_ref).as_posix().lstrip("./")
    if ref.startswith("wiki/"):
        return ref
    return f"wiki/{ref}"


def _article_descriptor(
    article_ref: str | Path,
    manifest: dict,
    inventory: dict,
) -> dict[str, str]:
    root_relative = _root_relative_article_ref(article_ref)
    wiki_relative = root_relative.removeprefix("wiki/")
    manifest_entry = manifest.get("articles", {}).get(root_relative)
    inventory_entry = inventory.get("by_article", {}).get(wiki_relative)

    slug = (
        manifest_entry.get("slug")
        if isinstance(manifest_entry, dict) and manifest_entry.get("slug")
        else inventory_entry.get("slug")
        if isinstance(inventory_entry, dict) and inventory_entry.get("slug")
        else Path(wiki_relative).stem
    )
    category = (
        manifest_entry.get("category")
        if isinstance(manifest_entry, dict) and manifest_entry.get("category") is not None
        else inventory_entry.get("category")
        if isinstance(inventory_entry, dict) and inventory_entry.get("category") is not None
        else "/".join(Path(wiki_relative).parts[:-1])
    )
    title = (
        manifest_entry.get("title")
        if isinstance(manifest_entry, dict) and manifest_entry.get("title")
        else inventory_entry.get("title")
        if isinstance(inventory_entry, dict) and inventory_entry.get("title")
        else slug.replace("-", " ").title()
    )
    wikilink = (
        manifest_entry.get("wikilink")
        if isinstance(manifest_entry, dict) and manifest_entry.get("wikilink")
        else inventory_entry.get("wikilink")
        if isinstance(inventory_entry, dict) and inventory_entry.get("wikilink")
        else wiki_relative.removesuffix(".md")
    )
    return {
        "article_path": root_relative,
        "wikilink": wikilink,
        "title": title,
        "category": category,
        "slug": slug,
    }


def _linked_article_refs(source_rel_path: str, manifest: dict, inventory: dict) -> list[str]:
    refs: set[str] = set()
    source_entry = manifest.get("sources", {}).get(source_rel_path)
    if isinstance(source_entry, dict):
        refs.update(
            _root_relative_article_ref(article_ref)
            for article_ref in source_entry.get("articles", [])
            if isinstance(article_ref, str) and article_ref.strip()
        )
    refs.update(
        _root_relative_article_ref(article_ref)
        for article_ref in inventory.get("by_source", {}).get(source_rel_path, [])
    )
    return sorted(refs)


def _planned_title_for_source(source: SourceRecord, manifest: dict) -> str:
    source_entry = manifest.get("sources", {}).get(source.rel_path)
    source_metadata = source_entry.get("metadata", {}) if isinstance(source_entry, dict) else {}
    raw_title = source_metadata.get("title")
    if raw_title:
        return str(raw_title).strip()
    label = source.path.stem.replace("_", " ").replace("-", " ").strip()
    return " ".join(part.capitalize() for part in label.split()) or source.path.stem


def _planned_category_for_source(source: SourceRecord, manifest: dict) -> str:
    source_entry = manifest.get("sources", {}).get(source.rel_path)
    source_metadata = source_entry.get("metadata", {}) if isinstance(source_entry, dict) else {}
    raw_category = source_metadata.get("category")
    if raw_category is not None:
        return str(raw_category).strip()

    parent = Path(source.rel_path).parent
    if parent == Path("."):
        return ""
    parts = [slugify(part) for part in parent.parts if part not in {".", ""}]
    return "/".join(part for part in parts if part)


def _planned_article_for_source(source: SourceRecord, manifest: dict) -> dict[str, str]:
    source_entry = manifest.get("sources", {}).get(source.rel_path)
    source_metadata = source_entry.get("metadata", {}) if isinstance(source_entry, dict) else {}
    title = _planned_title_for_source(source, manifest)
    category = _planned_category_for_source(source, manifest)
    raw_slug = source_metadata.get("slug")
    slug = str(raw_slug).strip() if raw_slug else slugify(source.path.stem)
    wiki_relative = f"{category}/{slug}.md" if category else f"{slug}.md"
    return {
        "article_path": f"wiki/{wiki_relative}",
        "wikilink": wiki_relative.removesuffix(".md"),
        "title": title,
        "category": category,
        "slug": slug,
    }


def build_compilation_plan(
    kb_root: str | Path,
    explicit_targets: list[str | Path] | None = None,
) -> CompilationPlan:
    root = Path(kb_root).resolve()
    manifest = load_manifest(root)
    inventory = article_inventory(root)
    sources = discover_sources(root, explicit_targets=explicit_targets)
    manifest_in_use = manifest_path(root).exists()
    compiled_refs = set(manifest.get("sources", {})) if manifest_in_use else compiled_source_refs_from_wiki(root)

    new_sources: list[SourceRecord] = []
    stale_sources: list[SourceRecord] = []
    unchanged_sources: list[SourceRecord] = []

    for source in sources:
        if manifest_in_use:
            if source.rel_path not in compiled_refs:
                new_sources.append(source)
            elif source_is_stale(manifest, root, source.path):
                stale_sources.append(source)
            else:
                unchanged_sources.append(source)
        else:
            if source.rel_path in compiled_refs:
                unchanged_sources.append(source)
            else:
                new_sources.append(source)

    impacted_index: dict[str, dict[str, object]] = {}
    planned_index: dict[str, dict[str, object]] = {}

    for bucket, reason in (
        (stale_sources, "linked source changed since the last compile"),
        (new_sources, "new source needs an initial article target"),
    ):
        for source in bucket:
            linked_articles = _linked_article_refs(source.rel_path, manifest, inventory)
            if linked_articles:
                for article_ref in linked_articles:
                    descriptor = _article_descriptor(article_ref, manifest, inventory)
                    impacted = impacted_index.setdefault(
                        descriptor["article_path"],
                        {
                            **descriptor,
                            "source_rel_paths": set(),
                            "reasons": set(),
                        },
                    )
                    impacted["source_rel_paths"].add(source.rel_path)
                    impacted["reasons"].add(reason)

                    plan = planned_index.setdefault(
                        descriptor["article_path"],
                        {
                            "action": "refresh",
                            **descriptor,
                            "source_rel_paths": set(),
                            "reasons": set(),
                        },
                    )
                    plan["source_rel_paths"].add(source.rel_path)
                    plan["reasons"].add(reason)
                continue

            descriptor = _planned_article_for_source(source, manifest)
            plan = planned_index.setdefault(
                descriptor["article_path"],
                {
                    "action": "create",
                    **descriptor,
                    "source_rel_paths": set(),
                    "reasons": set(),
                },
            )
            plan["source_rel_paths"].add(source.rel_path)
            plan["reasons"].add(reason)

    return CompilationPlan(
        all_sources=sources,
        new_sources=new_sources,
        stale_sources=stale_sources,
        unchanged_sources=unchanged_sources,
        impacted_articles=[
            ImpactedArticle(
                article_path=article_path,
                wikilink=str(payload["wikilink"]),
                title=str(payload["title"]),
                category=str(payload["category"]),
                slug=str(payload["slug"]),
                source_rel_paths=sorted(payload["source_rel_paths"]),
                reasons=sorted(payload["reasons"]),
            )
            for article_path, payload in sorted(impacted_index.items())
        ],
        planned_articles=[
            ArticlePlan(
                action=str(payload["action"]),
                article_path=article_path,
                wikilink=str(payload["wikilink"]),
                title=str(payload["title"]),
                category=str(payload["category"]),
                slug=str(payload["slug"]),
                source_rel_paths=sorted(payload["source_rel_paths"]),
                reasons=sorted(payload["reasons"]),
            )
            for article_path, payload in sorted(planned_index.items())
        ],
        compiled_source_refs=compiled_refs,
        manifest_in_use=manifest_in_use,
    )


def _normalize_kb_relative(path: str | Path, kb_root: str | Path) -> str:
    return Path(os.path.relpath(Path(path).resolve(), Path(kb_root).resolve())).as_posix()


def record_compilation(
    kb_root: str | Path,
    source_paths: list[str | Path],
    article_paths: list[str | Path],
    metadata: dict | None = None,
) -> Path:
    root = Path(kb_root).resolve()
    manifest = load_manifest(root)
    normalized_articles = sorted({_normalize_kb_relative(path, root) for path in article_paths})

    for source in source_paths:
        source_path = (root / source).resolve() if not Path(source).is_absolute() else Path(source).resolve()
        update_source_entry(
            manifest,
            root,
            source_path,
            article_paths=normalized_articles,
            metadata=metadata,
        )

    article_title = str(metadata.get("title")).strip() if isinstance(metadata, dict) and metadata.get("title") else None
    for article in article_paths:
        article_path = (root / article).resolve() if not Path(article).is_absolute() else Path(article).resolve()
        update_article_entry(
            manifest,
            root,
            article_path,
            source_paths=source_paths,
            metadata=metadata,
            title=article_title,
        )

    return save_manifest(root, manifest)


def sync_kb_indexes(kb_root: str | Path) -> dict[str, Path]:
    root = Path(kb_root).resolve()
    total_sources = len(discover_sources(root))
    return sync_indexes(root, total_sources=total_sources)


def _recent_entry_date(created: str | None, updated: str | None) -> str:
    return updated or created or date.today().isoformat()


def write_compiled_article(
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
    metadata: dict | None = None,
) -> dict[str, str]:
    root = Path(kb_root).resolve()
    result = write_article(
        root,
        title=title,
        body=body,
        category=category,
        slug=slug,
        sources=sources,
        tags=tags,
        created=created,
        updated=updated,
        extra_metadata=metadata,
    )
    if sources:
        record_compilation(
            root,
            list(sources),
            [result.path],
            metadata={"title": title, "category": category, "slug": result.path.stem, **(metadata or {})},
        )
    prepend_recent_entry(root, f"{_recent_entry_date(created, updated)} [[{result.wikilink}]] — {result.status}")
    sync_kb_indexes(root)
    return {
        "path": str(result.path),
        "rel_path": result.rel_path,
        "wikilink": result.wikilink,
        "status": result.status,
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


def _plan_to_jsonable(plan: CompilationPlan) -> dict:
    payload = asdict(plan)
    for key in ("all_sources", "new_sources", "stale_sources", "unchanged_sources"):
        payload[key] = [
            {
                "path": str(item["path"]),
                "rel_path": item["rel_path"],
                "kind": item["kind"],
            }
            for item in payload[key]
        ]
    for key in ("impacted_articles", "planned_articles"):
        payload[key] = list(payload[key])
    payload["compiled_source_refs"] = sorted(payload["compiled_source_refs"])
    return payload


def _print_plan(plan: CompilationPlan) -> None:
    print(
        f"Sources: {len(plan.all_sources)} total | "
        f"{len(plan.new_sources)} new | {len(plan.stale_sources)} stale | "
        f"{len(plan.unchanged_sources)} unchanged"
    )
    print(
        f"Articles: {len(plan.impacted_articles)} impacted | "
        f"{len(plan.planned_articles)} planned"
    )
    print(f"Manifest: {'present' if plan.manifest_in_use else 'absent (falling back to article sources)'}")

    for label, items in (
        ("New", plan.new_sources),
        ("Stale", plan.stale_sources),
    ):
        if not items:
            continue
        print(f"{label}:")
        for item in items:
            print(f"  - {item.rel_path} [{item.kind}]")

    if plan.impacted_articles:
        print("Impacted articles:")
        for article in plan.impacted_articles:
            print(f"  - {article.article_path} <- {', '.join(article.source_rel_paths)}")

    if plan.planned_articles:
        print("Planned article actions:")
        for article in plan.planned_articles:
            print(
                f"  - {article.action}: {article.article_path} <- "
                f"{', '.join(article.source_rel_paths)}"
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="llm-notes compile helpers")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser("plan", help="compute the current source/article compilation plan")
    plan_parser.add_argument("targets", nargs="*", help="optional source files or directories to scope the plan")
    plan_parser.add_argument("--kb-root")
    plan_parser.add_argument("--json", action="store_true")

    record_parser = subparsers.add_parser("record", help="record compiled source/article mappings in the manifest")
    record_parser.add_argument("--kb-root")
    record_parser.add_argument("--source", action="append", required=True, help="source file path; repeat for multiple")
    record_parser.add_argument("--article", action="append", required=True, help="wiki article path; repeat for multiple")
    record_parser.add_argument("--metadata-json", help="optional JSON object stored under metadata")

    sync_parser = subparsers.add_parser("sync-indexes", help="regenerate category and master indexes from existing articles")
    sync_parser.add_argument("--kb-root")

    write_parser = subparsers.add_parser("write-article", help="write or update a wiki article and finalize bookkeeping")
    write_parser.add_argument("--kb-root")
    write_parser.add_argument("--title", required=True)
    write_parser.add_argument("--category", default="")
    write_parser.add_argument("--slug")
    write_parser.add_argument("--source", action="append", default=[])
    write_parser.add_argument("--tag", action="append", default=[])
    write_parser.add_argument("--created")
    write_parser.add_argument("--updated")
    write_parser.add_argument("--metadata-json", help="optional JSON object merged into article metadata")
    body_group = write_parser.add_mutually_exclusive_group(required=True)
    body_group.add_argument("--body-file", help="path to a markdown body file")
    body_group.add_argument("--body-stdin", action="store_true", help="read the markdown body from stdin")

    args = parser.parse_args(argv)
    kb_root = _resolved_kb_root(getattr(args, "kb_root", None))

    if args.command == "plan":
        plan = build_compilation_plan(kb_root, explicit_targets=args.targets or None)
        if args.json:
            print(json.dumps(_plan_to_jsonable(plan), ensure_ascii=False, indent=2))
        else:
            _print_plan(plan)
        return 0

    if args.command == "record":
        metadata = json.loads(args.metadata_json) if args.metadata_json else None
        manifest_file = record_compilation(kb_root, args.source, args.article, metadata=metadata)
        print(f"Updated manifest -> {manifest_file}")
        return 0

    if args.command == "sync-indexes":
        written = sync_kb_indexes(kb_root)
        print(f"Updated {len(written)} index file(s)")
        for key, path in sorted(written.items()):
            print(f"  {key}: {path}")
        return 0

    if args.command == "write-article":
        metadata = json.loads(args.metadata_json) if args.metadata_json else None
        if args.body_file:
            body = Path(args.body_file).read_text(encoding="utf-8")
        else:
            import sys

            body = sys.stdin.read()
        result = write_compiled_article(
            kb_root,
            title=args.title,
            body=body,
            category=args.category,
            slug=args.slug,
            sources=args.source,
            tags=args.tag,
            created=args.created,
            updated=args.updated,
            metadata=metadata,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
