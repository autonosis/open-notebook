import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from open_notebook.podcasts import progress as p


class PodcastProgressTests(unittest.TestCase):
    def test_stages_counters_and_restart_persistence(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(p, "ROOT", Path(tmp)):
            sid = "episode:test"
            for msg in [
                "Starting outline generation",
                "Generated outline with 5 segments",
                "Generating transcript for segment 2/5: private title",
                "Generated transcript with 64 dialogue segments",
                "Generating audio clip 0000 for Speaker",
                "Generated audio clip: data/clips/0000.mp3",
            ]:
                p.consume(sid, msg)
            state = p.snapshot(sid, "running")
            self.assertEqual(state["stage"], "speech")
            self.assertEqual(state["sections_done"], 5)
            self.assertEqual(state["clips_done"], 1)
            self.assertEqual(state["clips_total"], 64)
            self.assertNotIn("private title", str(state))
            self.assertEqual(p.read(sid)["clips_done"], 1)
            p.consume(sid, "Starting audio combination")
            self.assertEqual(p.snapshot(sid, "running")["stage"], "assembly")
            p.update(sid, "completed", finished_at=1000)
            self.assertEqual(p.snapshot(sid, "completed")["stage"], "completed")

    def test_episode_isolation_unknown_history_and_failed_status(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(p, "ROOT", Path(tmp)):
            self.assertIsNone(p.snapshot("episode:old", "completed"))
            p.consume("episode:a", "Starting outline generation")
            self.assertEqual(p.snapshot("episode:a", "failed")["stage"], "failed")
            self.assertIsNone(p.snapshot("episode:b", "running"))
            with self.assertRaises(ValueError):
                p.read("episode:../bad")

    def test_live_log_sink_is_context_scoped_and_observability_cannot_abort_generation(
        self,
    ):
        from loguru import logger

        with tempfile.TemporaryDirectory() as tmp, patch.object(p, "ROOT", Path(tmp)):
            token = p.CURRENT.set("episode:live")
            try:
                logger.patch(
                    lambda record: record.update(name="podcast_creator.nodes")
                ).info("Starting outline generation")
                self.assertEqual(p.read("episode:live")["stage"], "outline")
            finally:
                p.CURRENT.reset(token)
            with patch.object(p, "_update", side_effect=OSError("disk unavailable")):
                p.update("episode:live", "speech")
