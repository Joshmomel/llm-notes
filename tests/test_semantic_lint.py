from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from llm_notes.answers import save_answer
from llm_notes.semantic_lint import build_semantic_candidates, write_semantic_candidates
from llm_notes.wiki import serialize_article


class SemanticLintTests(unittest.TestCase):
    def _write_article(
        self,
        path: Path,
        *,
        title: str,
        sources: list[str],
        tags: list[str],
        body: str,
        created: str = "2026-04-11",
        updated: str = "2026-04-11",
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            serialize_article(
                {
                    "title": title,
                    "created": created,
                    "updated": updated,
                    "sources": sources,
                    "tags": tags,
                },
                body,
            ),
            encoding="utf-8",
        )

    def test_semantic_candidates_include_hotspots_connections_and_missing_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_root = Path(tmpdir)
            wiki_dir = kb_root / "wiki" / "ml"
            wiki_dir.mkdir(parents=True)
            (kb_root / "notes").mkdir()
            for name in ("attention.md", "benchmark.md", "retrieval.md"):
                (kb_root / "notes" / name).write_text(f"# {name}\n\nBody", encoding="utf-8")

            self._write_article(
                wiki_dir / "attention.md",
                title="Attention",
                sources=["notes/attention.md", "notes/benchmark.md"],
                tags=["attention", "long-context"],
                body=(
                    "## Summary\n\nDense attention summary.\n\n"
                    "## Related\n\n- [[ml/kv-cache]]\n\n"
                    "## Open Questions\n\n"
                    "- Which benchmark best captures long-context degradation?\n"
                ),
            )
            self._write_article(
                wiki_dir / "retrieval.md",
                title="Retrieval Augmentation",
                sources=["notes/retrieval.md", "notes/benchmark.md"],
                tags=["attention", "retrieval"],
                body=(
                    "## Summary\n\nRetrieval summary.\n\n"
                    "## Open Questions\n\n"
                    "- Benchmark coverage is still missing for multi-hour context.\n"
                ),
            )
            self._write_article(
                wiki_dir / "attention-position.md",
                title="Attention Position",
                sources=["notes/attention.md", "notes/benchmark.md"],
                tags=["attention", "long-context"],
                body=(
                    "## Summary\n\n"
                    "Dense attention should be preferred for long-context serving because it is faster in this workload.\n\n"
                    "## Open Questions\n\n"
                    "- Which benchmark supports this preference?\n"
                ),
            )
            self._write_article(
                wiki_dir / "attention-counterpoint.md",
                title="Attention Counterpoint",
                sources=["notes/attention.md", "notes/benchmark.md"],
                tags=["attention", "long-context"],
                body=(
                    "## Summary\n\n"
                    "Dense attention should be avoided for long-context serving because it is slower in this workload.\n\n"
                    "## Open Questions\n\n"
                    "- Which benchmark contradicts the faster claim?\n"
                ),
            )
            self._write_article(
                wiki_dir / "attention-overview.md",
                title="Attention",
                sources=["notes/attention.md", "notes/benchmark.md"],
                tags=["attention", "long-context", "overview"],
                body=(
                    "## Summary\n\nDense attention summary with overlapping framing.\n\n"
                    "## Related\n\n- [[ml/retrieval]]\n\n"
                    "## Open Questions\n\n"
                    "- Which benchmark best captures long-context degradation?\n"
                    "- When should this split into separate pages?\n"
                ),
            )
            self._write_article(
                wiki_dir / "systems-and-benchmarks.md",
                title="Systems and Benchmarks",
                sources=["notes/attention.md", "notes/benchmark.md", "notes/retrieval.md"],
                tags=["attention", "retrieval", "benchmark", "systems"],
                body=(
                    "## Summary\n\nA very broad synthesis page.\n\n"
                    "## Related\n\n"
                    "- [[ml/attention]]\n"
                    "- [[ml/retrieval]]\n"
                    "- [[ml/attention-overview]]\n"
                    "- [[ml/kv-cache]]\n"
                    "- [[ml/latency]]\n"
                    "- [[ml/context-window]]\n\n"
                    "## Open Questions\n\n"
                    "- Which benchmark best captures long-context degradation?\n"
                    "- Which workloads benefit from retrieval?\n"
                    "- Which memory bottleneck matters most?\n"
                    "- Which pieces deserve their own page?\n\n"
                    + ("Long section. " * 200)
                ),
            )

            save_answer(
                kb_root,
                question="How do dense attention and retrieval compare for long context?",
                body=(
                    "# Compare\n\n"
                    "## Main Conclusion\n\n"
                    "The tradeoff is workload dependent and cross-source.\n\n"
                    "## Further Questions\n\n"
                    "- Which benchmark is still missing?\n"
                ),
                sources_consulted=["wiki/ml/attention.md", "wiki/ml/retrieval.md"],
            )

            payload = build_semantic_candidates(kb_root)

            self.assertTrue(payload["candidates"]["duplicate_candidates"])
            self.assertTrue(payload["candidates"]["split_candidates"])
            self.assertTrue(payload["candidates"]["conflict_candidates"])
            self.assertTrue(payload["candidates"]["inconsistency_hotspots"])
            self.assertTrue(payload["candidates"]["connection_candidates"])
            self.assertTrue(payload["candidates"]["missing_data_candidates"])
            self.assertTrue(payload["candidates"]["web_imputation_candidates"])
            self.assertTrue(payload["candidates"]["pending_answer_synthesis"])
            self.assertTrue(payload["issues"])
            first_issue = payload["issues"][0]
            self.assertIn("issue_id", first_issue)
            self.assertIn("severity", first_issue)
            self.assertIn("target_wikilinks", first_issue)
            self.assertIn("suggested_action", first_issue)

    def test_write_semantic_candidates_outputs_json_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_root = Path(tmpdir)
            wiki_dir = kb_root / "wiki"
            wiki_dir.mkdir(parents=True)
            self._write_article(
                wiki_dir / "topic.md",
                title="Topic",
                sources=["notes/topic.md"],
                tags=["topic"],
                body="## Summary\n\nBody.\n\n## Open Questions\n\n- Missing benchmark coverage.",
            )
            (kb_root / "notes").mkdir()
            (kb_root / "notes" / "topic.md").write_text("# Topic\n\nBody", encoding="utf-8")

            result = write_semantic_candidates(kb_root)

            json_path = Path(result["json_path"])
            md_path = Path(result["md_path"])
            self.assertTrue(json_path.exists())
            self.assertTrue(md_path.exists())

            payload = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertIn("candidates", payload)
            self.assertIn("issues", payload)
            self.assertIn("# Semantic Lint Candidates", md_path.read_text(encoding="utf-8"))
            self.assertIn("## Conflict Candidates", md_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
