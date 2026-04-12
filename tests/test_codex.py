from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from llm_notes.codex import codex_install, codex_status, codex_uninstall


class CodexIntegrationTests(unittest.TestCase):
    def test_codex_install_writes_section_and_hook(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_root = Path(tmpdir)
            (kb_root / "wiki").mkdir()

            result = codex_install(kb_root)

            agents_md = Path(result["agents_md"])
            hooks = Path(result["hooks"])
            self.assertTrue(agents_md.exists())
            self.assertTrue(hooks.exists())
            self.assertIn("## llm-notes", agents_md.read_text(encoding="utf-8"))

            payload = json.loads(hooks.read_text(encoding="utf-8"))
            pre_tool = payload["hooks"]["PreToolUse"]
            self.assertEqual(len(pre_tool), 1)
            self.assertEqual(pre_tool[0]["matcher"], "Bash")
            self.assertIn("llm-notes", json.dumps(pre_tool[0]))

    def test_codex_install_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_root = Path(tmpdir)
            (kb_root / "wiki").mkdir()

            codex_install(kb_root)
            codex_install(kb_root)

            agents_md = (kb_root / "AGENTS.md").read_text(encoding="utf-8")
            hooks = json.loads((kb_root / ".codex" / "hooks.json").read_text(encoding="utf-8"))

            self.assertEqual(agents_md.count("## llm-notes"), 1)
            self.assertEqual(len(hooks["hooks"]["PreToolUse"]), 1)

    def test_codex_uninstall_removes_only_llm_notes_bits(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_root = Path(tmpdir)
            (kb_root / "wiki").mkdir()
            (kb_root / "AGENTS.md").write_text("# Project\n\n## Existing\n\nkeep me\n", encoding="utf-8")
            hooks_path = kb_root / ".codex" / "hooks.json"
            hooks_path.parent.mkdir(parents=True)
            hooks_path.write_text(
                json.dumps(
                    {
                        "hooks": {
                            "PreToolUse": [
                                {
                                    "matcher": "Read",
                                    "hooks": [{"type": "command", "command": "echo keep"}],
                                }
                            ]
                        }
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            codex_install(kb_root)
            codex_uninstall(kb_root)

            agents_md = (kb_root / "AGENTS.md").read_text(encoding="utf-8")
            hooks = json.loads(hooks_path.read_text(encoding="utf-8"))

            self.assertNotIn("## llm-notes", agents_md)
            self.assertIn("## Existing", agents_md)
            self.assertEqual(len(hooks["hooks"]["PreToolUse"]), 1)
            self.assertEqual(hooks["hooks"]["PreToolUse"][0]["matcher"], "Read")

    def test_codex_status_reports_installation_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_root = Path(tmpdir)
            (kb_root / "wiki").mkdir()

            before = codex_status(kb_root)
            self.assertFalse(before["has_agents_section"])
            self.assertFalse(before["has_pre_tool_hook"])

            codex_install(kb_root)

            after = codex_status(kb_root)
            self.assertTrue(after["has_agents_section"])
            self.assertTrue(after["has_pre_tool_hook"])


if __name__ == "__main__":
    unittest.main()
