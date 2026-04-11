from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from llm_notes.search import build_index, index_is_stale, install_wrapper, search_index


class SearchTests(unittest.TestCase):
    def _make_wiki(self, root: Path) -> Path:
        wiki = root / "wiki"
        (wiki / "ml").mkdir(parents=True, exist_ok=True)
        (wiki / "systems").mkdir(parents=True, exist_ok=True)
        (wiki / "_index.md").write_text("# Index", encoding="utf-8")
        (wiki / "ml" / "attention.md").write_text(
            "---\n"
            'title: "Attention Mechanisms"\n'
            "---\n\n"
            "# Attention Mechanisms\n\n"
            "Transformers use attention to connect tokens across a sequence.",
            encoding="utf-8",
        )
        (wiki / "systems" / "retrieval.md").write_text(
            "# Retrieval\n\n"
            "Search indexes help retrieval pipelines find relevant notes quickly.",
            encoding="utf-8",
        )
        return wiki

    def test_install_wrapper_creates_stable_entrypoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            wiki = self._make_wiki(Path(tmpdir))
            wrapper = install_wrapper(wiki)
            self.assertTrue(wrapper.exists())
            self.assertIn("llm_notes.search", wrapper.read_text(encoding="utf-8"))

    def test_search_returns_ranked_results_with_snippets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            wiki = self._make_wiki(Path(tmpdir))
            build_index(wiki)
            results = search_index(wiki, "attention")
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].path, "ml/attention.md")
            self.assertIn("Transformers use attention", results[0].snippet)

    def test_boolean_search_respects_and_not(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            wiki = self._make_wiki(Path(tmpdir))
            build_index(wiki)
            results = search_index(wiki, "search AND retrieval NOT attention")
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].path, "systems/retrieval.md")

    def test_index_is_stale_after_article_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            wiki = self._make_wiki(Path(tmpdir))
            build_index(wiki)
            self.assertFalse(index_is_stale(wiki))

            article = wiki / "ml" / "attention.md"
            article.write_text("# Attention\n\nUpdated text", encoding="utf-8")
            self.assertTrue(index_is_stale(wiki))


if __name__ == "__main__":
    unittest.main()
