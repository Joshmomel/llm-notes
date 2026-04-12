"""Project-local Claude Code control-plane helpers for llm-notes KBs."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from llm_notes.compile import find_kb_root

_CLAUDE_MD_MARKER = "## llm-notes"
_CLAUDE_MD_SECTION = """\
## llm-notes

This directory is an `llm-notes` knowledge base.

Rules:
- For knowledge-oriented questions, prefer the single-step finisher: `python3 -m llm_notes.answers finalize --kb-root . ...`.
- `finalize` saves the answer note, auto-files reusable synthesis, and refreshes `outputs/lint-report.md`.
- Treat `outputs/answers/` as the audit layer, not as canonical source material. When filing back into the wiki, prefer canonical source files and existing wiki articles.
- If a pending answer still needs semantic review, refresh the semantic shortlist with `python3 -m llm_notes.semantic_lint --kb-root .`.
"""

_HOOK_CONTEXT = (
    "llm-notes: This is a knowledge-base repo. For knowledge-oriented work, save answers to "
    "outputs/answers with `python3 -m llm_notes.answers finalize`. That command also auto-files "
    "reusable synthesis and refreshes lint state. Prefer canonical sources over outputs when "
    "updating the wiki."
)

_SETTINGS_HOOK = {
    "matcher": "Bash|Glob|Grep",
    "hooks": [
        {
            "type": "command",
            "command": (
                "[ -d wiki ] && "
                + r"""echo '{"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":"llm-notes: This is a knowledge-base repo. For knowledge-oriented work, save answers to outputs/answers with `python3 -m llm_notes.answers finalize`. That command also auto-files reusable synthesis and refreshes lint state. Prefer canonical sources over outputs when updating the wiki."}}' """
                + "|| true"
            ),
        }
    ],
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


def _upsert_claude_section(content: str) -> str:
    if _CLAUDE_MD_MARKER in content:
        cleaned = re.sub(
            r"\n*## llm-notes\n.*?(?=\n## |\Z)",
            "",
            content,
            flags=re.DOTALL,
        ).rstrip()
        return (cleaned + "\n\n" + _CLAUDE_MD_SECTION).strip() + "\n"
    if not content.strip():
        return _CLAUDE_MD_SECTION
    return content.rstrip() + "\n\n" + _CLAUDE_MD_SECTION


def _remove_claude_section(content: str) -> str:
    if _CLAUDE_MD_MARKER not in content:
        return content
    cleaned = re.sub(
        r"\n*## llm-notes\n.*?(?=\n## |\Z)",
        "",
        content,
        flags=re.DOTALL,
    ).rstrip()
    return (cleaned + "\n") if cleaned else ""


def _install_claude_hook(project_dir: Path) -> Path:
    settings_path = project_dir / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)

    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            settings = {}
    else:
        settings = {}

    hooks = settings.setdefault("hooks", {})
    pre_tool = hooks.setdefault("PreToolUse", [])
    hooks["PreToolUse"] = [
        hook
        for hook in pre_tool
        if not (hook.get("matcher") == "Bash|Glob|Grep" and "llm-notes" in str(hook))
    ]
    hooks["PreToolUse"].append(_SETTINGS_HOOK)
    settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    return settings_path


def _uninstall_claude_hook(project_dir: Path) -> Path | None:
    settings_path = project_dir / ".claude" / "settings.json"
    if not settings_path.exists():
        return None
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None

    pre_tool = settings.get("hooks", {}).get("PreToolUse", [])
    filtered = [
        hook
        for hook in pre_tool
        if not (hook.get("matcher") == "Bash|Glob|Grep" and "llm-notes" in str(hook))
    ]
    if len(filtered) == len(pre_tool):
        return None

    settings.setdefault("hooks", {})["PreToolUse"] = filtered
    settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    return settings_path


def claude_install(kb_root: str | Path | None = None) -> dict[str, str]:
    root = _resolved_kb_root(kb_root)
    claude_md_path = root / "CLAUDE.md"
    existing = claude_md_path.read_text(encoding="utf-8") if claude_md_path.exists() else ""
    claude_md_path.write_text(_upsert_claude_section(existing), encoding="utf-8")
    settings_path = _install_claude_hook(root)
    return {
        "kb_root": str(root),
        "claude_md": str(claude_md_path),
        "settings": str(settings_path),
    }


def claude_uninstall(kb_root: str | Path | None = None) -> dict[str, str | None]:
    root = _resolved_kb_root(kb_root)
    claude_md_path = root / "CLAUDE.md"
    if claude_md_path.exists():
        cleaned = _remove_claude_section(claude_md_path.read_text(encoding="utf-8"))
        if cleaned:
            claude_md_path.write_text(cleaned, encoding="utf-8")
        else:
            claude_md_path.unlink()
    settings_path = _uninstall_claude_hook(root)
    return {
        "kb_root": str(root),
        "claude_md": str(claude_md_path) if claude_md_path.exists() else None,
        "settings": str(settings_path) if settings_path is not None else None,
    }


def claude_status(kb_root: str | Path | None = None) -> dict[str, object]:
    root = _resolved_kb_root(kb_root)
    claude_md_path = root / "CLAUDE.md"
    settings_path = root / ".claude" / "settings.json"

    has_section = False
    if claude_md_path.exists():
        has_section = _CLAUDE_MD_MARKER in claude_md_path.read_text(encoding="utf-8")

    has_hook = False
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            settings = {}
        for hook in settings.get("hooks", {}).get("PreToolUse", []):
            if hook.get("matcher") == "Bash|Glob|Grep" and "llm-notes" in str(hook):
                has_hook = True
                break

    return {
        "kb_root": str(root),
        "claude_md": str(claude_md_path),
        "settings": str(settings_path),
        "has_claude_section": has_section,
        "has_pre_tool_hook": has_hook,
        "hook_context": _HOOK_CONTEXT,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="llm-notes Claude Code project helpers")
    parser.add_argument("command", choices=("install", "uninstall", "status"))
    parser.add_argument("--kb-root")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "install":
        result = claude_install(args.kb_root)
    elif args.command == "uninstall":
        result = claude_uninstall(args.kb_root)
    else:
        result = claude_status(args.kb_root)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if args.command == "status":
            print(f"KB root: {result['kb_root']}")
            print(f"CLAUDE.md section: {'present' if result['has_claude_section'] else 'missing'}")
            print(f"PreToolUse hook: {'present' if result['has_pre_tool_hook'] else 'missing'}")
            print(f"CLAUDE.md: {result['claude_md']}")
            print(f"Settings: {result['settings']}")
        else:
            print(f"KB root: {result['kb_root']}")
            print(f"CLAUDE.md: {result['claude_md']}")
            print(f"Settings: {result['settings']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
