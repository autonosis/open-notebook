"""Fetch pinned MLX checkpoints and local synthetic reference voices once."""

import argparse
import json
import os
from pathlib import Path

import httpx

MODELS = {
    "qwen3-tts": (
        "mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit",
        "41d3337e8b7f2843a75841595fc14e4b9a7a4b96",
    ),
    "chatterbox": (
        "mlx-community/chatterbox-multilingual-v3",
        "03565773edd72e949572557597af8063bb49a18a",
    ),
}
S3_REVISION = "e0c9886f0e1c35ae85b1f27277416fb19fc72bec"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-dir", type=Path, required=True)
    args = parser.parse_args()
    root = args.state_dir.resolve()
    # This dedicated cache is shared with the earlier evaluation; no model copies.
    os.environ["HF_HOME"] = str(root / "models/tts-evaluation")
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    from huggingface_hub import snapshot_download
    from huggingface_hub.constants import HF_HUB_CACHE

    records = []
    for name, (repo, revision) in MODELS.items():
        path = snapshot_download(repo, revision=revision)
        records.append({"name": name, "repo": repo, "revision": revision, "path": path})
    snapshot_download(
        "mlx-community/S3TokenizerV2",
        revision=S3_REVISION,
        allow_patterns=["model.safetensors", "config.json"],
    )
    # Chatterbox's loader requests S3TokenizerV2 at 'main'. Pin that alias in this
    # private offline cache to the verified revision, rather than following upstream.
    alias = Path(HF_HUB_CACHE) / "models--mlx-community--S3TokenizerV2/refs/main"
    alias.parent.mkdir(parents=True, exist_ok=True)
    alias.write_text(S3_REVISION)
    target = root / "models/native-tts"
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    (target / "manifest.json").write_text(json.dumps(records, indent=2))
    references = target / "references"
    references.mkdir(exist_ok=True, mode=0o700)
    text = "This is a synthetic reference voice for a local speech model evaluation. We are comparing clarity, pronunciation, and pacing on the same research narration. No real person is being imitated."
    for name, voice in [
        ("synthetic_heart", "af_heart"),
        ("synthetic_michael", "am_michael"),
    ]:
        file = references / (name + ".wav")
        if not file.exists():
            response = httpx.post(
                "http://127.0.0.1:8880/v1/audio/speech",
                json={
                    "model": "kokoro",
                    "voice": voice,
                    "input": text,
                    "response_format": "wav",
                },
                timeout=120,
            )
            response.raise_for_status()
            file.write_bytes(response.content)
            file.chmod(0o600)
    print("Pinned checkpoints and local synthetic references are ready.")


if __name__ == "__main__":
    main()
