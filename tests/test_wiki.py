from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from llm_notes.wiki import (
    article_inventory,
    parse_frontmatter,
    prepend_recent_entry,
    serialize_article,
    sync_indexes,
)


class WikiTests(unittest.TestCase):
    def test_parse_and_serialize_frontmatter_roundtrip(self) -> None:
        text = serialize_article(
            {
                "title": "Attention Notes",
                "created": "2026-04-11",
                "updated": "2026-04-11",
                "sources": ["notes/a.md", "src/model.py"],
                "tags": ["attention", "transformer"],
            },
            "## Summary\n\nBody text.",
        )
        metadata, body = parse_frontmatter(text)
        self.assertEqual(metadata["title"], "Attention Notes")
        self.assertEqual(metadata["sources"], ["notes/a.md", "src/model.py"])
        self.assertEqual(metadata["tags"], ["attention", "transformer"])
        self.assertIn("Body text", body)

    def test_article_inventory_maps_sources_to_articles(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_root = Path(tmpdir)
            wiki_dir = kb_root / "wiki" / "ml"
            wiki_dir.mkdir(parents=True, exist_ok=True)
            (wiki_dir / "attention.md").write_text(
                serialize_article(
                    {
                        "title": "Attention",
                        "created": "2026-04-11",
                        "updated": "2026-04-11",
                        "sources": ["notes/a.md"],
                        "tags": ["attention"],
                    },
                    "Body",
                ),
                encoding="utf-8",
            )

            inventory = article_inventory(kb_root)
            self.assertEqual(inventory["by_source"]["notes/a.md"], ["ml/attention.md"])
            self.assertEqual(inventory["by_article"]["ml/attention.md"]["wikilink"], "ml/attention")

    def test_sync_indexes_writes_category_and_master_indexes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_root = Path(tmpdir)
            wiki_dir = kb_root / "wiki" / "ml"
            wiki_dir.mkdir(parents=True, exist_ok=True)
            (wiki_dir / "attention.md").write_text(
                serialize_article(
                    {
                        "title": "Attention",
                        "created": "2026-04-11",
                        "updated": "2026-04-11",
                        "sources": ["notes/a.md"],
                        "tags": ["attention"],
                    },
                    "Body",
                ),
                encoding="utf-8",
            )

            written = sync_indexes(kb_root, total_sources=3)
            self.assertIn("category:ml", written)
            self.assertTrue((kb_root / "wiki" / "ml" / "_index.md").exists())
            self.assertTrue((kb_root / "wiki" / "_index.md").exists())
            self.assertIn("[[ml/_index]]", (kb_root / "wiki" / "_index.md").read_text(encoding="utf-8"))

    def test_prepend_recent_entry_deduplicates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_root = Path(tmpdir)
            prepend_recent_entry(kb_root, "2026-04-11 [[ml/attention]] — updated")
            prepend_recent_entry(kb_root, "2026-04-11 [[ml/attention]] — updated")
            text = (kb_root / "wiki" / "_recent.md").read_text(encoding="utf-8")
            self.assertEqual(text.count("2026-04-11 [[ml/attention]]"), 1)


if __name__ == "__main__":
    unittest.main()
