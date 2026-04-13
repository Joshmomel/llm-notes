from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from llm_notes.answers import save_answer
from llm_notes.chat import create_chat_session, register_chat_artifacts
from llm_notes.report import build_report_payload, write_report
from llm_notes.wiki import serialize_article


class ReportTests(unittest.TestCase):
    def _write_article(
        self,
        path: Path,
        *,
        title: str,
        sources: list[str],
        tags: list[str],
        body: str,
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            serialize_article(
                {
                    "title": title,
                    "created": "2026-04-11",
                    "updated": "2026-04-11",
                    "sources": sources,
                    "tags": tags,
                },
                body,
            ),
            encoding="utf-8",
        )

    def test_build_report_payload_summarizes_kb_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_root = Path(tmpdir)
            wiki_dir = kb_root / "wiki" / "ml"
            wiki_dir.mkdir(parents=True)
            (kb_root / "notes").mkdir()
            (kb_root / "notes" / "attention.md").write_text("# Attention\n\nBody", encoding="utf-8")
            (kb_root / "notes" / "retrieval.md").write_text("# Retrieval\n\nBody", encoding="utf-8")
            self._write_article(
                wiki_dir / "attention.md",
                title="Attention",
                sources=["notes/attention.md"],
                tags=["attention"],
                body="## Summary\n\nBody",
            )
            answer_path = save_answer(
                kb_root,
                question="What belongs on the attention page?",
                body="# Extend\n\n## Main Conclusion\n\nAdd tradeoffs.\n",
                sources_consulted=["wiki/ml/attention.md"],
                metadata={"promotion_mode": "enrich", "promotion_targets": ["ml/attention"]},
            )
            session_path = create_chat_session(
                kb_root,
                title="Attention Session",
                focus="Track long-context tradeoffs",
                created_at="2026-04-12T09:00:00",
            )
            register_chat_artifacts(
                kb_root,
                session_path=session_path,
                answer_paths=[answer_path],
                updated_at="2026-04-12T09:10:00",
            )

            payload = build_report_payload(kb_root)

            self.assertEqual(payload["snapshot"]["articles"], 1)
            self.assertEqual(payload["snapshot"]["answers_total"], 1)
            self.assertEqual(payload["snapshot"]["active_sessions"], 1)
            self.assertTrue(payload["pending_filing"])
            self.assertTrue(payload["active_sessions"])
            self.assertTrue(payload["next_actions"])

    def test_write_report_outputs_markdown_dashboard(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_root = Path(tmpdir)
            (kb_root / "wiki").mkdir()

            result = write_report(kb_root)
            report_path = Path(result["path"])
            content = report_path.read_text(encoding="utf-8")

            self.assertTrue(report_path.exists())
            self.assertEqual(result["rel_path"], "outputs/KB_REPORT.md")
            self.assertIn("# KB Report", content)
            self.assertIn("## Snapshot", content)
            self.assertIn("## Pending Filing", content)
            self.assertIn("## Semantic Hotspots", content)
            self.assertIn("## Active Sessions", content)
            self.assertIn("## Next Actions", content)


if __name__ == "__main__":
    unittest.main()
