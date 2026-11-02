"""Audio-only podcast rendering. No outline, transcript LLM, or source ingestion."""

import shutil
import time
from pathlib import Path
from uuid import uuid4

from esperanto.factory import AIFactory
from podcast_creator.core import combine_audio_files
from podcast_creator.defaults import DEFAULT_AUDIO_GAP_MS
from surreal_commands import CommandInput, CommandOutput, command

from open_notebook.config import PODCASTS_FOLDER
from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.exceptions import NotFoundError
from open_notebook.podcasts.audio_paths import (
    resolve_contained_audio_path,
    to_relative_audio_path,
)
from open_notebook.podcasts.models import PodcastEpisode, _resolve_model_config
from open_notebook.podcasts.progress import CURRENT, update
from open_notebook.podcasts.transcripts import entries, validate_turns


class AudioRenderInput(CommandInput):
    episode_id: str
    request_id: str


class AudioRenderOutput(CommandOutput):
    episode_id: str
    clips_generated: int
    clips_reused: int


async def render_audio(episode_id, request_id, command_id=None):
    episode = await PodcastEpisode.get(episode_id)
    meta = episode.transcript or {}
    edit = meta.get("audio_edit") or {}
    if edit.get("request_id") != request_id:
        raise ValueError("This audio request was superseded.")
    if episode.audio_file:
        return {"episode_id": episode_id, "clips_generated": 0, "clips_reused": 0}
    if command_id:
        await repo_query(
            "UPDATE $episode SET command = $command WHERE transcript.audio_edit.request_id = $request",
            {
                "episode": ensure_record_id(episode_id),
                "command": ensure_record_id(command_id),
                "request": request_id,
            },
        )
    transcript = entries(meta)
    validate_turns(transcript, episode.speaker_profile)
    try:
        source = await PodcastEpisode.get(edit["source_episode"])
    except NotFoundError:
        source = None
    source_turns = entries(source.transcript) if source else []
    source_audio = resolve_contained_audio_path(source.audio_file) if source else None
    source_clips = source_audio.parent.parent / "clips" if source_audio else None
    # A new private directory for every attempt; partial/stale files never reach
    # a previous episode or get combined into a later attempt.
    output = Path(PODCASTS_FOLDER) / "episodes" / str(uuid4())
    clips = output / "clips"
    clips.mkdir(parents=True, mode=0o700)
    token = CURRENT.set(episode_id)
    generated = reused = 0
    clients = {}
    try:
        update(
            episode_id,
            "speech",
            started_at=time.time(),
            reset=True,
            clips_total=len(transcript),
            clips_done=0,
            command_id=str(command_id) if command_id else None,
        )
        for index, turn in enumerate(transcript):
            update(episode_id, "speech", current_clip=index + 1)
            destination = clips / f"{index:04d}.mp3"
            original = source_clips / f"{index:04d}.mp3" if source_clips else None
            can_reuse = (
                edit.get("reuse_unchanged", True)
                and source is not None
                and source.speaker_profile == episode.speaker_profile
                and index < len(source_turns)
                and source_turns[index] == turn
                and original
                and original.is_file()
                and original.stat().st_size > 100
            )
            if can_reuse:
                try:
                    shutil.copyfile(original, destination)
                    reused += 1
                except FileNotFoundError:
                    can_reuse = False
            if not can_reuse:
                speaker = next(
                    s
                    for s in episode.speaker_profile["speakers"]
                    if s["name"] == turn["speaker"]
                )
                model_id = speaker.get("voice_model") or episode.speaker_profile.get(
                    "voice_model"
                )
                if not model_id:
                    raise ValueError(
                        "The saved episode has no resolvable speech model."
                    )
                if model_id not in clients:
                    provider, name, config = await _resolve_model_config(str(model_id))
                    clients[model_id] = AIFactory.create_text_to_speech(
                        provider, name, config=config
                    )
                await clients[model_id].agenerate_speech(
                    text=turn["dialogue"],
                    voice=speaker["voice_id"],
                    output_file=destination,
                    response_format="mp3",
                )
                if not destination.is_file() or destination.stat().st_size < 100:
                    raise ValueError("Speech synthesis returned no usable audio.")
                generated += 1
            update(episode_id, "speech", clips_done=index + 1, clips_reused=reused)
        update(episode_id, "assembly")
        result = await combine_audio_files(
            clips, output.name + ".mp3", output / "audio", gap_ms=DEFAULT_AUDIO_GAP_MS
        )
        path = result["combined_audio_path"]
        if str(path).startswith("ERROR:") or not Path(path).is_file():
            raise ValueError("Audio assembly failed; previous audio was preserved.")
        transcript_path = output / "transcript.json"
        import json

        transcript_path.write_text(json.dumps(transcript, ensure_ascii=False, indent=2))
        published = await repo_query(
            "UPDATE $episode SET audio_file = $audio, transcript.audio_edit.clips_generated = $generated, transcript.audio_edit.clips_reused = $reused WHERE transcript.audio_edit.request_id = $request RETURN AFTER",
            {
                "episode": ensure_record_id(episode_id),
                "audio": to_relative_audio_path(path),
                "generated": generated,
                "reused": reused,
                "request": request_id,
            },
        )
        if not published:
            raise ValueError("This audio request was superseded before publication.")
        update(episode_id, "completed", finished_at=time.time())
        return {
            "episode_id": episode_id,
            "clips_generated": generated,
            "clips_reused": reused,
        }
    except Exception as exc:
        update(
            episode_id, "failed", error_type=type(exc).__name__, finished_at=time.time()
        )
        raise
    finally:
        CURRENT.reset(token)


@command("regenerate_podcast_audio", app="open_notebook", retry={"max_attempts": 1})
async def regenerate_podcast_audio(input_data: AudioRenderInput) -> AudioRenderOutput:
    result = await render_audio(
        input_data.episode_id,
        input_data.request_id,
        str(input_data.execution_context.command_id)
        if input_data.execution_context
        else None,
    )
    return AudioRenderOutput(**result)
