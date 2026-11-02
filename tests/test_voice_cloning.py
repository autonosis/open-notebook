from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.datastructures import UploadFile

from api import voice_cloning_service as service
from api.routers.podcasts import create_cloned_voice, valid_clone_id
from open_notebook.exceptions import ConfigurationError, InvalidInputError


@pytest.mark.asyncio
async def test_private_voice_never_forwarded_to_cloud(monkeypatch):
    monkeypatch.setattr(
        service.Model,
        "get",
        AsyncMock(
            return_value=SimpleNamespace(
                type="text_to_speech", provider="openai_compatible", name="chatterbox"
            )
        ),
    )
    monkeypatch.setattr(
        service,
        "_resolve_model_config",
        AsyncMock(
            return_value=(
                "openai_compatible",
                "chatterbox",
                {"base_url": "https://example.com/v1/chatterbox", "api_key": "private"},
            )
        ),
    )
    with pytest.raises(ConfigurationError):
        await service.connection("model:test")


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["chatterbox", "qwen3-tts-base"])
async def test_local_model_credentials_are_resolved_and_validated(monkeypatch, name):
    monkeypatch.setattr(
        service.Model,
        "get",
        AsyncMock(
            return_value=SimpleNamespace(
                type="text_to_speech", provider="openai_compatible", name=name
            )
        ),
    )
    monkeypatch.setattr(
        service,
        "_resolve_model_config",
        AsyncMock(
            return_value=(
                "openai_compatible",
                "chatterbox",
                {
                    "base_url": f"http://gateway:11438/v1/{name}",
                    "api_key": "private",
                },
            )
        ),
    )
    validate = AsyncMock()
    monkeypatch.setattr(service, "validate_url", validate)
    base, headers = await service.connection("model:test")
    assert base == f"http://gateway:11438/v1/{name}"
    assert headers == {"Authorization": "Bearer private"}
    validate.assert_awaited_once()


@pytest.mark.asyncio
async def test_large_upload_rejected_and_closed_before_forwarding(monkeypatch):
    upload = UploadFile(
        filename="reference.wav", file=BytesIO(b"x" * (service.MAX_BYTES + 1))
    )
    request = AsyncMock()
    monkeypatch.setattr(service, "request", request)
    with pytest.raises(InvalidInputError):
        await create_cloned_voice("model:test", "My voice", upload)
    assert upload.file.closed
    request.assert_not_awaited()


def test_clone_ids_are_not_paths():
    for value in ["../secret", "clone_/../secret", "clone_123"]:
        with pytest.raises(InvalidInputError):
            valid_clone_id(value)
    assert valid_clone_id("clone_" + "a" * 32) == "clone_" + "a" * 32


@pytest.mark.asyncio
async def test_capability_metadata_does_not_claim_presets_can_clone(monkeypatch):
    monkeypatch.setattr(
        service.Model,
        "get_models_by_type",
        AsyncMock(
            return_value=[
                SimpleNamespace(
                    id="m:kokoro", name="kokoro", provider="openai_compatible"
                ),
                SimpleNamespace(
                    id="m:qwen", name="qwen3-tts", provider="openai_compatible"
                ),
                SimpleNamespace(
                    id="m:chatter", name="chatterbox", provider="openai_compatible"
                ),
            ]
        ),
    )

    async def request(model_id, *args, **kwargs):
        return SimpleNamespace(
            json=lambda: {
                "supported": model_id == "m:chatter",
                "reason": "preset_only" if model_id == "m:qwen" else None,
                "local": True,
            }
        )

    monkeypatch.setattr(service, "request", request)
    rows = await service.models()
    assert [r["supported"] for r in rows] == [False, False, True]
