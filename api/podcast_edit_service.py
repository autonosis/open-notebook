"""Save optimistic-concurrency drafts and submit audio-only revised episodes."""

import asyncio
import copy
import time
from uuid import uuid4

from fastapi import HTTPException
from surreal_commands import submit_command

from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.exceptions import NotFoundError
from open_notebook.podcasts.models import PodcastEpisode
from open_notebook.podcasts.transcripts import revision, validate_turns

# This deployment has one API process. Database CAS also protects draft saves.
SUBMISSION_LOCK = asyncio.Lock()


async def save_draft(episode_id, expected_revision, turns):
    episode = await PodcastEpisode.get(episode_id)
    if await episode.get_job_status() in {"running", "pending", "queued", "submitted"}:
        raise HTTPException(
            409, "Wait for this episode to finish processing before editing."
        )
    try:
        validate_turns(turns, episode.speaker_profile)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    meta = copy.deepcopy(episode.transcript or {})
    if revision(meta) != expected_revision:
        raise HTTPException(
            409, "This transcript changed elsewhere. Reload before saving."
        )
    meta["draft"] = {"revision": expected_revision + 1, "entries": turns}
    result = await repo_query(
        "UPDATE $episode SET transcript = $transcript "
        "WHERE (transcript.draft.revision ?? transcript.revision ?? 0) = $expected RETURN AFTER",
        {
            "episode": ensure_record_id(episode_id),
            "transcript": meta,
            "expected": expected_revision,
        },
    )
    if not result:
        raise HTTPException(
            409, "This transcript changed elsewhere. Reload before saving."
        )
    return meta["draft"]


async def _submit(episode):
    meta = copy.deepcopy(episode.transcript or {})
    active = await episode.get_job_status()
    # An unknown command status is not evidence of failure. Never enqueue
    # duplicate speech when the status store is temporarily unavailable.
    if episode.audio_file or (episode.command and active not in {"failed", "error"}):
        return {
            "episode_id": str(episode.id),
            "job_id": str(episode.command),
            "name": episode.name,
            "status": "completed" if episode.audio_file else active or "pending",
        }
    if (
        not episode.command
        and meta.get("audio_edit", {}).get("claimed_at", 0) > time.time() - 120
    ):
        return {
            "episode_id": str(episode.id),
            "job_id": None,
            "name": episode.name,
            "status": "pending",
        }
    return await _dispatch(episode)


async def _dispatch(episode):
    from commands import podcast_audio_commands  # noqa: F401

    meta = copy.deepcopy(episode.transcript)
    request_id = uuid4().hex
    meta["audio_edit"].update(request_id=request_id, claimed_at=time.time())
    episode.transcript = meta
    episode.command = None
    await episode.save()
    try:
        job_id = await asyncio.to_thread(
            submit_command,
            "open_notebook",
            "regenerate_podcast_audio",
            {"episode_id": str(episode.id), "request_id": request_id},
        )
        # Worker can start before submission returns. Set only this field, so a
        # completed audio publication or newer draft cannot be overwritten.
        await repo_query(
            "UPDATE $episode SET command = $command WHERE transcript.audio_edit.request_id = $request",
            {
                "episode": ensure_record_id(episode.id),
                "command": ensure_record_id(job_id),
                "request": request_id,
            },
        )
    except Exception:
        await repo_query(
            "UPDATE $episode SET transcript.audio_edit.claimed_at = 0 WHERE transcript.audio_edit.request_id = $request",
            {"episode": ensure_record_id(episode.id), "request": request_id},
        )
        raise
    return {
        "episode_id": str(episode.id),
        "job_id": str(job_id),
        "name": episode.name,
        "status": "submitted",
    }


async def regenerate_audio(episode_id, expected_revision, reuse_unchanged=True):
    async with SUBMISSION_LOCK:
        parent = await PodcastEpisode.get(episode_id)
        if await parent.get_job_status() in {
            "running",
            "pending",
            "queued",
            "submitted",
        }:
            raise HTTPException(409, "Wait for this episode to finish processing.")
        meta = parent.transcript or {}
        if revision(meta) != expected_revision:
            raise HTTPException(
                409,
                "This transcript changed elsewhere. Reload before generating audio.",
            )
        draft = meta.get("draft")
        if not draft:
            raise HTTPException(400, "Save a transcript draft first.")
        validate_turns(draft["entries"], parent.speaker_profile)
        if draft.get("output_episode"):
            try:
                previous = await PodcastEpisode.get(draft["output_episode"])
            except NotFoundError:
                previous = None
            if (
                previous
                and (previous.transcript or {})
                .get("audio_edit", {})
                .get("reuse_unchanged", True)
                == reuse_unchanged
            ):
                return await _submit(previous)
        child = PodcastEpisode(
            name=f"{parent.name} · edit {draft['revision']}",
            episode_profile=copy.deepcopy(parent.episode_profile),
            speaker_profile=copy.deepcopy(parent.speaker_profile),
            briefing=parent.briefing,
            content=parent.content,
            transcript={
                "transcript": copy.deepcopy(draft["entries"]),
                "revision": draft["revision"],
                "audio_edit": {
                    "source_episode": str(parent.id),
                    "reuse_unchanged": reuse_unchanged,
                },
            },
            outline=copy.deepcopy(parent.outline),
        )
        await child.save()
        linked = await repo_query(
            "UPDATE $episode SET transcript.draft.output_episode = $child WHERE transcript.draft.revision = $revision RETURN AFTER",
            {
                "episode": ensure_record_id(parent.id),
                "child": str(child.id),
                "revision": draft["revision"],
            },
        )
        if not linked:
            await repo_query("DELETE $episode", {"episode": ensure_record_id(child.id)})
            raise HTTPException(
                409, "The draft changed during submission. Save and generate again."
            )
        return await _dispatch(child)


async def retry_audio(episode_id):
    async with SUBMISSION_LOCK:
        episode = await PodcastEpisode.get(episode_id)
        result = await _submit(episode)
        return {**result, "message": "Audio regeneration queued."}
