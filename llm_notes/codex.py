"""Project-local Codex control-plane helpers for llm-notes KBs."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from llm_notes.compile import find_kb_root

_AGENTS_MD_MARKER = "## llm-notes"
_AGENTS_MD_SECTION = """\
## llm-notes

This directory is an `llm-notes` knowledge base.

Rules:
- For knowledge-oriented questions, save the answer note first with `python3 -m llm_notes.answers save --kb-root . ...`.
- If the answer is reusable synthesis, immediately promote it with `python3 -m llm_notes.answers file --kb-root . --answer <path> --mode auto`.
- Treat `outputs/answers/` as the audit layer, not as canonical source material. When filing back into the wiki, prefer canonical source files and existing wiki articles.
- If an answer remains pending instead of being filed, refresh the queue with `python3 -m llm_notes.lint --kb-root .`.
"""

_HOOK_CONTEXT = (
    "llm-notes: This is a knowledge-base repo. For knowledge-oriented work, save answers to "
    "outputs/answers with `python3 -m llm_notes.answers save`, then promote reusable synthesis "
    "with `python3 -m llm_notes.answers file --mode auto`. Prefer canonical sources over outputs "
    "when updating the wiki."
)

_CODEX_HOOK = {
    "hooks": {
        "PreToolUse": [
            {
                "matcher": "Bash",
                "hooks": [
                    {
                        "type": "command",
                        "command": (
                            "[ -d wiki ] && "
                            + r"""echo '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"allow"},"systemMessage":"llm-notes: This is a knowledge-base repo. For knowledge-oriented work, save answers to outputs/answers with `python3 -m llm_notes.answers save`, then promote reusable synthesis with `python3 -m llm_notes.answers file --mode auto`. Prefer canonical sources over outputs when updating the wiki."}' """
                            + "|| true"
                        ),
                    }
                ],
            }
        ]
    }
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


def _upsert_agents_section(content: str) -> str:
    if _AGENTS_MD_MARKER in content:
        cleaned = re.sub(
            r"\n*## llm-notes\n.*?(?=\n## |\Z)",
            "",
            content,
            flags=re.DOTALL,
        ).rstrip()
        return (cleaned + "\n\n" + _AGENTS_MD_SECTION).strip() + "\n"
    if not content.strip():
        return _AGENTS_MD_SECTION
    return content.rstrip() + "\n\n" + _AGENTS_MD_SECTION


def _remove_agents_section(content: str) -> str:
    if _AGENTS_MD_MARKER not in content:
        return content
    cleaned = re.sub(
        r"\n*## llm-notes\n.*?(?=\n## |\Z)",
        "",
        content,
        flags=re.DOTALL,
    ).rstrip()
    return (cleaned + "\n") if cleaned else ""


def _install_codex_hook(project_dir: Path) -> Path:
    hooks_path = project_dir / ".codex" / "hooks.json"
    hooks_path.parent.mkdir(parents=True, exist_ok=True)

    if hooks_path.exists():
        try:
            existing = json.loads(hooks_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
    else:
        existing = {}

    pre_tool = existing.setdefault("hooks", {}).setdefault("PreToolUse", [])
    existing["hooks"]["PreToolUse"] = [hook for hook in pre_tool if "llm-notes" not in str(hook)]
    existing["hooks"]["PreToolUse"].extend(_CODEX_HOOK["hooks"]["PreToolUse"])
    hooks_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    return hooks_path


def _uninstall_codex_hook(project_dir: Path) -> Path | None:
    hooks_path = project_dir / ".codex" / "hooks.json"
    if not hooks_path.exists():
        return None
    try:
        existing = json.loads(hooks_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None

    pre_tool = existing.get("hooks", {}).get("PreToolUse", [])
    filtered = [hook for hook in pre_tool if "llm-notes" not in str(hook)]
    if len(filtered) == len(pre_tool):
        return None

    existing.setdefault("hooks", {})["PreToolUse"] = filtered
    hooks_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    return hooks_path


def codex_install(kb_root: str | Path | None = None) -> dict[str, str]:
    root = _resolved_kb_root(kb_root)
    agents_path = root / "AGENTS.md"
    existing = agents_path.read_text(encoding="utf-8") if agents_path.exists() else ""
    agents_path.write_text(_upsert_agents_section(existing), encoding="utf-8")
    hooks_path = _install_codex_hook(root)
    return {
        "kb_root": str(root),
        "agents_md": str(agents_path),
        "hooks": str(hooks_path),
    }


def codex_uninstall(kb_root: str | Path | None = None) -> dict[str, str | None]:
    root = _resolved_kb_root(kb_root)
    agents_path = root / "AGENTS.md"
    if agents_path.exists():
        cleaned = _remove_agents_section(agents_path.read_text(encoding="utf-8"))
        if cleaned:
            agents_path.write_text(cleaned, encoding="utf-8")
        else:
            agents_path.unlink()
    hooks_path = _uninstall_codex_hook(root)
    return {
        "kb_root": str(root),
        "agents_md": str(agents_path) if agents_path.exists() else None,
        "hooks": str(hooks_path) if hooks_path is not None else None,
    }


def codex_status(kb_root: str | Path | None = None) -> dict[str, object]:
    root = _resolved_kb_root(kb_root)
    agents_path = root / "AGENTS.md"
    hooks_path = root / ".codex" / "hooks.json"

    has_section = False
    if agents_path.exists():
        has_section = _AGENTS_MD_MARKER in agents_path.read_text(encoding="utf-8")

    has_hook = False
    if hooks_path.exists():
        try:
            settings = json.loads(hooks_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            settings = {}
        for hook in settings.get("hooks", {}).get("PreToolUse", []):
            if hook.get("matcher") == "Bash" and "llm-notes" in str(hook):
                has_hook = True
                break

    return {
        "kb_root": str(root),
        "agents_md": str(agents_path),
        "hooks": str(hooks_path),
        "has_agents_section": has_section,
        "has_pre_tool_hook": has_hook,
        "hook_context": _HOOK_CONTEXT,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="llm-notes Codex project helpers")
    parser.add_argument("command", choices=("install", "uninstall", "status"))
    parser.add_argument("--kb-root")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "install":
        result = codex_install(args.kb_root)
    elif args.command == "uninstall":
        result = codex_uninstall(args.kb_root)
    else:
        result = codex_status(args.kb_root)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if args.command == "status":
            print(f"KB root: {result['kb_root']}")
            print(f"AGENTS.md section: {'present' if result['has_agents_section'] else 'missing'}")
            print(f"PreToolUse hook: {'present' if result['has_pre_tool_hook'] else 'missing'}")
            print(f"AGENTS.md: {result['agents_md']}")
            print(f"Hooks: {result['hooks']}")
        else:
            print(f"KB root: {result['kb_root']}")
            print(f"AGENTS.md: {result['agents_md']}")
            print(f"Hooks: {result['hooks']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
