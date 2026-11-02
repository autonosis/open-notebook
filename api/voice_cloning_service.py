"""Authenticated bridge to the private local speech service's clone protocol."""

from urllib.parse import urlsplit

import httpx

from open_notebook.ai.models import Model
from open_notebook.exceptions import (
    ConfigurationError,
    ExternalServiceError,
    InvalidInputError,
)
from open_notebook.podcasts.models import _resolve_model_config
from open_notebook.utils.url_validation import validate_url

MAX_BYTES = 10 * 1024 * 1024


async def connection(model_id):
    model = await Model.get(model_id)
    if (
        model.type != "text_to_speech"
        or model.provider != "openai_compatible"
        or model.name not in {"chatterbox", "qwen3-tts"}
    ):
        raise InvalidInputError(
            "Voice cloning is available through the configured local speech service"
        )
    _, _, config = await _resolve_model_config(model_id)
    base = str(config.get("base_url") or config.get("endpoint_tts") or "").rstrip("/")
    parsed = urlsplit(base)
    # Reference recordings are private. This integration must never silently
    # forward them to a cloud provider, even if a model has a familiar name.
    if (
        parsed.scheme != "http"
        or parsed.hostname
        not in {"gateway", "127.0.0.1", "localhost", "host.docker.internal"}
        or parsed.port != 11438
        or parsed.path != "/v1/" + model.name
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ConfigurationError(
            "Configure the private local speech endpoint before cloning a voice"
        )
    await validate_url(base, model.provider)
    return base, {"Authorization": "Bearer " + str(config.get("api_key") or "")}


async def request(model_id, method, suffix, **kwargs):
    base, headers = await connection(model_id)
    try:
        async with httpx.AsyncClient(
            timeout=60, follow_redirects=False, trust_env=False
        ) as client:
            response = await client.request(
                method, base + "/audio/" + suffix, headers=headers, **kwargs
            )
    except httpx.HTTPError as exc:
        raise ExternalServiceError(
            "Local voice service is unavailable; retry when it is running"
        ) from exc
    if response.status_code == 400:
        raise InvalidInputError(
            response.json().get("detail", "Check the reference recording")
        )
    if response.status_code == 404:
        raise InvalidInputError("Saved voice or cloning endpoint was not found")
    if not response.is_success:
        raise ExternalServiceError(
            "Local voice service could not complete this request"
        )
    return response


async def models():
    records = await Model.get_models_by_type("text_to_speech")
    result = []
    for model in records:
        row = {
            "id": str(model.id),
            "name": model.name,
            "supported": False,
            "reason": "unsupported",
        }
        if model.provider == "openai_compatible" and model.name in {
            "chatterbox",
            "qwen3-tts",
        }:
            try:
                response = await request(str(model.id), "GET", "clone-capabilities")
                row.update(response.json())
            except (ConfigurationError, InvalidInputError, ExternalServiceError):
                row["reason"] = "unavailable"
        result.append(row)
    return result
