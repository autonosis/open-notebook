"""Private persistent reference voices; no training or external inference."""

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import wave
from pathlib import Path
from uuid import uuid4

MAX_BYTES = 10 * 1024 * 1024


class VoiceStore:
    def __init__(self, settings):
        state = Path(settings.get("log_file", "logs/local-tts.jsonl")).parent.parent
        self.root = Path(settings.get("clones_dir", state / "data/voice_clones"))
        self.ffmpeg = settings.get("ffmpeg", "ffmpeg")
        self.lock = threading.RLock()

    def directory(self, voice_id):
        if not re.fullmatch(r"clone_[a-f0-9]{32}", voice_id):
            raise ValueError("Invalid saved voice")
        if self.root.exists():
            for candidate in self.root.iterdir():
                if (
                    candidate.name == voice_id
                    and candidate.is_dir()
                    and not candidate.is_symlink()
                ):
                    return candidate
        raise ValueError("Saved voice was not found")

    def get(self, voice_id):
        try:
            return json.loads((self.directory(voice_id) / "voice.json").read_text())
        except FileNotFoundError as exc:
            raise ValueError("Saved voice was not found") from exc

    def list(self, archived=False):
        if not self.root.exists():
            return []
        with self.lock:
            rows = [
                json.loads((p / "voice.json").read_text())
                for p in self.root.glob("clone_*")
                if not p.is_symlink()
                and re.fullmatch(r"clone_[a-f0-9]{32}", p.name)
                and (p / "voice.json").is_file()
            ]
        return sorted(
            (r for r in rows if archived or not r["archived"]),
            key=lambda r: r["created"],
            reverse=True,
        )

    def write(self, directory, metadata):
        fd, name = tempfile.mkstemp(dir=directory, suffix=".json")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(metadata, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(name, directory / "voice.json")
        finally:
            Path(name).unlink(missing_ok=True)

    def archive(self, voice_id, archived):
        with self.lock:
            meta = self.get(voice_id)
            meta["archived"] = archived
            self.write(self.directory(voice_id), meta)
            return meta

    def create(self, name, data):
        import numpy as np

        name = name.strip()
        if not name or len(name) > 80:
            raise ValueError("Enter a voice name of 1–80 characters")
        if not data or len(data) > MAX_BYTES:
            raise ValueError("Upload an audio sample up to 10 MB")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        voice_id = "clone_" + uuid4().hex
        directory = self.root / voice_id
        directory.mkdir(mode=0o700)
        try:
            with tempfile.TemporaryDirectory(dir=self.root) as tmp:
                source, target = Path(tmp) / "input", directory / "reference.wav"
                source.write_bytes(data)
                source.chmod(0o600)
                subprocess.run(
                    [
                        self.ffmpeg,
                        "-v",
                        "error",
                        "-nostdin",
                        "-protocol_whitelist",
                        "file,pipe",
                        "-format_whitelist",
                        "wav,mp3,mov,matroska,webm,ogg,flac,aac",
                        "-i",
                        str(source),
                        "-map",
                        "0:a:0",
                        "-t",
                        "31",
                        "-vn",
                        "-ac",
                        "1",
                        "-ar",
                        "24000",
                        "-c:a",
                        "pcm_s16le",
                        str(target),
                    ],
                    capture_output=True,
                    check=True,
                    timeout=30,
                )
            target.chmod(0o600)
            with wave.open(str(target), "rb") as audio:
                duration = audio.getnframes() / audio.getframerate()
                samples = (
                    np.frombuffer(
                        audio.readframes(audio.getnframes()), dtype=np.int16
                    ).astype(np.float32)
                    / 32768
                )
            if not 5 <= duration <= 30.05:
                raise ValueError("Use a sample between 5 and 30 seconds")
            if float(np.sqrt(np.mean(samples * samples))) < 0.001:
                raise ValueError(
                    "The sample is too quiet or silent; record clear speech"
                )
            meta = {
                "id": voice_id,
                "name": name,
                "duration_s": round(duration, 2),
                "created": time.time(),
                "archived": False,
                "backend": "chatterbox",
                "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            }
            with self.lock:
                self.write(directory, meta)
            return meta
        except (subprocess.SubprocessError, OSError) as exc:
            shutil.rmtree(directory, ignore_errors=True)
            raise ValueError(
                "Could not decode this recording; upload a valid audio file"
            ) from exc
        except Exception:
            shutil.rmtree(directory, ignore_errors=True)
            raise
