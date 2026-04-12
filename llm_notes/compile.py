"""Source discovery and manifest-driven compile planning for llm-notes."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from llm_notes.manifest import load_manifest, manifest_path, save_manifest, source_is_stale, update_source_entry
from llm_notes.wiki import article_inventory, sync_indexes

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
    compiled_source_refs: set[str]
    manifest_in_use: bool


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


def build_compilation_plan(
    kb_root: str | Path,
    explicit_targets: list[str | Path] | None = None,
) -> CompilationPlan:
    root = Path(kb_root).resolve()
    manifest = load_manifest(root)
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

    return CompilationPlan(
        all_sources=sources,
        new_sources=new_sources,
        stale_sources=stale_sources,
        unchanged_sources=unchanged_sources,
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

    return save_manifest(root, manifest)


def sync_kb_indexes(kb_root: str | Path) -> dict[str, Path]:
    root = Path(kb_root).resolve()
    total_sources = len(discover_sources(root))
    return sync_indexes(root, total_sources=total_sources)


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
    payload["compiled_source_refs"] = sorted(payload["compiled_source_refs"])
    return payload


def _print_plan(plan: CompilationPlan) -> None:
    print(
        f"Sources: {len(plan.all_sources)} total | "
        f"{len(plan.new_sources)} new | {len(plan.stale_sources)} stale | "
        f"{len(plan.unchanged_sources)} unchanged"
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="llm-notes compile helpers")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser("plan", help="compute the current compilation plan")
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

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
