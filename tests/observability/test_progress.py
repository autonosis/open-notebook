"""Acceptance-state tests: completed extraction is not completed ingestion."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from open_notebook import observability as obs


class ProgressTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = patch.object(obs, "ROOT", Path(self.temp.name))
        self.root.start()
        self.source = SimpleNamespace(
            id="source:test",
            command="command:root",
            title="Test PDF",
            asset=None,
            full_text="some extracted text",
            get_embedded_chunks=AsyncMock(return_value=0),
        )

    def tearDown(self):
        self.root.stop()
        self.temp.cleanup()

    def job(self, name, status, id="command:root", success=True, **kwargs):
        return dict(id=id, name=name, status=status, success=success, **kwargs)

    async def snap(self, jobs, insights=None):
        with patch.object(
            obs, "repo_query", AsyncMock(side_effect=[jobs, insights or []])
        ):
            return await obs.snapshot(self.source)

    async def test_extraction_complete_embedding_queued_is_not_ready(self):
        s = await self.snap(
            [
                self.job("process_source", "completed"),
                self.job("embed_source", "new", "command:embed"),
            ]
        )
        self.assertEqual(s["status"], "running")
        self.assertEqual(s["stage"], "Queued for indexing")

    async def test_false_success_is_failure_even_if_job_completed(self):
        s = await self.snap(
            [
                self.job("process_source", "completed"),
                self.job("embed_source", "completed", "command:embed", False),
            ]
        )
        self.assertEqual(s["status"], "failed")

    async def test_missing_requested_index_is_not_ready(self):
        s = await self.snap(
            [self.job("process_source", "completed", requested_embed=True)]
        )
        self.assertEqual(s["status"], "unknown")

    async def test_stale_other_root_does_not_block_current_source(self):
        s = await self.snap(
            [
                self.job("process_source", "completed"),
                self.job("process_source", "running", "command:old"),
            ]
        )
        self.assertEqual(s["status"], "completed")

    async def test_persistent_progress_and_safe_identifier(self):
        obs.event("source:test", "Indexing", chunks_done=50, chunks_total=100)
        self.assertEqual(obs.read("source:test")["chunks_done"], 50)
        with self.assertRaises(ValueError):
            obs.path("source:../../escape")
