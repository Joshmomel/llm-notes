from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from llm_notes.ingest import add, add_file, add_stdin, add_url, main


class _FakeHeaders:
    def __init__(self, content_type: str, charset: str | None = "utf-8") -> None:
        self._content_type = content_type
        self._charset = charset

    def get_content_type(self) -> str:
        return self._content_type

    def get_content_charset(self) -> str | None:
        return self._charset


class _FakeResponse:
    def __init__(self, body: bytes, content_type: str) -> None:
        self._body = body
        self.headers = _FakeHeaders(content_type)

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class IngestTests(unittest.TestCase):
    def test_add_url_fetches_html_into_imported_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_root = Path(tmpdir)
            (kb_root / "wiki").mkdir()
            html = (
                "<html><head><title>Example Article</title></head>"
                "<body><article><p>First paragraph.</p><p>Second paragraph.</p></article></body></html>"
            ).encode("utf-8")

            with patch("llm_notes.ingest.urlopen", return_value=_FakeResponse(html, "text/html")):
                result = add_url(kb_root, url="https://example.com/article")

            imported = Path(result["path"])
            content = imported.read_text(encoding="utf-8")
            self.assertTrue(imported.exists())
            self.assertEqual(result["rel_path"], "imports/web/example-article.md")
            self.assertIn('source_url: "https://example.com/article"', content)
            self.assertIn("# Example Article", content)
            self.assertIn("First paragraph.", content)
            self.assertTrue((kb_root / result["kb_report_rel_path"]).exists())

    def test_add_file_copies_source_and_writes_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            kb_root = root / "kb"
            external_root = root / "external"
            (kb_root / "wiki").mkdir(parents=True)
            external_root.mkdir()
            source = external_root / "paper.pdf"
            source.write_bytes(b"%PDF-sample")

            result = add_file(kb_root, file_path=source)

            imported = Path(result["path"])
            sidecar = Path(result["sidecar_path"])
            self.assertTrue(imported.exists())
            self.assertEqual(imported.read_bytes(), b"%PDF-sample")
            self.assertTrue(sidecar.exists())
            payload = json.loads(sidecar.read_text(encoding="utf-8"))
            self.assertEqual(payload["ingest_type"], "file")
            self.assertEqual(payload["source_path"], str(source.resolve()))
            self.assertEqual(payload["target_rel_path"], "imports/files/paper.pdf")
            self.assertTrue((kb_root / result["kb_report_rel_path"]).exists())

    def test_add_stdin_writes_markdown_import(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_root = Path(tmpdir)
            (kb_root / "wiki").mkdir()

            result = add_stdin(
                kb_root,
                content="Confluence body copied from the browser.",
                title="Confluence Note",
                source_url="https://company.atlassian.net/wiki/spaces/ENG/pages/123",
            )

            imported = Path(result["path"])
            content = imported.read_text(encoding="utf-8")
            self.assertTrue(imported.exists())
            self.assertEqual(result["rel_path"], "imports/text/confluence-note.md")
            self.assertIn('ingest_type: "stdin"', content)
            self.assertIn('source_url: "https://company.atlassian.net/wiki/spaces/ENG/pages/123"', content)
            self.assertIn("# Confluence Note", content)

    def test_add_dispatcher_auto_detects_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            kb_root = root / "kb"
            external_root = root / "external"
            (kb_root / "wiki").mkdir(parents=True)
            external_root.mkdir()
            source = external_root / "notes.md"
            source.write_text("# Notes\n\nBody", encoding="utf-8")

            result = add(kb_root, input_value=str(source))
            self.assertEqual(result["rel_path"], "imports/files/notes.md")

    def test_add_dispatcher_auto_detects_stdin(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_root = Path(tmpdir)
            (kb_root / "wiki").mkdir()

            result = add(
                kb_root,
                mode="auto",
                title="Pasted Note",
                stdin_content="Copied body",
            )
            self.assertEqual(result["rel_path"], "imports/text/pasted-note.md")

    def test_main_add_file_emits_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            kb_root = root / "kb"
            external_root = root / "external"
            (kb_root / "wiki").mkdir(parents=True)
            external_root.mkdir()
            source = external_root / "notes.md"
            source.write_text("# Notes\n\nBody", encoding="utf-8")

            from io import StringIO
            from contextlib import redirect_stdout

            buffer = StringIO()
            with redirect_stdout(buffer):
                exit_code = main(["add-file", "--kb-root", str(kb_root), "--json", str(source)])

            payload = json.loads(buffer.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["rel_path"], "imports/files/notes.md")

    def test_main_add_uses_stdin_when_no_input_is_given(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_root = Path(tmpdir)
            (kb_root / "wiki").mkdir()

            from io import StringIO
            from contextlib import redirect_stdout

            original_stdin = sys.stdin
            buffer = StringIO()
            try:
                sys.stdin = StringIO("Pasted content from clipboard")
                with redirect_stdout(buffer):
                    exit_code = main(["add", "--kb-root", str(kb_root), "--json", "--title", "Clipboard Note"])
            finally:
                sys.stdin = original_stdin

            payload = json.loads(buffer.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["rel_path"], "imports/text/clipboard-note.md")


if __name__ == "__main__":
    unittest.main()
