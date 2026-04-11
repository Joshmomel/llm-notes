from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from llm_notes.manifest import (
    load_manifest,
    manifest_path,
    save_manifest,
    source_digest,
    source_is_stale,
    tracked_sources,
    update_source_entry,
)


class ManifestTests(unittest.TestCase):
    def test_load_manifest_defaults_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = load_manifest(tmpdir)
            self.assertEqual(manifest["sources"], {})
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


if __name__ == "__main__":
    unittest.main()
