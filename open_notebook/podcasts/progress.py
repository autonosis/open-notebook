"""Content-free, persistent podcast pipeline progress from pinned creator events."""

import contextvars
import json
import os
import re
import tempfile
import threading
import time
from pathlib import Path

from loguru import logger

from open_notebook.config import DATA_FOLDER

ROOT = Path(DATA_FOLDER) / "observability" / "podcasts"
CURRENT = contextvars.ContextVar("podcast_progress_episode", default=None)
LOCK = threading.RLock()


def path(episode_id):
    if not re.fullmatch(r"episode:[A-Za-z0-9_-]+", str(episode_id)):
        raise ValueError("Invalid episode ID")
    return ROOT / (str(episode_id).split(":")[1] + ".json")


def read(episode_id):
    filename = path(episode_id)
    try:
        return json.loads(filename.read_text())
    except (OSError, ValueError):
        return {}


def _update(episode_id, stage=None, **fields):
    with LOCK:
        data = {} if fields.pop("reset", False) else read(episode_id)
        now = fields.pop("at", time.time())
        previous = data.get("stage")
        data.update(fields, updated_at=now)
        data.setdefault("started_at", now)
        if stage:
            data["stage"] = stage
            if stage != previous:
                data["stage_started_at"] = now
                data["timeline"] = (
                    data.get("timeline", []) + [{"stage": stage, "at": now}]
                )[-100:]
        ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, tmp = tempfile.mkstemp(dir=ROOT)
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump(data, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, path(episode_id))
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)


def update(episode_id, stage=None, **fields):
    try:
        _update(episode_id, stage, **fields)
    except OSError as exc:
        logger.warning("Podcast telemetry write unavailable: {}", type(exc).__name__)


def consume(episode_id, message, at=None):
    fields = {"at": at} if at is not None else {}
    if "Starting outline generation" in message:
        update(episode_id, "outline", **fields)
    elif match := re.search(r"Generated outline with (\d+) segments", message):
        update(
            episode_id,
            "script",
            outline_done=True,
            sections_total=int(match[1]),
            **fields,
        )
    elif match := re.search(r"Generating transcript for segment (\d+)/(\d+)", message):
        update(
            episode_id,
            "script",
            sections_done=int(match[1]) - 1,
            sections_total=int(match[2]),
            **fields,
        )
    elif match := re.search(
        r"Generated transcript with (\d+) dialogue segments", message
    ):
        data = read(episode_id)
        update(
            episode_id,
            "speech",
            script_done=True,
            sections_done=data.get("sections_total"),
            clips_total=int(match[1]),
            clips_done=0,
            **fields,
        )
    elif match := re.search(r"Generating audio clip (\d+) for ", message):
        update(episode_id, "speech", current_clip=int(match[1]) + 1, **fields)
    elif re.search(r"Generated audio clip: .*/\d+\.mp3", message):
        update(
            episode_id,
            "speech",
            clips_done=read(episode_id).get("clips_done", 0) + 1,
            **fields,
        )
    elif "Starting audio combination" in message:
        update(episode_id, "assembly", **fields)
    elif "Combined audio saved to:" in message:
        update(episode_id, "saving", **fields)


def sink(message):
    episode_id = CURRENT.get()
    if episode_id:
        try:
            consume(episode_id, message.record["message"])
        except Exception as exc:
            logger.warning("Podcast progress unavailable: {}", type(exc).__name__)


logger.add(
    sink, filter=lambda record: record["name"] == "podcast_creator.nodes", level="INFO"
)


def snapshot(episode_id, status):
    data = read(episode_id)
    if not data:
        return None
    data["elapsed_s"] = round(
        max(0, data.get("finished_at", time.time()) - data["started_at"])
    )
    data["stage_elapsed_s"] = round(
        max(
            0,
            data.get("finished_at", time.time())
            - data.get("stage_started_at", data["started_at"]),
        )
    )
    data["status"] = status
    if status in ("failed", "error"):
        data["stage"] = "failed"
    elif status == "completed":
        data["stage"] = "completed"
    timeline = data.get("timeline", [])
    for index, entry in enumerate(timeline):
        end = (
            timeline[index + 1]["at"]
            if index + 1 < len(timeline)
            else data.get("finished_at", time.time())
        )
        entry["duration_s"] = round(max(0, end - entry["at"]))
    return data
