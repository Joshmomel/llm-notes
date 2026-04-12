from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from llm_notes.answers import file_answer, save_answer
from llm_notes.lint import run_lint, write_report
from llm_notes.wiki import serialize_article


class LintTests(unittest.TestCase):
    def test_lint_flags_high_value_pending_answer(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_root = Path(tmpdir)
            wiki_dir = kb_root / "wiki" / "ml"
            wiki_dir.mkdir(parents=True)
            (kb_root / "notes").mkdir()
            (kb_root / "notes" / "attention.md").write_text("# Attention\n\nBody", encoding="utf-8")
            (kb_root / "notes" / "kv-cache.md").write_text("# KV Cache\n\nBody", encoding="utf-8")
            (wiki_dir / "attention.md").write_text(
                serialize_article(
                    {
                        "title": "Attention",
                        "created": "2026-04-11",
                        "updated": "2026-04-11",
                        "sources": ["notes/attention.md", "notes/kv-cache.md"],
                        "tags": ["attention"],
                    },
                    "## Summary\n\nAttention article.",
                ),
                encoding="utf-8",
            )

            save_answer(
                kb_root,
                question="What tradeoffs emerge in long-context attention?",
                body=(
                    "# Tradeoffs\n\n"
                    "## Main Conclusion\n\n"
                    "Long-context attention shifts bottlenecks from pure context length toward memory traffic, retrieval latency, and update policy across multiple components.\n\n"
                    "## Knowledge Network Extension\n\n"
                    "- [[ml/attention]] — baseline mechanism.\n"
                    "- [[ml/kv-cache]] — likely follow-up target.\n\n"
                    "## Further Questions\n\n"
                    "- Which workloads remain dominated by KV cache bandwidth?\n"
                    "- When does retrieval beat dense extension?"
                ),
                sources_consulted=["wiki/ml/attention.md", "notes/kv-cache.md"],
            )

            result = run_lint(kb_root)
            self.assertEqual(result["stats"].high_value_pending_answers, 1)
            self.assertTrue(any(issue.category == "pending answer worth filing" for issue in result["issues"]))
            self.assertGreaterEqual(result["health_score"], 0)

    def test_lint_report_writes_markdown_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_root = Path(tmpdir)
            (kb_root / "wiki").mkdir()

            report = write_report(kb_root)
            report_path = kb_root / report["rel_path"]

            self.assertTrue(report_path.exists())
            content = report_path.read_text(encoding="utf-8")
            self.assertIn("# KB Health Report", content)
            self.assertIn("## Answer Filing Queue", content)

    def test_lint_fix_regenerates_indexes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_root = Path(tmpdir)
            wiki_dir = kb_root / "wiki" / "ml"
            wiki_dir.mkdir(parents=True)
            (kb_root / "notes.md").write_text("# Notes\n\nBody", encoding="utf-8")
            (wiki_dir / "attention.md").write_text(
                serialize_article(
                    {
                        "title": "Attention",
                        "created": "2026-04-11",
                        "updated": "2026-04-11",
                        "sources": ["notes.md"],
                        "tags": ["attention"],
                    },
                    "## Summary\n\nBody",
                ),
                encoding="utf-8",
            )

            result = write_report(kb_root, fix=True)
            self.assertTrue((kb_root / "wiki" / "_index.md").exists())
            self.assertTrue((kb_root / "wiki" / "ml" / "_index.md").exists())
            self.assertTrue(result["auto_fixed"])

    def test_lint_warns_when_filed_answer_target_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_root = Path(tmpdir)
            wiki_dir = kb_root / "wiki" / "ml"
            wiki_dir.mkdir(parents=True)
            (kb_root / "notes.md").write_text("# Notes\n\nBody", encoding="utf-8")
            article_path = wiki_dir / "attention.md"
            article_path.write_text(
                serialize_article(
                    {
                        "title": "Attention",
                        "created": "2026-04-11",
                        "updated": "2026-04-11",
                        "sources": ["notes.md"],
                        "tags": ["attention"],
                    },
                    "## Summary\n\nBody",
                ),
                encoding="utf-8",
            )

            answer_path = save_answer(
                kb_root,
                question="What should be filed?",
                body="# Filed\n\n## Main Conclusion\n\nSomething reusable.",
                sources_consulted=["wiki/ml/attention.md"],
                metadata={"promotion_mode": "enrich", "promotion_targets": ["ml/attention"]},
            )
            file_answer(kb_root, answer_path=answer_path, mode="auto")
            article_path.unlink()

            result = run_lint(kb_root)
            self.assertTrue(any(issue.category == "filed answer target missing" for issue in result["issues"]))


if __name__ == "__main__":
    unittest.main()
