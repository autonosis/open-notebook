"""Private, serialized MLX speech service for Open Notebook's OpenAI TTS provider."""

import asyncio
import gc
import hmac
import io
import json
import logging
import os
import subprocess
import textwrap
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from voice_clones import MAX_BYTES, VoiceStore

VOICE_CATALOG = {
    "qwen3-tts": {
        "Ryan": "Ryan — English · Male",
        "Aiden": "Aiden — American English · Male",
        "Vivian": "Vivian — Mandarin Chinese · Female",
        "Serena": "Serena — Mandarin Chinese · Female",
        "Uncle_Fu": "Uncle Fu — Mandarin Chinese · Male",
        "Dylan": "Dylan — Beijing Mandarin · Male",
        "Eric": "Eric — Sichuan Chinese · Male",
        "Ono_Anna": "Ono Anna — Japanese · Female",
        "Sohee": "Sohee — Korean · Female",
    },
    "qwen3-tts-base": {},
    "chatterbox": {
        "synthetic_heart": "Heart — American English · Female (synthetic reference)",
        "synthetic_michael": "Michael — American English · Male (synthetic reference)",
    },
}


CLONE_BACKENDS = {"chatterbox", "qwen3-tts-base"}


class SpeechRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: Literal["qwen3-tts", "qwen3-tts-base", "chatterbox"]
    input: str = Field(min_length=1, max_length=12000)
    voice: str
    response_format: Literal["mp3", "wav", "pcm"] = "mp3"
    speed: float = Field(default=1, ge=0.5, le=2)


def validate_voice(request, store=None):
    if request.model in CLONE_BACKENDS and request.voice.startswith("clone_") and store:
        try:
            store.get(request.voice, backend=request.model)
        except ValueError as exc:
            raise HTTPException(400, "Saved voice was not found") from exc
    elif request.voice not in VOICE_CATALOG[request.model]:
        raise HTTPException(400, "Select a voice from this model's catalog.")
    if not request.input.strip():
        raise HTTPException(400, "Speech text must not be blank.")


class Engine:
    """Access exclusively on one executor thread, including eviction and Metal calls."""

    def __init__(self, settings):
        self.settings = settings
        self.store = VoiceStore(settings)
        self.model = None
        self.name = None
        self.last_use = time.monotonic()
        self.conditionals = {}

    def unload(self):
        self.model = None
        self.name = None
        self.conditionals.clear()
        gc.collect()
        import mlx.core as mx

        mx.clear_cache()

    def idle(self):
        if (
            self.model is not None
            and time.monotonic() - self.last_use
            > self.settings.get("idle_seconds", 300)
        ):
            self.unload()

    def speech(self, request):
        import mlx.core as mx
        import numpy as np
        import soundfile as sf
        from mlx_audio.tts.utils import load_model

        if self.name != request.model:
            self.unload()
            self.model = load_model(Path(self.settings["models"][request.model]))
            mx.eval(self.model.parameters())
            self.name = request.model
        self.last_use = time.monotonic()
        kwargs = {"lang_code": "auto", "voice": request.voice}
        if request.model == "chatterbox":
            if request.voice not in self.conditionals:
                reference = (
                    (self.store.directory(request.voice) / "reference.wav")
                    if request.voice.startswith("clone_")
                    else self.settings["references"][request.voice]
                )
                ref, sr = sf.read(reference, dtype="float32")
                self.conditionals[request.voice] = self.model.prepare_conditionals(
                    mx.array(ref), sr, exaggeration=0.1
                )
            kwargs = {
                "lang_code": "en",
                "conds": self.conditionals[request.voice],
                "exaggeration": 0.1,
            }
        if request.model == "qwen3-tts-base":
            reference = self.store.get(request.voice, backend=request.model)
            kwargs = {
                "lang_code": "english",
                "ref_audio": str(self.store.directory(request.voice) / "reference.wav"),
                "ref_text": reference["reference_text"],
            }
        chunks = []
        try:
            for text in textwrap.wrap(
                request.input,
                width=1000,
                break_long_words=False,
                break_on_hyphens=False,
            ):
                for result in self.model.generate(
                    text, **kwargs, max_tokens=4096, verbose=False
                ):
                    mx.eval(result.audio)
                    audio = np.array(result.audio).reshape(-1)
                    if not np.isfinite(audio).all():
                        raise ValueError("Non-finite speech samples")
                    chunks.append(audio)
                    sr = result.sample_rate
            if not chunks or not sum(len(chunk) for chunk in chunks):
                raise ValueError("No speech returned")
            audio = np.concatenate(chunks)
            # Post-process tempo: both architectures otherwise ignore speed controls.
            wav = io.BytesIO()
            sf.write(wav, audio, sr, format="WAV", subtype="PCM_16")
            args = [
                self.settings.get("ffmpeg", "ffmpeg"),
                "-v",
                "error",
                "-i",
                "pipe:0",
            ]
            if request.speed != 1:
                args += ["-af", f"atempo={request.speed}"]
            args += {
                "mp3": ["-f", "mp3"],
                "wav": ["-f", "wav"],
                "pcm": ["-f", "s16le", "-ar", "24000", "-ac", "1"],
            }[request.response_format]
            encoded = subprocess.run(
                args + ["pipe:1"],
                input=wav.getvalue(),
                capture_output=True,
                check=True,
                timeout=120,
            ).stdout
            if len(encoded) < 100:
                raise ValueError("Empty encoded speech")
            return encoded
        except Exception:
            # Clear a failed model/conditioning rather than poisoning later requests.
            self.unload()
            raise
        finally:
            self.last_use = time.monotonic()


def create_app(settings, key, engine=None):
    if not key:
        raise ValueError("A local TTS API key is required")
    engine = engine or Engine(settings)
    store = getattr(engine, "store", None) or VoiceStore(settings)
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mlx-speech")
    gate = asyncio.Semaphore(2)
    log = logging.getLogger("local_tts")

    async def auth(authorization: str | None = Header(default=None)):
        if not hmac.compare_digest(authorization or "", "Bearer " + key):
            raise HTTPException(401, "Authentication required")

    async def idle_loop():
        while True:
            await asyncio.sleep(30)
            await asyncio.get_running_loop().run_in_executor(executor, engine.idle)

    @asynccontextmanager
    async def lifespan(app):
        idle_task = asyncio.create_task(idle_loop())
        yield
        idle_task.cancel()
        await asyncio.get_running_loop().run_in_executor(executor, engine.unload)
        executor.shutdown(wait=True)

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def limit_reference_upload(request, call_next):
        if request.method == "POST" and request.url.path.endswith("/audio/clones"):
            try:
                size = int(request.headers.get("content-length", "-1"))
            except ValueError:
                size = -1
            if size < 0 or size > MAX_BYTES + 65536:
                return Response(status_code=413, content="Audio upload exceeds 10 MB")
        return await call_next(request)

    @app.get("/v1/{backend}/audio/clone-capabilities", dependencies=[Depends(auth)])
    def clone_capabilities(backend: str):
        if backend not in VOICE_CATALOG:
            raise HTTPException(404, "Unknown speech model")
        return {
            "supported": backend in CLONE_BACKENDS
            and (
                backend != "qwen3-tts-base"
                or bool(settings.get("models", {}).get(backend))
            ),
            "requires_reference_text": backend == "qwen3-tts-base",
            "reason": (
                "unavailable"
                if backend == "qwen3-tts-base"
                and not settings.get("models", {}).get(backend)
                else None
            )
            if backend in CLONE_BACKENDS
            else "preset_only",
            "min_seconds": 5,
            "max_seconds": 30,
            "max_bytes": MAX_BYTES,
            "local": True,
            "language": "en",
        }

    def require_cloning(backend):
        if backend not in CLONE_BACKENDS:
            raise HTTPException(
                400, "This model uses preset voices and does not support cloning"
            )

        if backend == "qwen3-tts-base" and not settings.get("models", {}).get(backend):
            raise HTTPException(503, "Qwen Base has not been provisioned")

    @app.get("/v1/{backend}/audio/clones", dependencies=[Depends(auth)])
    def clones(backend: str, archived: bool = False):
        require_cloning(backend)
        return store.list(archived, backend=backend)

    @app.post("/v1/{backend}/audio/clones", dependencies=[Depends(auth)])
    async def create_clone(
        backend: str,
        name: str = Form(...),
        file: UploadFile = File(...),
        reference_text: str = Form(""),
    ):
        require_cloning(backend)
        try:
            data = await file.read(MAX_BYTES + 1)
            return await asyncio.to_thread(
                store.create, name, data, backend, reference_text
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        finally:
            await file.close()

    class ArchiveRequest(BaseModel):
        archived: bool

    @app.patch("/v1/{backend}/audio/clones/{voice_id}", dependencies=[Depends(auth)])
    def archive_clone(backend: str, voice_id: str, request: ArchiveRequest):
        require_cloning(backend)
        try:
            return store.archive(voice_id, request.archived, backend=backend)
        except ValueError as exc:
            raise HTTPException(404, "Saved voice was not found") from exc

    @app.get(
        "/v1/{backend}/audio/clones/{voice_id}/reference", dependencies=[Depends(auth)]
    )
    def clone_reference(backend: str, voice_id: str):
        require_cloning(backend)
        try:
            store.get(voice_id, backend=backend)
            return Response(
                (store.directory(voice_id) / "reference.wav").read_bytes(),
                media_type="audio/wav",
                headers={"Cache-Control": "no-store"},
            )
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(404, "Saved voice was not found") from exc

    @app.get("/health")
    def health():
        return {"status": "healthy", "models": list(VOICE_CATALOG)}

    @app.get("/v1/models", dependencies=[Depends(auth)])
    def models():
        return {
            "object": "list",
            "data": [
                {"id": name, "object": "model", "owned_by": "local"}
                for name in VOICE_CATALOG
            ],
        }

    @app.get("/v1/{backend}/models", dependencies=[Depends(auth)])
    def backend_models(backend: str):
        if backend not in VOICE_CATALOG:
            raise HTTPException(404, "Unknown speech model")
        return {
            "object": "list",
            "data": [{"id": backend, "object": "model", "owned_by": "local"}],
        }

    @app.get("/v1/{backend}/audio/voices", dependencies=[Depends(auth)])
    def voices(backend: str):
        if backend not in VOICE_CATALOG:
            raise HTTPException(404, "Unknown speech model")
        saved = (
            [
                {"id": v["id"], "name": v["name"] + " — Cloned voice · English"}
                for v in store.list(backend=backend)
            ]
            if backend in CLONE_BACKENDS
            else []
        )
        return {
            "voices": saved
            + [
                {"id": voice, "name": name}
                for voice, name in VOICE_CATALOG[backend].items()
            ]
        }

    @app.post("/v1/{backend}/audio/speech", dependencies=[Depends(auth)])
    async def speech(backend: str, request: SpeechRequest):
        if backend != request.model:
            raise HTTPException(400, "Model does not match the configured endpoint")
        validate_voice(request, store)
        if gate.locked():
            raise HTTPException(
                429, "Speech service is busy; retry after the current requests finish."
            )
        request_id = uuid4().hex
        started = time.monotonic()
        # The shield keeps the queue slot until native inference actually finishes,
        # even if the HTTP caller disconnects or cancels its coroutine.
        await gate.acquire()

        async def generate():
            try:
                audio = await asyncio.get_running_loop().run_in_executor(
                    executor, engine.speech, request
                )
                log.info(
                    json.dumps(
                        {
                            "request_id": request_id,
                            "model": request.model,
                            "voice": request.voice,
                            "characters": len(request.input),
                            "seconds": round(time.monotonic() - started, 3),
                            "bytes": len(audio),
                        }
                    )
                )
                return audio
            except Exception as exc:
                log.error(
                    json.dumps(
                        {
                            "request_id": request_id,
                            "model": request.model,
                            "error_type": type(exc).__name__,
                        }
                    )
                )
                raise HTTPException(
                    502,
                    "Local speech synthesis failed; inspect the local TTS log using the request ID.",
                    headers={"X-Request-ID": request_id},
                ) from exc
            finally:
                gate.release()

        audio = await asyncio.shield(generate())
        return Response(
            audio,
            media_type={"mp3": "audio/mpeg", "wav": "audio/wav", "pcm": "audio/pcm"}[
                request.response_format
            ],
            headers={"X-Request-ID": request_id, "Cache-Control": "no-store"},
        )

    return app


if __name__ == "__main__":
    import uvicorn

    config = Path(os.environ["OPEN_NOTEBOOK_TTS_CONFIG"])
    settings = json.loads(config.read_text())
    key = Path(settings["api_key_file"]).read_text().strip()
    handler = RotatingFileHandler(
        settings["log_file"], maxBytes=10000000, backupCount=5
    )
    logging.getLogger("local_tts").addHandler(handler)
    logging.getLogger("local_tts").setLevel(logging.INFO)
    uvicorn.run(
        create_app(settings, key), host="127.0.0.1", port=11438, access_log=False
    )
