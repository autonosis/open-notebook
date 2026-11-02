"""Register optional local speech backends without modifying existing profiles/defaults."""

import argparse
import importlib.util
import json
import os
import plistlib
import secrets
import shutil
import subprocess
import time
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-dir", type=Path, required=True)
    args = parser.parse_args()
    root = args.state_dir.resolve()
    source = Path(__file__).resolve().parent
    model_records = json.loads((root / "models/native-tts/manifest.json").read_text())
    models = {
        name: next(x["path"] for x in model_records if marker in x.get("repo", ""))
        for name, marker in [("qwen3-tts", "Qwen3"), ("chatterbox", "chatterbox")]
    }
    for path in models.values():
        if not Path(path, "config.json").is_file():
            raise RuntimeError("Provision the pinned evaluated models before setup")
    references = root / "models/native-tts/references"
    references.mkdir(parents=True, exist_ok=True, mode=0o700)
    refs = {}
    for voice, file in [("synthetic_heart", "A.wav"), ("synthetic_michael", "B.wav")]:
        target = references / (voice + ".wav")
        if not target.exists():
            shutil.copyfile(
                root / "evaluation/tts-2026-11-02/references" / file, target
            )
        refs[voice] = str(target)
    key_file = root / "config/local-tts.key"
    if not key_file.exists():
        fd = os.open(key_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_urlsafe(48))
    config = root / "config/local-tts.json"
    config.write_text(
        json.dumps(
            {
                "models": models,
                "references": refs,
                "clones_dir": str(root / "data/voice_clones"),
                "idle_seconds": 300,
                "api_key_file": str(key_file),
                "ffmpeg": shutil.which("ffmpeg"),
                "log_file": str(root / "logs/local-tts.jsonl"),
            },
            indent=2,
        )
    )
    config.chmod(0o600)
    agent = Path.home() / "Library/LaunchAgents/local.open-notebook.tts.plist"
    agent.write_bytes(
        plistlib.dumps(
            {
                "Label": "local.open-notebook.tts",
                "ProgramArguments": [
                    str(root / ".tts-venv/bin/python"),
                    str(source / "local_tts.py"),
                ],
                "WorkingDirectory": str(root),
                "RunAtLoad": True,
                "KeepAlive": True,
                "ProcessType": "Interactive",
                "ThrottleInterval": 10,
                "EnvironmentVariables": {
                    "OPEN_NOTEBOOK_TTS_CONFIG": str(config),
                    "HF_HOME": str(root / "models/tts-evaluation"),
                    "HF_HUB_OFFLINE": "1",
                    "TRANSFORMERS_OFFLINE": "1",
                    "HF_HUB_DISABLE_TELEMETRY": "1",
                    "DO_NOT_TRACK": "1",
                },
                "StandardOutPath": str(root / "logs/local-tts-stdout.log"),
                "StandardErrorPath": str(root / "logs/local-tts-stderr.log"),
            }
        )
    )
    (root / "config/local.open-notebook.tts.plist").write_bytes(agent.read_bytes())
    domain = f"gui/{os.getuid()}"
    existing = (
        subprocess.run(
            ["launchctl", "print", domain + "/local.open-notebook.tts"],
            capture_output=True,
        ).returncode
        == 0
    )
    if existing:
        # Idempotent setup must not interrupt a running inference request.
        # Explicit source upgrades use kickstart -k after work has drained.
        subprocess.run(
            ["launchctl", "kickstart", domain + "/local.open-notebook.tts"], check=True
        )
    else:
        for attempt in range(3):
            result = subprocess.run(
                ["launchctl", "bootstrap", domain, str(agent)], capture_output=True
            )
            if result.returncode == 0:
                break
            if attempt == 2:
                raise RuntimeError(
                    "LaunchAgent bootstrap failed; inspect launchctl status and the local TTS startup log"
                )
            time.sleep(1)
    for _ in range(120):
        try:
            if httpx.get("http://127.0.0.1:11438/health", timeout=2).is_success:
                break
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    else:
        raise RuntimeError("Local TTS failed to start; inspect local TTS stderr log")
    spec = importlib.util.spec_from_file_location(
        "deployment_api", root / "scripts/api.py"
    )
    api = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(api)
    before = {
        path: api.call("GET", path)
        for path in ["/models/defaults", "/speaker-profiles", "/episode-profiles"]
    }
    evidence = root / "evidence/local-tts-before.json"
    if not evidence.exists():
        evidence.write_text(json.dumps(before, indent=2))
    registered = {}
    creds = api.call("GET", "/credentials")
    existing_models = api.call("GET", "/models")
    for name, credential_name in [
        ("qwen3-tts", "Local Qwen Speech"),
        ("chatterbox", "Local Chatterbox Speech"),
    ]:
        base = f"http://gateway:11438/v1/{name}"
        cred = next((x for x in creds if x["name"] == credential_name), None)
        if not cred:
            cred = api.call(
                "POST",
                "/credentials",
                json={
                    "name": credential_name,
                    "provider": "openai_compatible",
                    "base_url": base,
                    "endpoint_tts": base,
                    "api_key": key_file.read_text().strip(),
                    "modalities": ["text_to_speech"],
                },
            )
        model = next(
            (
                x
                for x in existing_models
                if x["name"] == name and x.get("credential") == cred["id"]
            ),
            None,
        )
        if not model:
            model = api.call(
                "POST",
                "/models",
                json={
                    "name": name,
                    "type": "text_to_speech",
                    "provider": "openai_compatible",
                    "credential": cred["id"],
                },
            )
        registered[name] = model["id"]
    profiles = api.call("GET", "/speaker-profiles")
    for model, profile_name, voices in [
        ("qwen3-tts", "Qwen English pair", ["Ryan", "Aiden"]),
        (
            "chatterbox",
            "Chatterbox English pair",
            ["synthetic_heart", "synthetic_michael"],
        ),
    ]:
        profile = next((x for x in profiles if x["name"] == profile_name), None)
        if not profile:
            profile = api.call(
                "POST",
                "/speaker-profiles",
                json={
                    "name": profile_name,
                    "description": "Optional local speech pair. Existing Kokoro default is preserved.",
                    "voice_model": registered[model],
                    "speakers": [
                        {
                            "name": name,
                            "voice_id": voice,
                            "backstory": role,
                            "personality": "Clear, concise, and grounded in the supplied sources.",
                        }
                        for name, voice, role in zip(
                            ["Host", "Analyst"],
                            voices,
                            [
                                "A host who asks focused research questions.",
                                "An analyst who separates evidence, assumptions, and uncertainty.",
                            ],
                        )
                    ],
                },
            )
        episodes = api.call("GET", "/episode-profiles")
        episode_name = (
            "Qwen local research"
            if model == "qwen3-tts"
            else "Chatterbox local research"
        )
        if not any(x["name"] == episode_name for x in episodes):
            api.call(
                "POST",
                "/episode-profiles",
                json={
                    "name": episode_name,
                    "description": "Source-grounded discussion with optional local speech.",
                    "speaker_config": profile["id"],
                    "outline_llm": before["/models/defaults"]["default_chat_model"],
                    "transcript_llm": before["/models/defaults"]["default_chat_model"],
                    "language": "en-US",
                    "default_briefing": "Use only supplied sources. Distinguish claims, evidence and uncertainty. Keep the conversation concise and preserve numerical qualifications.",
                    "num_segments": 3,
                },
            )
    assert api.call("GET", "/models/defaults") == before["/models/defaults"], (
        "Defaults unexpectedly changed"
    )
    api.save(
        "local-tts-integration.json",
        {
            "models": registered,
            "native_url": "http://127.0.0.1:11438",
            "default_unchanged": True,
        },
    )
    print(json.dumps({"registered_models": registered, "default_unchanged": True}))


if __name__ == "__main__":
    main()
