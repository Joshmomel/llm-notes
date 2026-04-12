from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from llm_notes.claude import claude_install, claude_status, claude_uninstall


class ClaudeIntegrationTests(unittest.TestCase):
    def test_claude_install_writes_section_and_hook(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_root = Path(tmpdir)
            (kb_root / "wiki").mkdir()

            result = claude_install(kb_root)

            claude_md = Path(result["claude_md"])
            settings = Path(result["settings"])
            self.assertTrue(claude_md.exists())
            self.assertTrue(settings.exists())
            self.assertIn("## llm-notes", claude_md.read_text(encoding="utf-8"))

            payload = json.loads(settings.read_text(encoding="utf-8"))
            hooks = payload["hooks"]["PreToolUse"]
            self.assertEqual(len(hooks), 1)
            self.assertEqual(hooks[0]["matcher"], "Bash|Glob|Grep")
            self.assertIn("llm-notes", json.dumps(hooks[0]))

    def test_claude_install_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_root = Path(tmpdir)
            (kb_root / "wiki").mkdir()

            claude_install(kb_root)
            claude_install(kb_root)

            claude_md = (kb_root / "CLAUDE.md").read_text(encoding="utf-8")
            settings = json.loads((kb_root / ".claude" / "settings.json").read_text(encoding="utf-8"))

            self.assertEqual(claude_md.count("## llm-notes"), 1)
            self.assertEqual(len(settings["hooks"]["PreToolUse"]), 1)

    def test_claude_uninstall_removes_only_llm_notes_bits(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_root = Path(tmpdir)
            (kb_root / "wiki").mkdir()
            (kb_root / "CLAUDE.md").write_text("# Knowledge Base\n\n## Existing\n\nkeep me\n", encoding="utf-8")
            settings_path = kb_root / ".claude" / "settings.json"
            settings_path.parent.mkdir(parents=True)
            settings_path.write_text(
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

            claude_install(kb_root)
            claude_uninstall(kb_root)

            claude_md = (kb_root / "CLAUDE.md").read_text(encoding="utf-8")
            settings = json.loads(settings_path.read_text(encoding="utf-8"))

            self.assertNotIn("## llm-notes", claude_md)
            self.assertIn("## Existing", claude_md)
            self.assertEqual(len(settings["hooks"]["PreToolUse"]), 1)
            self.assertEqual(settings["hooks"]["PreToolUse"][0]["matcher"], "Read")

    def test_claude_status_reports_installation_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_root = Path(tmpdir)
            (kb_root / "wiki").mkdir()

            before = claude_status(kb_root)
            self.assertFalse(before["has_claude_section"])
            self.assertFalse(before["has_pre_tool_hook"])

            claude_install(kb_root)

            after = claude_status(kb_root)
            self.assertTrue(after["has_claude_section"])
            self.assertTrue(after["has_pre_tool_hook"])


if __name__ == "__main__":
    unittest.main()
