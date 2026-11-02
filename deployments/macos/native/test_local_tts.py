"""Protocol regression tests without downloading or loading speech weights."""

import asyncio
import threading

import httpx
import pytest
from fastapi.testclient import TestClient
from local_tts import create_app

AUTH = {"Authorization": "Bearer test-secret"}
PAYLOAD = {"model": "qwen3-tts", "voice": "Ryan", "input": "Public test text."}


class FakeEngine:
    def __init__(self):
        self.calls = []
        self.fail = False
        self.active = 0
        self.peak_active = 0
        self.release = threading.Event()
        self.release.set()

    def speech(self, request):
        self.active += 1
        self.peak_active = max(self.active, self.peak_active)
        try:
            self.calls.append(request)
            self.release.wait(5)
            if self.fail:
                raise ValueError("private request details must not leak")
            return b"fake-mp3-data"
        finally:
            self.active -= 1

    def idle(self):
        pass

    def unload(self):
        pass


def test_catalog_auth_and_voice_ids():
    with TestClient(create_app({}, "test-secret", FakeEngine())) as client:
        assert client.get("/v1/qwen3-tts/audio/voices").status_code == 401
        qwen = client.get("/v1/qwen3-tts/audio/voices", headers=AUTH).json()["voices"]
        assert {v["id"] for v in qwen} >= {"Ryan", "Aiden"}
        assert (
            next(v for v in qwen if v["id"] == "Ryan")["name"]
            == "Ryan — English · Male"
        )
        chatter = client.get("/v1/chatterbox/audio/voices", headers=AUTH).json()[
            "voices"
        ]
        assert {v["id"] for v in chatter} == {"synthetic_heart", "synthetic_michael"}


def test_protocol_invalid_voices_paths_and_formats():
    engine = FakeEngine()
    with TestClient(create_app({}, "test-secret", engine)) as client:
        endpoint = "/v1/qwen3-tts/audio/speech"
        assert client.post(endpoint, json=PAYLOAD).status_code == 401
        assert (
            client.post(
                endpoint, headers=AUTH, json={**PAYLOAD, "voice": "../private"}
            ).status_code
            == 400
        )
        assert (
            client.post(
                endpoint, headers=AUTH, json={**PAYLOAD, "ref_audio": "/private"}
            ).status_code
            == 422
        )
        assert (
            client.post(
                endpoint, headers=AUTH, json={**PAYLOAD, "response_format": "bad"}
            ).status_code
            == 422
        )
        assert (
            client.post(
                endpoint, headers=AUTH, json={**PAYLOAD, "input": "x" * 12001}
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/v1/chatterbox/audio/speech", headers=AUTH, json=PAYLOAD
            ).status_code
            == 400
        )
        result = client.post(endpoint, headers=AUTH, json=PAYLOAD)
        assert result.status_code == 200
        assert result.headers["content-type"] == "audio/mpeg"
        assert result.headers["x-request-id"]
        assert engine.calls[0].voice == "Ryan"


def test_errors_are_sanitized_and_retry_recovers():
    engine = FakeEngine()
    with TestClient(create_app({}, "test-secret", engine)) as client:
        engine.fail = True
        result = client.post("/v1/qwen3-tts/audio/speech", headers=AUTH, json=PAYLOAD)
        assert result.status_code == 502
        assert "private request details" not in result.text
        engine.fail = False
        assert (
            client.post(
                "/v1/qwen3-tts/audio/speech", headers=AUTH, json=PAYLOAD
            ).status_code
            == 200
        )


@pytest.mark.asyncio
async def test_serializes_models_bounds_queue_and_retains_slot_after_cancel():
    engine = FakeEngine()
    engine.release.clear()
    app = create_app({}, "test-secret", engine)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test", headers=AUTH
        ) as client:
            first = asyncio.create_task(
                client.post("/v1/qwen3-tts/audio/speech", json=PAYLOAD)
            )
            for _ in range(100):
                if engine.active:
                    break
                await asyncio.sleep(0.01)
            second = asyncio.create_task(
                client.post(
                    "/v1/chatterbox/audio/speech",
                    json={**PAYLOAD, "model": "chatterbox", "voice": "synthetic_heart"},
                )
            )
            await asyncio.sleep(0.03)
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            assert (
                await client.post("/v1/qwen3-tts/audio/speech", json=PAYLOAD)
            ).status_code == 429
            engine.release.set()
            assert (await second).status_code == 200
            assert engine.peak_active == 1
            assert [r.model for r in engine.calls] == ["qwen3-tts", "chatterbox"]


def test_engine_switches_models_caches_each_reference_and_unloads_idle(
    monkeypatch, tmp_path
):
    from types import SimpleNamespace

    import mlx.core as mx
    import numpy as np
    import soundfile as sf
    from local_tts import Engine, SpeechRequest
    from mlx_audio.tts import utils

    loaded = []
    refs = []
    received = []

    class Model:
        def parameters(self):
            return []

        def prepare_conditionals(self, ref, sr, exaggeration):
            refs.append(float(np.array(ref).mean()))
            return len(refs)

        def generate(self, text, **kwargs):
            received.append((text, kwargs))
            yield SimpleNamespace(
                audio=mx.array(np.zeros(2400, dtype=np.float32)), sample_rate=24000
            )

    def load(path):
        loaded.append(str(path))
        return Model()

    monkeypatch.setattr(utils, "load_model", load)
    for name, value in [("a", 0.1), ("b", 0.2)]:
        sf.write(tmp_path / (name + ".wav"), np.full(2400, value), 24000)
    settings = {
        "models": {"qwen3-tts": "qwen", "chatterbox": "chatter"},
        "references": {
            "synthetic_heart": str(tmp_path / "a.wav"),
            "synthetic_michael": str(tmp_path / "b.wav"),
        },
        "idle_seconds": 1,
        "ffmpeg": "/opt/homebrew/bin/ffmpeg",
    }
    engine = Engine(settings)
    engine.speech(SpeechRequest(**PAYLOAD))
    for voice in ["synthetic_heart", "synthetic_michael", "synthetic_heart"]:
        assert (
            len(
                engine.speech(
                    SpeechRequest(
                        model="chatterbox",
                        voice=voice,
                        input="Test.",
                        response_format="wav",
                    )
                )
            )
            > 100
        )
    assert loaded == ["qwen", "chatter"]
    assert len(refs) == 2
    assert [r[1]["conds"] for r in received[1:]] == [1, 2, 1]
    engine.last_use = 0
    engine.idle()
    assert engine.model is None and engine.name is None and not engine.conditionals


def test_long_turn_preserves_every_word_and_failed_engine_can_reload(monkeypatch):
    from types import SimpleNamespace

    import mlx.core as mx
    import numpy as np
    from local_tts import Engine, SpeechRequest
    from mlx_audio.tts import utils

    captured = []
    failures = [True]

    class Model:
        def parameters(self):
            return []

        def generate(self, text, **kwargs):
            if failures[0]:
                raise RuntimeError("simulated device failure")
            captured.append(text)
            yield SimpleNamespace(
                audio=mx.array(np.zeros(2400, dtype=np.float32)), sample_rate=24000
            )

    monkeypatch.setattr(utils, "load_model", lambda _: Model())
    engine = Engine(
        {"models": {"qwen3-tts": "qwen"}, "ffmpeg": "/opt/homebrew/bin/ffmpeg"}
    )
    request = SpeechRequest(
        **{**PAYLOAD, "input": " ".join("word" + str(i) for i in range(500))}
    )
    with pytest.raises(RuntimeError):
        engine.speech(request)
    assert engine.model is None and engine.name is None
    failures[0] = False
    engine.speech(request)
    assert len(captured) > 1
    assert " ".join(captured).split() == request.input.split()
