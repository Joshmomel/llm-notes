"""Import external material into an llm-notes knowledge base."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import urlopen

from llm_notes.compile import find_kb_root
from llm_notes.report import write_report as write_kb_report
from llm_notes.wiki import slugify


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


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


def _imports_root(kb_root: str | Path, kind: str) -> Path:
    return Path(kb_root) / "imports" / kind


def _ensure_unique_path(target_dir: Path, stem: str, suffix: str) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    candidate = target_dir / f"{stem}{suffix}"
    if not candidate.exists():
        return candidate
    for index in range(2, 1000):
        alt = target_dir / f"{stem}-{index}{suffix}"
        if not alt.exists():
            return alt
    raise RuntimeError(f"Could not allocate a unique import path in {target_dir}")


def _extract_title_from_text(text: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
        return stripped[:120]
    return None


def _extract_html_content(raw_html: str) -> tuple[str | None, str]:
    title_match = None
    import re

    title_match = re.search(r"<title[^>]*>(.*?)</title>", raw_html, re.IGNORECASE | re.DOTALL)
    title = unescape(title_match.group(1)).strip() if title_match else None

    cleaned = re.sub(r"(?is)<(script|style|noscript).*?>.*?</\1>", " ", raw_html)
    cleaned = re.sub(r"(?i)</?(p|div|section|article|main|br|li|ul|ol|h1|h2|h3|h4|h5|h6|tr)>", "\n", cleaned)
    cleaned = re.sub(r"(?s)<[^>]+>", " ", cleaned)
    text = unescape(cleaned)
    lines = [" ".join(line.split()) for line in text.splitlines()]
    body = "\n\n".join(line for line in lines if line)
    return title, body.strip()


def _frontmatter(metadata: dict[str, Any]) -> str:
    lines = ["---"]
    for key, value in metadata.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {json.dumps(str(item), ensure_ascii=False)}")
        else:
            lines.append(f"{key}: {json.dumps(str(value), ensure_ascii=False)}")
    lines.append("---")
    return "\n".join(lines)


def _write_sidecar(target: Path, payload: dict[str, Any]) -> Path:
    sidecar = target.with_name(f"{target.name}.import.json")
    sidecar.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return sidecar


def _looks_like_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def add_url(
    kb_root: str | Path,
    *,
    url: str,
    title: str | None = None,
    slug: str | None = None,
) -> dict[str, Any]:
    root = Path(kb_root).resolve()
    with urlopen(url) as response:
        raw = response.read()
        headers = getattr(response, "headers", None)
        content_type = headers.get_content_type() if headers and hasattr(headers, "get_content_type") else (headers.get("Content-Type", "") if headers else "")
        charset = headers.get_content_charset() if headers and hasattr(headers, "get_content_charset") else None

    decoded = raw.decode(charset or "utf-8", errors="ignore")
    if content_type and "html" in content_type.lower():
        extracted_title, body = _extract_html_content(decoded)
    elif not content_type or content_type.lower().startswith("text/"):
        extracted_title = _extract_title_from_text(decoded)
        body = decoded.strip()
    else:
        raise RuntimeError(f"Unsupported URL content type for add-url: {content_type}")

    parsed = urlparse(url)
    final_title = title or extracted_title or parsed.netloc or "Imported URL"
    final_slug = slug or slugify(final_title)[:80] or "imported-url"
    target = _ensure_unique_path(_imports_root(root, "web"), final_slug, ".md")

    metadata = {
        "title": final_title,
        "source_url": url,
        "source_domain": parsed.netloc,
        "ingested_at": _now_iso(),
        "ingest_type": "url",
        "content_type": content_type or "text/plain",
    }
    content = (
        f"{_frontmatter(metadata)}\n\n"
        f"# {final_title}\n\n"
        f"> Source: {url}\n\n"
        f"{body.strip()}\n"
    )
    target.write_text(content, encoding="utf-8")
    kb_report = write_kb_report(root)
    return {
        "path": str(target),
        "rel_path": target.relative_to(root).as_posix(),
        "title": final_title,
        "source_url": url,
        "kb_report_rel_path": kb_report["rel_path"],
    }


def add_file(
    kb_root: str | Path,
    *,
    file_path: str | Path,
    name: str | None = None,
) -> dict[str, Any]:
    root = Path(kb_root).resolve()
    source = Path(file_path).expanduser().resolve()
    if not source.exists() or not source.is_file():
        raise RuntimeError(f"File not found: {source}")

    stem = slugify(name or source.stem)[:80] or source.stem
    target = _ensure_unique_path(_imports_root(root, "files"), stem, source.suffix)
    shutil.copy2(source, target)
    sidecar = _write_sidecar(
        target,
        {
            "ingest_type": "file",
            "imported_at": _now_iso(),
            "source_path": str(source),
            "source_name": source.name,
            "target_rel_path": target.relative_to(root).as_posix(),
            "size_bytes": source.stat().st_size,
        },
    )
    kb_report = write_kb_report(root)
    return {
        "path": str(target),
        "rel_path": target.relative_to(root).as_posix(),
        "sidecar_path": str(sidecar),
        "sidecar_rel_path": sidecar.relative_to(root).as_posix(),
        "source_path": str(source),
        "kb_report_rel_path": kb_report["rel_path"],
    }


def add_stdin(
    kb_root: str | Path,
    *,
    content: str,
    title: str | None = None,
    slug: str | None = None,
    source_url: str | None = None,
) -> dict[str, Any]:
    root = Path(kb_root).resolve()
    parsed = urlparse(source_url) if source_url else None
    derived_title = title or _extract_title_from_text(content) or (parsed.netloc if parsed else None) or "Imported Text"
    final_slug = slug or slugify(derived_title)[:80] or "imported-text"
    target = _ensure_unique_path(_imports_root(root, "text"), final_slug, ".md")

    metadata = {
        "title": derived_title,
        "ingested_at": _now_iso(),
        "ingest_type": "stdin",
    }
    if source_url:
        metadata["source_url"] = source_url
        metadata["source_domain"] = parsed.netloc if parsed else ""

    body = content.strip()
    if body and not body.lstrip().startswith("#"):
        body = f"# {derived_title}\n\n{body}"
    content_text = f"{_frontmatter(metadata)}\n\n{body.rstrip()}\n"
    target.write_text(content_text, encoding="utf-8")

    kb_report = write_kb_report(root)
    return {
        "path": str(target),
        "rel_path": target.relative_to(root).as_posix(),
        "title": derived_title,
        "source_url": source_url,
        "kb_report_rel_path": kb_report["rel_path"],
    }


def add(
    kb_root: str | Path,
    *,
    input_value: str | None = None,
    mode: str = "auto",
    title: str | None = None,
    slug: str | None = None,
    name: str | None = None,
    source_url: str | None = None,
    stdin_content: str | None = None,
) -> dict[str, Any]:
    normalized_mode = mode
    if normalized_mode == "auto":
        if stdin_content is not None:
            normalized_mode = "stdin"
        elif input_value and _looks_like_url(input_value):
            normalized_mode = "url"
        elif input_value:
            normalized_mode = "file"
        else:
            raise RuntimeError("`add` requires a URL, a file path, or stdin content.")

    if normalized_mode == "url":
        if not input_value:
            raise RuntimeError("`add --mode url` requires a URL input.")
        return add_url(kb_root, url=input_value, title=title, slug=slug)
    if normalized_mode == "file":
        if not input_value:
            raise RuntimeError("`add --mode file` requires a file path input.")
        return add_file(kb_root, file_path=input_value, name=name)
    if normalized_mode == "stdin":
        if stdin_content is None:
            raise RuntimeError("`add --mode stdin` requires content from stdin.")
        return add_stdin(kb_root, content=stdin_content, title=title, slug=slug, source_url=source_url)
    raise RuntimeError(f"Unsupported ingest mode: {mode}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="llm-notes ingest helpers")
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser("add", help="import a URL, local file, or stdin content into the KB")
    add_parser.add_argument("--kb-root")
    add_parser.add_argument("input", nargs="?")
    add_parser.add_argument("--mode", choices=("auto", "url", "file", "stdin"), default="auto")
    add_parser.add_argument("--title")
    add_parser.add_argument("--slug")
    add_parser.add_argument("--name")
    add_parser.add_argument("--source-url")
    add_parser.add_argument("--json", action="store_true")

    add_url_parser = subparsers.add_parser("add-url", help="fetch a web page into imports/web/")
    add_url_parser.add_argument("--kb-root")
    add_url_parser.add_argument("url")
    add_url_parser.add_argument("--title")
    add_url_parser.add_argument("--slug")
    add_url_parser.add_argument("--json", action="store_true")

    add_file_parser = subparsers.add_parser("add-file", help="copy a local file into imports/files/")
    add_file_parser.add_argument("--kb-root")
    add_file_parser.add_argument("file_path")
    add_file_parser.add_argument("--name")
    add_file_parser.add_argument("--json", action="store_true")

    add_stdin_parser = subparsers.add_parser("add-stdin", help="save stdin content into imports/text/")
    add_stdin_parser.add_argument("--kb-root")
    add_stdin_parser.add_argument("--title")
    add_stdin_parser.add_argument("--slug")
    add_stdin_parser.add_argument("--source-url")
    add_stdin_parser.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    kb_root = _resolved_kb_root(getattr(args, "kb_root", None))

    if args.command == "add":
        stdin_content = None
        if args.mode == "stdin" or (args.input is None and not sys.stdin.isatty()):
            stdin_content = sys.stdin.read()
        result = add(
            kb_root,
            input_value=args.input,
            mode=args.mode,
            title=args.title,
            slug=args.slug,
            name=args.name,
            source_url=args.source_url,
            stdin_content=stdin_content,
        )
    elif args.command == "add-url":
        result = add_url(kb_root, url=args.url, title=args.title, slug=args.slug)
    elif args.command == "add-file":
        result = add_file(kb_root, file_path=args.file_path, name=args.name)
    else:
        result = add_stdin(
            kb_root,
            content=sys.stdin.read(),
            title=args.title,
            slug=args.slug,
            source_url=args.source_url,
        )

    if getattr(args, "json", False):
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Imported -> {result['path']}")
        print(f"KB report -> {Path(kb_root) / result['kb_report_rel_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
