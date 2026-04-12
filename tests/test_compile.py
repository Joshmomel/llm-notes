from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from llm_notes.compile import (
    build_compilation_plan,
    classify_source,
    discover_sources,
    find_kb_root,
    main,
    record_compilation,
    sync_kb_indexes,
    write_compiled_article,
)
from llm_notes.manifest import load_manifest, save_manifest, update_source_entry
from llm_notes.wiki import serialize_article


class CompileTests(unittest.TestCase):
    def test_find_kb_root_walks_upward(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_root = Path(tmpdir)
            nested = kb_root / "a" / "b" / "c"
            (kb_root / "wiki").mkdir(parents=True)
            nested.mkdir(parents=True)
            self.assertEqual(find_kb_root(nested), kb_root.resolve())

    def test_discover_sources_skips_generated_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_root = Path(tmpdir)
            (kb_root / "wiki").mkdir()
            (kb_root / "outputs").mkdir()
            egg_dir = kb_root / "demo.egg-info"
            egg_dir.mkdir()
            (kb_root / "notes.md").write_text("hello", encoding="utf-8")
            (kb_root / "wiki" / "ignored.md").write_text("ignored", encoding="utf-8")
            (kb_root / "outputs" / "also-ignored.md").write_text("ignored", encoding="utf-8")
            (egg_dir / "PKG-INFO").write_text("ignored", encoding="utf-8")
            (kb_root / ".hidden.md").write_text("hidden", encoding="utf-8")

            records = discover_sources(kb_root)
            self.assertEqual([record.rel_path for record in records], ["notes.md"])

    def test_classify_source_categories(self) -> None:
        self.assertEqual(classify_source("file.py"), "code")
        self.assertEqual(classify_source("file.pdf"), "paper")
        self.assertEqual(classify_source("file.png"), "image")
        self.assertEqual(classify_source("file.md"), "document")

    def test_build_compilation_plan_uses_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_root = Path(tmpdir)
            (kb_root / "wiki").mkdir()
            (kb_root / "outputs").mkdir()

            unchanged = kb_root / "unchanged.md"
            stale = kb_root / "stale.md"
            fresh = kb_root / "fresh.md"
            unchanged.write_text("# Same\n\nBody", encoding="utf-8")
            stale.write_text("# Old\n\nBody", encoding="utf-8")
            fresh.write_text("# New\n\nBody", encoding="utf-8")

            manifest = load_manifest(kb_root)
            update_source_entry(manifest, kb_root, unchanged, article_paths=["wiki/ml/unchanged.md"])
            update_source_entry(manifest, kb_root, stale, article_paths=["wiki/ml/stale.md"])
            save_manifest(kb_root, manifest)

            stale.write_text("# Old\n\nUpdated body", encoding="utf-8")
            plan = build_compilation_plan(kb_root)

            self.assertEqual([item.rel_path for item in plan.new_sources], ["fresh.md"])
            self.assertEqual([item.rel_path for item in plan.stale_sources], ["stale.md"])
            self.assertEqual([item.rel_path for item in plan.unchanged_sources], ["unchanged.md"])
            self.assertEqual([item.article_path for item in plan.impacted_articles], ["wiki/ml/stale.md"])
            self.assertEqual(
                [(item.action, item.article_path) for item in plan.planned_articles],
                [("create", "wiki/fresh.md"), ("refresh", "wiki/ml/stale.md")],
            )
            self.assertTrue(plan.manifest_in_use)

    def test_build_compilation_plan_falls_back_to_article_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_root = Path(tmpdir)
            source_dir = kb_root / "notes"
            wiki_dir = kb_root / "wiki" / "ml"
            source_dir.mkdir(parents=True)
            wiki_dir.mkdir(parents=True)

            tracked = source_dir / "tracked.md"
            new_file = source_dir / "new.md"
            tracked.write_text("# Tracked\n\nBody", encoding="utf-8")
            new_file.write_text("# New\n\nBody", encoding="utf-8")
            (wiki_dir / "attention.md").write_text(
                serialize_article(
                    {
                        "title": "Attention",
                        "created": "2026-04-11",
                        "updated": "2026-04-11",
                        "sources": ["notes/tracked.md"],
                        "tags": ["attention"],
                    },
                    "Body",
                ),
                encoding="utf-8",
            )

            plan = build_compilation_plan(kb_root)
            self.assertFalse(plan.manifest_in_use)
            self.assertEqual([item.rel_path for item in plan.new_sources], ["notes/new.md"])
            self.assertEqual([item.rel_path for item in plan.unchanged_sources], ["notes/tracked.md"])

    def test_record_compilation_updates_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_root = Path(tmpdir)
            (kb_root / "wiki" / "ml").mkdir(parents=True)
            source = kb_root / "notes.md"
            article = kb_root / "wiki" / "ml" / "attention.md"
            source.write_text("# Note\n\nBody", encoding="utf-8")
            article.write_text(
                serialize_article(
                    {
                        "title": "Attention",
                        "created": "2026-04-11",
                        "updated": "2026-04-11",
                        "sources": ["notes.md"],
                        "tags": ["attention"],
                    },
                    "Body",
                ),
                encoding="utf-8",
            )

            record_compilation(kb_root, [source], [article], metadata={"kind": "test"})
            manifest = load_manifest(kb_root)
            self.assertIn("notes.md", manifest["sources"])
            self.assertEqual(manifest["sources"]["notes.md"]["articles"], ["wiki/ml/attention.md"])
            self.assertEqual(manifest["sources"]["notes.md"]["metadata"]["kind"], "test")
            self.assertIn("wiki/ml/attention.md", manifest["articles"])
            self.assertEqual(manifest["articles"]["wiki/ml/attention.md"]["source_refs"], ["notes.md"])

    def test_build_compilation_plan_reports_existing_article_refresh_and_new_article_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_root = Path(tmpdir)
            (kb_root / "wiki" / "ml").mkdir(parents=True)
            (kb_root / "outputs").mkdir()
            notes_dir = kb_root / "notes"
            notes_dir.mkdir()

            tracked = notes_dir / "attention.md"
            tracked.write_text("# Attention\n\nBody", encoding="utf-8")
            article = kb_root / "wiki" / "ml" / "attention.md"
            article.write_text(
                serialize_article(
                    {
                        "title": "Attention",
                        "created": "2026-04-11",
                        "updated": "2026-04-11",
                        "sources": ["notes/attention.md"],
                        "tags": ["attention"],
                    },
                    "Body",
                ),
                encoding="utf-8",
            )
            record_compilation(
                kb_root,
                [tracked],
                [article],
                metadata={"title": "Attention", "category": "ml", "slug": "attention"},
            )

            tracked.write_text("# Attention\n\nUpdated body", encoding="utf-8")
            novel = notes_dir / "novel-concept.md"
            novel.write_text("# Novel\n\nBody", encoding="utf-8")

            plan = build_compilation_plan(kb_root)

            self.assertEqual([item.article_path for item in plan.impacted_articles], ["wiki/ml/attention.md"])
            refresh = next(item for item in plan.planned_articles if item.action == "refresh")
            create = next(item for item in plan.planned_articles if item.action == "create")
            self.assertEqual(refresh.article_path, "wiki/ml/attention.md")
            self.assertEqual(refresh.source_rel_paths, ["notes/attention.md"])
            self.assertEqual(create.article_path, "wiki/notes/novel-concept.md")
            self.assertEqual(create.source_rel_paths, ["notes/novel-concept.md"])

    def test_sync_kb_indexes_regenerates_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_root = Path(tmpdir)
            wiki_dir = kb_root / "wiki" / "ml"
            wiki_dir.mkdir(parents=True)
            (kb_root / "notes.md").write_text("# Note\n\nBody", encoding="utf-8")
            (wiki_dir / "attention.md").write_text(
                serialize_article(
                    {
                        "title": "Attention",
                        "created": "2026-04-11",
                        "updated": "2026-04-11",
                        "sources": ["notes.md"],
                        "tags": ["attention"],
                    },
                    "Body",
                ),
                encoding="utf-8",
            )

            written = sync_kb_indexes(kb_root)
            self.assertIn("master", written)
            self.assertTrue((kb_root / "wiki" / "_index.md").exists())
            self.assertTrue((kb_root / "wiki" / "ml" / "_index.md").exists())

    def test_main_plan_json_outputs_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_root = Path(tmpdir)
            (kb_root / "wiki").mkdir()
            (kb_root / "notes.md").write_text("# Note\n\nBody", encoding="utf-8")

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = main(["plan", "--kb-root", str(kb_root), "--json"])

            payload = json.loads(buffer.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["new_sources"][0]["rel_path"], "notes.md")
            self.assertEqual(payload["all_sources"][0]["kind"], "document")
            self.assertEqual(payload["planned_articles"][0]["action"], "create")

    def test_main_requires_existing_wiki_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_root = Path(tmpdir)
            with self.assertRaises(RuntimeError):
                main(["sync-indexes", "--kb-root", str(kb_root)])

    def test_write_compiled_article_updates_all_bookkeeping(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_root = Path(tmpdir)
            (kb_root / "wiki").mkdir()
            source = kb_root / "notes.md"
            source.write_text("# Note\n\nBody", encoding="utf-8")

            result = write_compiled_article(
                kb_root,
                title="Attention",
                body="## Summary\n\nBody",
                category="ml",
                sources=["notes.md"],
                tags=["attention"],
                created="2026-04-12",
                updated="2026-04-12",
            )

            self.assertEqual(result["wikilink"], "ml/attention")
            self.assertTrue((kb_root / "wiki" / "ml" / "attention.md").exists())
            self.assertTrue((kb_root / "outputs" / "_manifest.json").exists())
            self.assertIn("2026-04-12 [[ml/attention]]", (kb_root / "wiki" / "_recent.md").read_text(encoding="utf-8"))
            self.assertTrue((kb_root / "wiki" / "_index.md").exists())

    def test_main_write_article_accepts_stdin_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_root = Path(tmpdir)
            (kb_root / "wiki").mkdir()
            (kb_root / "notes.md").write_text("# Note\n\nBody", encoding="utf-8")

            original_stdin = sys.stdin
            buffer = io.StringIO()
            try:
                sys.stdin = io.StringIO("## Summary\n\nBody from stdin\n")
                with redirect_stdout(buffer):
                    exit_code = main(
                        [
                            "write-article",
                            "--kb-root",
                            str(kb_root),
                            "--title",
                            "CLI Article",
                            "--category",
                            "ml",
                            "--source",
                            "notes.md",
                            "--tag",
                            "cli",
                            "--body-stdin",
                        ]
                    )
            finally:
                sys.stdin = original_stdin

            payload = json.loads(buffer.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["wikilink"], "ml/cli-article")
            self.assertTrue((kb_root / "wiki" / "ml" / "cli-article.md").exists())


if __name__ == "__main__":
    unittest.main()
