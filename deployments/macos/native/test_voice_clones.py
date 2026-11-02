import io
import wave

import numpy as np
import pytest
from fastapi.testclient import TestClient
from local_tts import create_app
from test_local_tts import AUTH, FakeEngine
from voice_clones import VoiceStore


def sample(seconds=6, silent=False):
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        audio = (
            np.zeros(int(24000 * seconds))
            if silent
            else np.sin(np.arange(int(24000 * seconds)) * 0.05) * 6000
        )
        wav.writeframes(audio.astype(np.int16).tobytes())
    return output.getvalue()


def test_private_upload_archive_persistence_and_catalog(tmp_path):
    settings = {
        "clones_dir": str(tmp_path / "voices"),
        "ffmpeg": "/opt/homebrew/bin/ffmpeg",
    }
    with TestClient(create_app(settings, "test-secret", FakeEngine())) as client:
        path = "/v1/chatterbox/audio/clones"
        assert (
            client.post(
                path, data={"name": "Test"}, files={"file": ("speech.wav", sample())}
            ).status_code
            == 401
        )
        response = client.post(
            path,
            headers=AUTH,
            data={"name": "My voice"},
            files={"file": ("speech.wav", sample())},
        )
        assert response.status_code == 200, response.text
        voice = response.json()
        vid = voice["id"]
        assert voice["duration_s"] == 6
        assert VoiceStore(settings).get(vid)["name"] == "My voice"
        assert (
            tmp_path / "voices" / vid / "reference.wav"
        ).stat().st_mode & 0o777 == 0o600
        assert client.get(path, headers=AUTH).json()[0]["id"] == vid
        assert vid in {
            v["id"]
            for v in client.get("/v1/chatterbox/audio/voices", headers=AUTH).json()[
                "voices"
            ]
        }
        assert (
            client.get(path + "/" + vid + "/reference", headers=AUTH).headers[
                "content-type"
            ]
            == "audio/wav"
        )
        assert (
            client.patch(
                path + "/" + vid, headers=AUTH, json={"archived": True}
            ).status_code
            == 200
        )
        assert client.get(path, headers=AUTH).json() == []
        assert (
            client.get(path + "?archived=true", headers=AUTH).json()[0]["archived"]
            is True
        )
        # Existing profiles can still render an archived voice.
        result = client.post(
            "/v1/chatterbox/audio/speech",
            headers=AUTH,
            json={"model": "chatterbox", "voice": vid, "input": "A public test."},
        )
        assert result.status_code == 200
        client.patch(path + "/" + vid, headers=AUTH, json={"archived": False})
        assert client.get(path, headers=AUTH).json()[0]["archived"] is False
        assert (
            client.post(
                "/v1/qwen3-tts/audio/clones",
                headers=AUTH,
                data={"name": "Test"},
                files={"file": ("speech.wav", sample())},
            ).status_code
            == 400
        )
        assert (
            client.get("/v1/qwen3-tts/audio/clone-capabilities", headers=AUTH).json()[
                "supported"
            ]
            is False
        )


@pytest.mark.parametrize(
    "data", [b"not audio", sample(1), sample(31), sample(silent=True)]
)
def test_bad_reference_is_rejected_without_partial_saved_voice(tmp_path, data):
    store = VoiceStore(
        {"clones_dir": str(tmp_path), "ffmpeg": "/opt/homebrew/bin/ffmpeg"}
    )
    with pytest.raises(ValueError):
        store.create("Example", data)
    assert store.list(True) == []
    assert list(tmp_path.iterdir()) == []


def test_paths_and_oversized_upload_rejected(tmp_path):
    store = VoiceStore({"clones_dir": str(tmp_path)})
    for vid in ["../secret", "clone_not-a-uuid"]:
        with pytest.raises(ValueError):
            store.get(vid)
    with pytest.raises(ValueError):
        store.create("Test", b"x" * (10 * 1024 * 1024 + 1))


def test_existing_voice_cannot_resolve_through_a_symlink(tmp_path):
    root = tmp_path / "voices"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "voice.json").write_text("{}")
    (root / ("clone_" + "a" * 32)).symlink_to(outside, target_is_directory=True)
    store = VoiceStore({"clones_dir": str(root)})
    with pytest.raises(ValueError):
        store.get("clone_" + "a" * 32)


def test_qwen_reference_text_and_model_isolation(tmp_path):
    settings = {
        "clones_dir": str(tmp_path / "voices"),
        "ffmpeg": "/opt/homebrew/bin/ffmpeg",
        "models": {"qwen3-tts-base": "test-model"},
    }
    with TestClient(create_app(settings, "test-secret", FakeEngine())) as client:
        qwen = "/v1/qwen3-tts-base/audio/clones"
        assert (
            client.get(
                "/v1/qwen3-tts-base/audio/clone-capabilities", headers=AUTH
            ).json()["requires_reference_text"]
            is True
        )
        assert (
            client.post(
                qwen,
                headers=AUTH,
                data={"name": "Qwen test"},
                files={"file": ("sample.wav", sample())},
            ).status_code
            == 400
        )
        response = client.post(
            qwen,
            headers=AUTH,
            data={"name": "Qwen test", "reference_text": "Exact words in the sample."},
            files={"file": ("sample.wav", sample())},
        )
        assert response.status_code == 200, response.text
        voice = response.json()
        vid = voice["id"]
        assert voice["reference_text"] == "Exact words in the sample."
        assert client.get(qwen, headers=AUTH).json()[0]["id"] == vid
        assert client.get("/v1/chatterbox/audio/clones", headers=AUTH).json() == []
        assert (
            client.get(
                "/v1/chatterbox/audio/clones/" + vid + "/reference", headers=AUTH
            ).status_code
            == 404
        )
        assert (
            client.patch(
                "/v1/chatterbox/audio/clones/" + vid,
                headers=AUTH,
                json={"archived": True},
            ).status_code
            == 404
        )
        assert (
            client.post(
                "/v1/chatterbox/audio/speech",
                headers=AUTH,
                json={"model": "chatterbox", "voice": vid, "input": "Hello"},
            ).status_code
            == 400
        )
        assert (
            client.post(
                "/v1/qwen3-tts-base/audio/speech",
                headers=AUTH,
                json={"model": "qwen3-tts-base", "voice": vid, "input": "Hello"},
            ).status_code
            == 200
        )
        assert (
            client.patch(
                qwen + "/" + vid, headers=AUTH, json={"archived": True}
            ).status_code
            == 200
        )
        assert client.get(qwen, headers=AUTH).json() == []
        assert (
            client.post(
                "/v1/qwen3-tts-base/audio/speech",
                headers=AUTH,
                json={"model": "qwen3-tts-base", "voice": vid, "input": "Hello"},
            ).status_code
            == 200
        )


def test_qwen_engine_passes_audio_and_transcript_not_preset_voice(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    import mlx.core as mx
    from local_tts import Engine, SpeechRequest
    from mlx_audio.tts import utils

    calls = []

    class Model:
        def parameters(self):
            return []

        def generate(self, text, **kwargs):
            calls.append(kwargs)
            yield SimpleNamespace(
                audio=mx.array(np.zeros(2400, dtype=np.float32)), sample_rate=24000
            )

    monkeypatch.setattr(utils, "load_model", lambda _: Model())
    engine = Engine(
        {
            "models": {"qwen3-tts-base": "model"},
            "clones_dir": str(tmp_path / "voices"),
            "ffmpeg": "/opt/homebrew/bin/ffmpeg",
        }
    )
    voice = engine.store.create(
        "Test", sample(), "qwen3-tts-base", "Exact spoken reference."
    )
    engine.speech(
        SpeechRequest(model="qwen3-tts-base", voice=voice["id"], input="New speech.")
    )
    assert calls[0]["ref_text"] == "Exact spoken reference."
    assert calls[0]["ref_audio"].endswith("/reference.wav")
    assert "voice" not in calls[0]
