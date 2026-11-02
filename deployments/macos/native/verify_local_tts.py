"""Live app-boundary auditions and optional small synthetic podcast acceptance jobs."""

import argparse
import importlib.util
import json
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--podcasts", action="store_true")
    args = parser.parse_args()
    root = args.state_dir.resolve()
    spec = importlib.util.spec_from_file_location(
        "deployment_api", root / "scripts/api.py"
    )
    api = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(api)
    registry = api.call("GET", "/models")
    models = {
        name: next(
            x["id"]
            for x in registry
            if x["name"] == name and x["type"] == "text_to_speech"
        )
        for name in ["qwen3-tts", "chatterbox"]
    }
    rows = []
    for model, voices in [
        ("qwen3-tts", ["Ryan", "Aiden"]),
        ("chatterbox", ["synthetic_heart", "synthetic_michael"]),
    ]:
        catalog = api.call(
            "GET", "/podcasts/voices", params={"model_id": models[model]}
        )
        assert set(voices) <= {v["id"] for v in catalog}
        print(json.dumps({"model": model, "catalog_count": len(catalog)}), flush=True)
        for voice in voices:
            start = time.perf_counter()
            r = api.client.post(
                "/podcasts/voices/preview",
                json={"model_id": models[model], "voice_id": voice},
            )
            r.raise_for_status()
            file = root / "evidence" / f"{model}-{voice}-integrated.mp3"
            file.write_bytes(r.content)
            row = {
                "model": model,
                "voice": voice,
                "bytes": len(r.content),
                "generation_s": time.perf_counter() - start,
                "file": str(file),
            }
            rows.append(row)
            print(json.dumps(row), flush=True)
    if args.podcasts:
        for profile, speaker, model in [
            ("Qwen local research", "Qwen English pair", "qwen3-tts"),
            ("Chatterbox local research", "Chatterbox English pair", "chatterbox"),
        ]:
            existing = api.call("GET", "/podcasts/episodes")
            title = "Local speech integration check — " + model
            if any(
                e["name"] == title
                and e.get("job_status") in ["completed", "running", "queued"]
                for e in existing
            ):
                print("Existing validation episode retained: " + model, flush=True)
                continue
            job = api.call(
                "POST",
                "/podcasts/generate",
                json={
                    "episode_profile": profile,
                    "speaker_profile": speaker,
                    "episode_name": title,
                    "content": "This is synthetic acceptance-test material, not a research finding. A causal graph makes assumptions explicit. A graph alone does not prove identification. Prediction and intervention answer different questions. State uncertainty and avoid inventing numerical evidence.",
                    "briefing_suffix": "Technical acceptance check. Use exactly two short turns per section, one by each speaker, at most twelve words per turn. No introductions, biographies, invented experiments, or external facts. Keep the entire episode under 120 words.",
                },
            )
            rows.append({"model": model, "job": job})
            print(json.dumps({"model": model, "job": job}), flush=True)
    assert api.call("GET", "/models/defaults")["default_text_to_speech_model"] == next(
        x["id"] for x in registry if x["name"] == "kokoro"
    )
    api.save("local-tts-live-tests.json", rows)


if __name__ == "__main__":
    main()
