from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from llm_notes.chat import (
    append_chat_turn,
    close_chat_session,
    create_chat_session,
    list_chat_sessions,
    main,
    parse_chat_session,
    register_chat_artifacts,
)


class ChatTests(unittest.TestCase):
    def test_create_chat_session_writes_active_transcript_note(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_root = Path(tmpdir)
            (kb_root / "wiki").mkdir()

            session_path = create_chat_session(
                kb_root,
                title="Long Context Tradeoffs",
                focus="Compare dense attention and retrieval",
                created_at="2026-04-12T09:00:00",
            )

            session = parse_chat_session(session_path, kb_root)
            self.assertEqual(session.status, "active")
            self.assertEqual(session.turn_count, 0)
            self.assertEqual(session.focus, "Compare dense attention and retrieval")
            self.assertEqual(session.rel_path, "outputs/sessions/2026-04-12-long-context-tradeoffs.md")
            self.assertIn("## Transcript", session.body)

    def test_append_chat_turn_updates_transcript_and_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_root = Path(tmpdir)
            (kb_root / "wiki").mkdir()
            session_path = create_chat_session(
                kb_root,
                title="Attention Session",
                created_at="2026-04-12T09:00:00",
            )

            append_chat_turn(
                kb_root,
                session_path=session_path,
                speaker="user",
                content="How does attention scale?",
                timestamp="2026-04-12T09:01:00",
                sources_consulted=["wiki/ml/attention.md"],
            )
            append_chat_turn(
                kb_root,
                session_path=session_path,
                speaker="assistant",
                content="It trades memory for coverage.",
                timestamp="2026-04-12T09:02:00",
            )

            session = parse_chat_session(session_path, kb_root)
            self.assertEqual(session.turn_count, 2)
            self.assertEqual(session.sources_consulted, ["wiki/ml/attention.md"])
            self.assertIn("### User (2026-04-12T09:01:00)", session.body)
            self.assertIn("### Assistant (2026-04-12T09:02:00)", session.body)

    def test_register_chat_artifacts_updates_metadata_and_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_root = Path(tmpdir)
            (kb_root / "wiki").mkdir()
            answer_path = kb_root / "outputs" / "answers" / "2026-04-12-answer.md"
            answer_path.parent.mkdir(parents=True)
            answer_path.write_text("# Answer", encoding="utf-8")
            session_path = create_chat_session(
                kb_root,
                title="Attention Session",
                created_at="2026-04-12T09:00:00",
            )

            register_chat_artifacts(
                kb_root,
                session_path=session_path,
                answer_paths=["outputs/answers/2026-04-12-answer.md"],
                filed_wikilinks=["ml/attention"],
                updated_at="2026-04-12T09:10:00",
            )

            session = parse_chat_session(session_path, kb_root)
            self.assertEqual(session.answers_generated, ["outputs/answers/2026-04-12-answer.md"])
            self.assertEqual(session.filed_wikilinks, ["ml/attention"])
            self.assertIn("Answer note: `outputs/answers/2026-04-12-answer.md`", session.body)
            self.assertIn("Filed to wiki: [[ml/attention]]", session.body)

    def test_list_chat_sessions_filters_by_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_root = Path(tmpdir)
            (kb_root / "wiki").mkdir()
            active = create_chat_session(
                kb_root,
                title="Active Session",
                created_at="2026-04-12T09:00:00",
            )
            closed = create_chat_session(
                kb_root,
                title="Closed Session",
                created_at="2026-04-12T10:00:00",
            )
            close_chat_session(
                kb_root,
                session_path=closed,
                status="closed",
                updated_at="2026-04-12T10:30:00",
            )

            sessions = list_chat_sessions(kb_root, status="active")
            self.assertEqual([session.title for session in sessions], ["Active Session"])
            self.assertEqual(parse_chat_session(active, kb_root).status, "active")

    def test_main_start_and_append_emit_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_root = Path(tmpdir)
            (kb_root / "wiki").mkdir()

            start_buffer = io.StringIO()
            with redirect_stdout(start_buffer):
                exit_code = main(
                    [
                        "start",
                        "--kb-root",
                        str(kb_root),
                        "--title",
                        "Session Via CLI",
                        "--created",
                        "2026-04-12T09:00:00",
                    ]
                )
            start_payload = json.loads(start_buffer.getvalue())
            self.assertEqual(exit_code, 0)

            original_stdin = sys.stdin
            append_buffer = io.StringIO()
            try:
                sys.stdin = io.StringIO("Track this follow-up.")
                with redirect_stdout(append_buffer):
                    exit_code = main(
                        [
                            "append",
                            "--kb-root",
                            str(kb_root),
                            "--session",
                            start_payload["rel_path"],
                            "--speaker",
                            "user",
                            "--timestamp",
                            "2026-04-12T09:01:00",
                            "--content-stdin",
                        ]
                    )
            finally:
                sys.stdin = original_stdin

            append_payload = json.loads(append_buffer.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(append_payload["turn_count"], 1)


if __name__ == "__main__":
    unittest.main()
