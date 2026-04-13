from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from llm_notes.retrieval import (
    build_source_index,
    consulted_sources_from_retrieval,
    query_retrieval,
    search_source_index,
    suggest_retrieval_mode,
    source_index_is_stale,
)
from llm_notes.search import build_index


class RetrievalTests(unittest.TestCase):
    def _make_kb(self, root: Path) -> Path:
        wiki = root / "wiki" / "ml"
        wiki.mkdir(parents=True, exist_ok=True)
        (root / "notes").mkdir(parents=True, exist_ok=True)
        (wiki / "attention.md").write_text(
            "---\n"
            'title: "Attention"\n'
            "---\n\n"
            "# Attention\n\n"
            "Attention is the main compiled topic for transformer context handling.\n",
            encoding="utf-8",
        )
        (root / "notes" / "attention.md").write_text(
            "# Attention notes\n\n"
            "Dense attention increases memory cost while keeping full-token interactions.\n"
            "Retrieval reduces memory pressure but adds index maintenance.\n",
            encoding="utf-8",
        )
        (root / "src").mkdir()
        (root / "src" / "model.py").write_text(
            "class AttentionModel:\n"
            "    def compare_attention_and_retrieval(self):\n"
            "        return 'tradeoffs'\n",
            encoding="utf-8",
        )
        return root

    def test_build_source_index_and_search_returns_source_hits(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_root = self._make_kb(Path(tmpdir))
            build_source_index(kb_root)
            results = search_source_index(kb_root, "attention retrieval")

            self.assertEqual(len(results), 2)
            self.assertEqual(results[0].source_path, "notes/attention.md")
            self.assertIn("Retrieval reduces memory", results[0].snippet)

    def test_source_index_is_stale_after_source_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_root = self._make_kb(Path(tmpdir))
            build_source_index(kb_root)
            self.assertFalse(source_index_is_stale(kb_root))

            source = kb_root / "notes" / "attention.md"
            source.write_text("# Attention notes\n\nUpdated body", encoding="utf-8")
            self.assertTrue(source_index_is_stale(kb_root))

    def test_suggest_retrieval_mode_chooses_hybrid_for_code_sensitive_question(self) -> None:
        suggestion = suggest_retrieval_mode("Compare the attention implementation and retrieval tradeoffs")
        self.assertEqual(suggestion.mode, "hybrid")

    def test_query_retrieval_returns_wiki_and_source_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_root = self._make_kb(Path(tmpdir))
            build_index(kb_root / "wiki")

            payload = query_retrieval(
                kb_root,
                "Compare the attention implementation and retrieval tradeoffs",
                mode="auto",
                wiki_limit=3,
                source_limit=3,
            )

            self.assertEqual(payload["mode"], "auto")
            self.assertEqual(payload["suggested_mode"], "hybrid")
            self.assertEqual(payload["executed_modes"], ["wiki", "source"])
            self.assertTrue(payload["wiki_results"])
            self.assertTrue(payload["source_results"])
            self.assertEqual(payload["sources_consulted_by_mode"]["hybrid"][0], "wiki/ml/attention.md")
            self.assertEqual(
                set(payload["sources_consulted_by_mode"]["hybrid"]),
                {"wiki/ml/attention.md", "notes/attention.md", "src/model.py"},
            )
            self.assertTrue(any(item.startswith("wiki:") for item in payload["retrieval_trace"]))
            self.assertTrue(any(item.startswith("source:") for item in payload["retrieval_trace"]))

    def test_query_retrieval_auto_can_suggest_source_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_root = self._make_kb(Path(tmpdir))
            payload = query_retrieval(
                kb_root,
                "Which file contains compare_attention_and_retrieval?",
                mode="auto",
                wiki_limit=3,
                source_limit=3,
            )
            self.assertEqual(payload["mode"], "auto")
            self.assertEqual(payload["suggested_mode"], "source_only")
            self.assertEqual(payload["executed_modes"], ["wiki", "source"])
            self.assertFalse(payload["wiki_results"])
            self.assertTrue(payload["source_results"])

    def test_query_retrieval_can_force_source_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_root = self._make_kb(Path(tmpdir))
            payload = query_retrieval(
                kb_root,
                "Which file contains compare_attention_and_retrieval?",
                mode="source_only",
                wiki_limit=3,
                source_limit=3,
            )
            self.assertEqual(payload["mode"], "source_only")
            self.assertEqual(payload["suggested_mode"], "source_only")
            self.assertEqual(payload["executed_modes"], ["source"])
            self.assertFalse(payload["wiki_results"])
            self.assertTrue(payload["source_results"])

    def test_consulted_sources_from_retrieval_normalizes_paths_by_mode(self) -> None:
        payload = {
            "wiki_results": [{"path": "ml/attention.md"}],
            "source_results": [
                {"source_path": "notes/attention.md"},
                {"source_path": "src/model.py"},
            ],
        }

        self.assertEqual(
            consulted_sources_from_retrieval(payload, actual_mode="wiki_only"),
            ["wiki/ml/attention.md"],
        )
        self.assertEqual(
            consulted_sources_from_retrieval(payload, actual_mode="source_only"),
            ["notes/attention.md", "src/model.py"],
        )
        self.assertEqual(
            consulted_sources_from_retrieval(payload, actual_mode="hybrid"),
            ["wiki/ml/attention.md", "notes/attention.md", "src/model.py"],
        )


if __name__ == "__main__":
    unittest.main()
