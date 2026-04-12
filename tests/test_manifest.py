from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from llm_notes.manifest import (
    backfill_article_entries,
    tracked_articles,
    load_manifest,
    manifest_path,
    save_manifest,
    source_digest,
    source_is_stale,
    tracked_sources,
    update_article_entry,
    update_source_entry,
)


class ManifestTests(unittest.TestCase):
    def test_load_manifest_defaults_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = load_manifest(tmpdir)
            self.assertEqual(manifest["sources"], {})
            self.assertEqual(manifest["articles"], {})
            self.assertIsNone(manifest["updated_at"])

    def test_save_and_reload_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = load_manifest(tmpdir)
            source = Path(tmpdir) / "notes.md"
            source.write_text("# Title\n\nBody", encoding="utf-8")
            update_source_entry(manifest, tmpdir, source, article_paths=["wiki/topic.md"])
            save_manifest(tmpdir, manifest)

            reloaded = load_manifest(tmpdir)
            self.assertIn("notes.md", tracked_sources(reloaded))
            self.assertTrue(manifest_path(tmpdir).exists())

    def test_markdown_digest_ignores_frontmatter_only_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "notes.md"
            source.write_text("---\nreviewed: 1\n---\n\n# Title\n\nBody", encoding="utf-8")
            first = source_digest(source)
            source.write_text("---\nreviewed: 2\n---\n\n# Title\n\nBody", encoding="utf-8")
            second = source_digest(source)
            self.assertEqual(first, second)

    def test_source_is_stale_after_body_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = load_manifest(tmpdir)
            source = Path(tmpdir) / "notes.md"
            source.write_text("# Title\n\nBody", encoding="utf-8")
            update_source_entry(manifest, tmpdir, source, article_paths=["wiki/topic.md"])
            save_manifest(tmpdir, manifest)

            self.assertFalse(source_is_stale(load_manifest(tmpdir), tmpdir, source))

            source.write_text("# Title\n\nUpdated body", encoding="utf-8")
            self.assertTrue(source_is_stale(load_manifest(tmpdir), tmpdir, source))

    def test_update_source_entry_merges_articles_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = load_manifest(tmpdir)
            source = Path(tmpdir) / "notes.md"
            source.write_text("# Title\n\nBody", encoding="utf-8")

            update_source_entry(
                manifest,
                tmpdir,
                source,
                article_paths=["wiki/ml/attention.md"],
                metadata={"title": "Attention"},
            )
            update_source_entry(
                manifest,
                tmpdir,
                source,
                article_paths=["wiki/synthesis/attention-tradeoffs.md"],
                metadata={"filed": True},
            )

            entry = manifest["sources"]["notes.md"]
            self.assertEqual(
                entry["articles"],
                ["wiki/ml/attention.md", "wiki/synthesis/attention-tradeoffs.md"],
            )
            self.assertEqual(entry["metadata"]["title"], "Attention")
            self.assertTrue(entry["metadata"]["filed"])

    def test_update_article_entry_tracks_source_refs_and_digests(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = load_manifest(tmpdir)
            source = Path(tmpdir) / "notes.md"
            article = Path(tmpdir) / "wiki" / "ml" / "attention.md"
            source.write_text("# Title\n\nBody", encoding="utf-8")

            update_article_entry(
                manifest,
                tmpdir,
                article,
                source_paths=[source],
                metadata={"planner": "compile"},
                title="Attention",
            )

            self.assertIn("wiki/ml/attention.md", tracked_articles(manifest))
            entry = manifest["articles"]["wiki/ml/attention.md"]
            self.assertEqual(entry["title"], "Attention")
            self.assertEqual(entry["wikilink"], "ml/attention")
            self.assertEqual(entry["source_refs"], ["notes.md"])
            self.assertIn("notes.md", entry["source_digests"])
            self.assertEqual(entry["metadata"]["planner"], "compile")

    def test_backfill_article_entries_upgrades_source_only_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_root = Path(tmpdir)
            (kb_root / "wiki" / "ml").mkdir(parents=True)
            source = kb_root / "notes.md"
            article = kb_root / "wiki" / "ml" / "attention.md"
            source.write_text("# Title\n\nBody", encoding="utf-8")
            article.write_text(
                "---\n"
                'title: "Attention"\n'
                "created: 2026-04-11\n"
                "updated: 2026-04-11\n"
                "sources:\n"
                "  - notes.md\n"
                "tags: [attention]\n"
                "---\n\n"
                "Body\n",
                encoding="utf-8",
            )

            manifest = {
                "version": 1,
                "updated_at": None,
                "sources": {
                    "notes.md": {
                        "digest": source_digest(source),
                        "mtime_ns": source.stat().st_mtime_ns,
                        "compiled_at": "2026-04-12T00:00:00+00:00",
                        "articles": ["wiki/ml/attention.md"],
                    }
                },
            }

            changed = backfill_article_entries(manifest, kb_root)
            self.assertTrue(changed)
            self.assertIn("wiki/ml/attention.md", manifest["articles"])
            self.assertEqual(manifest["articles"]["wiki/ml/attention.md"]["source_refs"], ["notes.md"])
            self.assertEqual(manifest["articles"]["wiki/ml/attention.md"]["wikilink"], "ml/attention")


if __name__ == "__main__":
    unittest.main()
