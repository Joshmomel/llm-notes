from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from llm_notes.answers import file_answer, finalize_answer, parse_answer, resolve_answer_sources, save_answer
from llm_notes.lint import run_lint
from llm_notes.wiki import read_article, serialize_article


class AnswerTests(unittest.TestCase):
    def test_save_answer_creates_pending_note(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_root = Path(tmpdir)
            (kb_root / "wiki").mkdir()

            note_path = save_answer(
                kb_root,
                question="How do transformers scale to long context?",
                body="# Long Context\n\n## Main Conclusion\n\nThey rely on attention variants.",
                sources_consulted=["wiki/ml/attention.md"],
                retrieval_mode="wiki_only",
                retrieval_trace=["wiki:ml/attention.md"],
            )

            answer = parse_answer(note_path, kb_root)
            self.assertEqual(answer.question, "How do transformers scale to long context?")
            self.assertEqual(answer.filing_status, "pending")
            self.assertFalse(answer.filed_to_wiki)
            self.assertEqual(answer.retrieval_mode, "wiki_only")
            self.assertEqual(answer.retrieval_trace, ["wiki:ml/attention.md"])
            self.assertEqual(answer.sources_consulted, ["wiki/ml/attention.md"])

    def test_resolve_answer_sources_reads_wiki_article_sources(self) -> None:
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
                    "Body",
                ),
                encoding="utf-8",
            )

            note_path = save_answer(
                kb_root,
                question="What matters for long context?",
                body="# Q\n\n## Main Conclusion\n\nRead [[ml/attention]].",
                sources_consulted=["wiki/ml/attention.md"],
            )
            answer = parse_answer(note_path, kb_root)

            self.assertEqual(
                resolve_answer_sources(kb_root, answer),
                ["notes/attention.md", "notes/kv-cache.md"],
            )

    def test_file_answer_creates_new_article_from_answer(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_root = Path(tmpdir)
            wiki_dir = kb_root / "wiki" / "ml"
            wiki_dir.mkdir(parents=True)
            (kb_root / "notes").mkdir()
            (kb_root / "notes" / "attention.md").write_text("# Attention\n\nBody", encoding="utf-8")
            (kb_root / "notes" / "direct.md").write_text("# Direct\n\nBody", encoding="utf-8")
            (wiki_dir / "attention.md").write_text(
                serialize_article(
                    {
                        "title": "Attention",
                        "created": "2026-04-11",
                        "updated": "2026-04-11",
                        "sources": ["notes/attention.md"],
                        "tags": ["attention"],
                    },
                    "## Summary\n\nAttention article.",
                ),
                encoding="utf-8",
            )

            note_path = save_answer(
                kb_root,
                question="What are the tradeoffs of long-context attention?",
                body=(
                    "# What are the tradeoffs of long-context attention?\n\n"
                    "## Main Conclusion\n\n"
                    "Long-context systems trade compute, memory, and retrieval complexity.\n\n"
                    "## Knowledge Network Extension\n\n"
                    "- [[ml/attention]] — the baseline mechanism to compare against.\n\n"
                    "## Deep-Dive Threads\n\n"
                    "- Quantify when KV cache stops being the bottleneck.\n\n"
                    "## Further Questions\n\n"
                    "- Which compression schemes preserve retrieval quality best?\n\n"
                    "## Gaps Identified\n\n"
                    "- No benchmark coverage for multi-hour contexts."
                ),
                sources_consulted=["wiki/ml/attention.md", "notes/direct.md"],
            )

            result = file_answer(
                kb_root,
                answer_path=note_path,
                mode="new",
                title="Long-Context Attention Tradeoffs",
                category="synthesis",
                tags=["attention", "long-context"],
            )

            article = read_article(result["article_path"], kb_root)
            answer = parse_answer(note_path, kb_root)

            self.assertEqual(result["status"], "created")
            self.assertEqual(article.metadata["sources"], ["notes/attention.md", "notes/direct.md"])
            self.assertIn("derived_from_outputs", article.metadata)
            self.assertIn(answer.rel_path, article.metadata["derived_from_outputs"])
            self.assertTrue(answer.filed_to_wiki)
            self.assertEqual(answer.filing_status, "filed")
            self.assertEqual(answer.filed_wikilinks, [result["wikilink"]])
            self.assertIn("Derived insight from", article.body)

    def test_file_answer_auto_enriches_existing_article(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_root = Path(tmpdir)
            wiki_dir = kb_root / "wiki" / "ml"
            wiki_dir.mkdir(parents=True)
            (kb_root / "notes").mkdir()
            (kb_root / "notes" / "attention.md").write_text("# Attention\n\nBody", encoding="utf-8")
            article_path = wiki_dir / "attention.md"
            article_path.write_text(
                serialize_article(
                    {
                        "title": "Attention",
                        "created": "2026-04-11",
                        "updated": "2026-04-11",
                        "sources": ["notes/attention.md"],
                        "tags": ["attention"],
                    },
                    "## Summary\n\nAttention article.",
                ),
                encoding="utf-8",
            )

            note_path = save_answer(
                kb_root,
                question="How should we extend the attention article?",
                body=(
                    "# Extend\n\n"
                    "## Main Conclusion\n\n"
                    "Add a comparison between dense attention and retrieval augmentation.\n\n"
                    "## Knowledge Network Extension\n\n"
                    "- [[ml/attention]] — should become the landing page for this topic.\n\n"
                    "## Further Questions\n\n"
                    "- Which retrieval policy degrades least under long contexts?"
                ),
                sources_consulted=["wiki/ml/attention.md"],
                metadata={
                    "promotion_mode": "enrich",
                    "promotion_targets": ["ml/attention"],
                },
            )

            result = file_answer(kb_root, answer_path=note_path, mode="auto")
            updated = read_article(article_path, kb_root)
            answer = parse_answer(note_path, kb_root)

            self.assertEqual(result["wikilink"], "ml/attention")
            self.assertIn("## Filed Insights", updated.body)
            self.assertIn("### Filed Insight", updated.body)
            self.assertIn("How should we extend the attention article?", updated.body)
            self.assertIn(answer.rel_path, updated.metadata["derived_from_outputs"])
            self.assertEqual(answer.filed_wikilinks, ["ml/attention"])

    def test_finalize_answer_auto_files_and_refreshes_lint(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_root = Path(tmpdir)
            wiki_dir = kb_root / "wiki" / "ml"
            wiki_dir.mkdir(parents=True)
            (kb_root / "notes").mkdir()
            (kb_root / "notes" / "attention.md").write_text("# Attention\n\nBody", encoding="utf-8")
            (kb_root / "notes" / "retrieval.md").write_text("# Retrieval\n\nBody", encoding="utf-8")
            (wiki_dir / "attention.md").write_text(
                serialize_article(
                    {
                        "title": "Attention",
                        "created": "2026-04-11",
                        "updated": "2026-04-11",
                        "sources": ["notes/attention.md"],
                        "tags": ["attention"],
                    },
                    "## Summary\n\nAttention article.",
                ),
                encoding="utf-8",
            )

            result = finalize_answer(
                kb_root,
                question="How do dense attention and retrieval compare for long context?",
                body=(
                    "# Compare\n\n"
                    "## Main Conclusion\n\n"
                    "Dense attention and retrieval trade off memory, latency, and coverage across multiple sources in ways that should be captured as reusable synthesis for the KB.\n\n"
                    "## Knowledge Network Extension\n\n"
                    "- [[ml/attention]] — baseline mechanism.\n\n"
                    "## Further Questions\n\n"
                    "- Which workloads favor retrieval over dense extension?\n"
                    "- Which benchmark suite is missing long-context cases?"
                ),
                sources_consulted=["wiki/ml/attention.md", "notes/retrieval.md"],
                retrieval_mode="hybrid",
                retrieval_trace=["wiki:ml/attention.md", "source:notes/retrieval.md#chunk-001"],
                title="Attention vs Retrieval for Long Context",
                category="synthesis",
                tags=["attention", "retrieval"],
            )

            answer = parse_answer(result["answer_path"], kb_root)
            lint_state = run_lint(kb_root)

            self.assertTrue(answer.filed_to_wiki)
            self.assertEqual(answer.retrieval_mode, "hybrid")
            self.assertEqual(
                answer.retrieval_trace,
                ["source:notes/retrieval.md#chunk-001", "wiki:ml/attention.md"],
            )
            self.assertEqual(result["assessment"]["action"], "new")
            self.assertIsNotNone(result["filing_result"])
            self.assertIsNotNone(result["lint_result"])
            self.assertEqual(result["kb_report"]["rel_path"], "outputs/KB_REPORT.md")
            self.assertTrue((kb_root / result["kb_report"]["rel_path"]).exists())
            self.assertTrue((kb_root / "outputs" / "lint-report.md").exists())
            self.assertEqual(lint_state["stats"].high_value_pending_answers, 0)

    def test_finalize_answer_keeps_low_value_answer_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_root = Path(tmpdir)
            (kb_root / "wiki").mkdir()
            (kb_root / "notes.md").write_text("# Note\n\nBody", encoding="utf-8")

            result = finalize_answer(
                kb_root,
                question="What file exists here?",
                body="# What file exists here?\n\n## Main Conclusion\n\n`notes.md` exists.",
                sources_consulted=["notes.md"],
            )

            answer = parse_answer(result["answer_path"], kb_root)
            lint_state = run_lint(kb_root)

            self.assertFalse(answer.filed_to_wiki)
            self.assertEqual(result["assessment"]["action"], "pending")
            self.assertIsNone(result["filing_result"])
            self.assertEqual(result["kb_report"]["rel_path"], "outputs/KB_REPORT.md")
            self.assertTrue((kb_root / result["kb_report"]["rel_path"]).exists())
            self.assertTrue((kb_root / "outputs" / "lint-report.md").exists())
            self.assertEqual(lint_state["stats"].pending_answers, 1)

    def test_finalize_answer_auto_uses_enrich_recommendation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_root = Path(tmpdir)
            wiki_dir = kb_root / "wiki" / "ml"
            wiki_dir.mkdir(parents=True)
            (kb_root / "notes").mkdir()
            (kb_root / "notes" / "attention.md").write_text("# Attention\n\nBody", encoding="utf-8")
            article_path = wiki_dir / "attention.md"
            article_path.write_text(
                serialize_article(
                    {
                        "title": "Attention",
                        "created": "2026-04-11",
                        "updated": "2026-04-11",
                        "sources": ["notes/attention.md"],
                        "tags": ["attention"],
                    },
                    "## Summary\n\nAttention article.",
                ),
                encoding="utf-8",
            )

            result = finalize_answer(
                kb_root,
                question="What should be added to the attention page?",
                body=(
                    "# Extend attention\n\n"
                    "## Main Conclusion\n\n"
                    "The attention page should add a dense-vs-retrieval tradeoff section with explicit caveats.\n\n"
                    "## Knowledge Network Extension\n\n"
                    "- [[ml/attention]] — primary landing page for this synthesis.\n\n"
                    "## Further Questions\n\n"
                    "- Which workloads still favor dense attention?"
                ),
                sources_consulted=["wiki/ml/attention.md"],
                metadata={"promotion_mode": "enrich", "promotion_targets": ["ml/attention"]},
            )

            updated = read_article(article_path, kb_root)
            answer = parse_answer(result["answer_path"], kb_root)

            self.assertEqual(result["assessment"]["action"], "enrich")
            self.assertEqual(result["assessment"]["candidate_article"], "ml/attention")
            self.assertTrue(answer.filed_to_wiki)
            self.assertIn("## Filed Insights", updated.body)
            self.assertTrue((kb_root / result["kb_report"]["rel_path"]).exists())


if __name__ == "__main__":
    unittest.main()
