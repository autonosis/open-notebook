import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from api import voice_preview_service as service
from open_notebook.exceptions import ExternalServiceError, InvalidInputError


class VoicePreviewTests(unittest.IsolatedAsyncioTestCase):
    async def test_selected_voice_is_generated_once_then_cached(self):
        async def speak(**kwargs):
            self.assertEqual(kwargs["voice"], "af_heart")
            self.assertEqual(kwargs["text"], service.SAMPLE)
            kwargs["output_file"].write_bytes(b"ID3" + b"a" * 200)

        tts = SimpleNamespace(agenerate_speech=AsyncMock(side_effect=speak))
        record = SimpleNamespace(name="kokoro", provider="openai_compatible")
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(service, "ROOT", Path(tmp)),
            patch.object(service, "resolve", AsyncMock(return_value=(record, tts))),
        ):
            first = await service.preview("model:test", "af_heart")
            self.assertTrue(first.is_file())
            self.assertEqual(first, await service.preview("model:test", "af_heart"))
            self.assertEqual(tts.agenerate_speech.await_count, 1)

    async def test_failed_generation_is_not_cached(self):
        tts = SimpleNamespace(
            agenerate_speech=AsyncMock(side_effect=RuntimeError("provider detail"))
        )
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(service, "ROOT", Path(tmp)),
            patch.object(
                service,
                "resolve",
                AsyncMock(
                    return_value=(
                        SimpleNamespace(name="kokoro", provider="openai_compatible"),
                        tts,
                    )
                ),
            ),
        ):
            with self.assertRaises(ExternalServiceError):
                await service.preview("model:test", "bad")
            self.assertEqual(list(Path(tmp).iterdir()), [])

    async def test_language_model_is_rejected_before_inference(self):
        with (
            patch.object(
                service.Model,
                "get",
                AsyncMock(return_value=SimpleNamespace(type="language")),
            ),
            patch.object(service.model_manager, "get_model", AsyncMock()) as inference,
        ):
            with self.assertRaises(InvalidInputError):
                await service.resolve("model:test")
            inference.assert_not_awaited()

    async def test_voice_catalog_comes_from_selected_provider(self):
        tts = SimpleNamespace(
            available_voices={"af_heart": SimpleNamespace(name="Heart")}
        )
        with patch.object(service, "resolve", AsyncMock(return_value=(None, tts))):
            self.assertEqual(
                await service.voices("model:kokoro"),
                [{"id": "af_heart", "name": "Heart"}],
            )
