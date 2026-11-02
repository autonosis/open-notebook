"""Short, cached auditions through the configured TTS provider."""

import asyncio
import hashlib
import os
import tempfile
from pathlib import Path

from open_notebook.ai.models import Model, model_manager
from open_notebook.config import DATA_FOLDER
from open_notebook.exceptions import (
    ExternalServiceError,
    InvalidInputError,
    OpenNotebookError,
)

SAMPLE = "Hello. This is a voice preview. Listen to the pace, clarity, and tone before choosing a speaker."
ROOT = Path(DATA_FOLDER) / "voice_previews"
LOCK = asyncio.Lock()


async def resolve(model_id):
    record = await Model.get(model_id)
    if not record or record.type != "text_to_speech":
        raise InvalidInputError("Select a text-to-speech model for voice previews.")
    return record, await model_manager.get_model(model_id)


async def voices(model_id):
    _, tts = await resolve(model_id)
    catalog = await asyncio.to_thread(lambda: tts.available_voices)
    return [{"id": key, "name": voice.name} for key, voice in catalog.items()]


async def preview(model_id, voice_id):
    record, tts = await resolve(model_id)
    key = hashlib.sha256(
        repr((model_id, record.name, record.provider, voice_id, SAMPLE)).encode()
    ).hexdigest()
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = ROOT / (key + ".mp3")
    async with LOCK:
        if target.exists() and target.stat().st_size:
            return target
        fd, name = tempfile.mkstemp(dir=ROOT, suffix=".mp3")
        os.close(fd)
        try:
            await tts.agenerate_speech(
                text=SAMPLE,
                voice=voice_id,
                output_file=Path(name),
                response_format="mp3",
            )
            if Path(name).stat().st_size < 100:
                raise ExternalServiceError("Voice preview returned no usable audio.")
            os.replace(name, target)
        except OpenNotebookError:
            raise
        except Exception as exc:
            raise ExternalServiceError(
                "Voice preview failed. Check that this voice ID is supported by the selected TTS model."
            ) from exc
        finally:
            Path(name).unlink(missing_ok=True)
    return target
