from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from loguru import logger
from pydantic import BaseModel, Field

from api.podcast_service import (
    PodcastGenerationRequest,
    PodcastGenerationResponse,
    PodcastService,
)
from open_notebook.ai.models import Model
from open_notebook.exceptions import OpenNotebookError
from open_notebook.podcasts.audio_paths import resolve_contained_audio_path
from open_notebook.podcasts.models import PodcastEpisode

router = APIRouter()

# Model reference fields stored in the denormalized profile snapshots on an
# episode, mapped to the resolved display fields the frontend renders
# ("provider / name" rows in EpisodeCard). Mirrors the speaker_config ->
# speaker_config_name precedent in api/routers/episode_profiles.py.
_EPISODE_PROFILE_MODEL_FIELDS = {
    "outline_llm": ("outline_model_provider", "outline_model_name"),
    "transcript_llm": ("transcript_model_provider", "transcript_model_name"),
}
_SPEAKER_PROFILE_MODEL_FIELDS = {
    "voice_model": ("voice_model_provider", "voice_model_name"),
}


def _collect_snapshot_model_ids(episodes: List[PodcastEpisode]) -> List[str]:
    """Collect the distinct model record IDs referenced by episode snapshots."""
    ids = set()
    for episode in episodes:
        for field in _EPISODE_PROFILE_MODEL_FIELDS:
            ref = (episode.episode_profile or {}).get(field)
            if ref:
                ids.add(str(ref))
        for field in _SPEAKER_PROFILE_MODEL_FIELDS:
            ref = (episode.speaker_profile or {}).get(field)
            if ref:
                ids.add(str(ref))
    return sorted(ids)


def _with_resolved_model_fields(
    snapshot: dict,
    field_map: dict,
    models_by_id: dict,
) -> dict:
    """Return a copy of a profile snapshot with resolved model display fields.

    Only sets the display fields when the reference resolves; unresolvable
    references (deleted model) and legacy snapshots without references are
    left untouched so the frontend can fall back to the historical
    provider/model strings, then to a placeholder.
    """
    enriched = dict(snapshot or {})
    for ref_field, (provider_field, name_field) in field_map.items():
        ref = enriched.get(ref_field)
        info = models_by_id.get(str(ref)) if ref else None
        if info:
            enriched[provider_field] = info["provider"]
            enriched[name_field] = info["name"]
    return enriched


async def _resolve_snapshot_models(
    episodes: List[PodcastEpisode],
) -> dict:
    """Batch-resolve every model reference in the episodes' snapshots.

    One query for the whole list (see Model.get_display_info_for_ids) - a
    failure degrades to no resolved fields rather than failing the request.
    """
    try:
        return await Model.get_display_info_for_ids(
            _collect_snapshot_model_ids(episodes)
        )
    except Exception as e:
        logger.warning(f"Error batch-resolving snapshot model references: {str(e)}")
        return {}


def _delete_episode_audio(episode: PodcastEpisode, episode_id: str) -> None:
    """Best-effort unlink of an episode's audio file, refusing invalid paths.

    Shared by the delete and retry endpoints. Legacy/escaping audio_file
    values (resolve_contained_audio_path -> None) are logged and skipped.
    """
    if not episode.audio_file:
        return
    audio_path = resolve_contained_audio_path(episode.audio_file)
    if audio_path is None:
        logger.warning(
            f"Refusing to delete audio file outside podcasts directory "
            f"for episode {episode_id}: {episode.audio_file}"
        )
    elif audio_path.exists():
        try:
            audio_path.unlink()
            logger.info(f"Deleted audio file: {audio_path}")
        except Exception as e:
            logger.warning(f"Failed to delete audio file {audio_path}: {e}")


from open_notebook.podcasts.progress import snapshot as podcast_progress


class PodcastEpisodeResponse(BaseModel):
    id: str
    name: str
    episode_profile: dict
    speaker_profile: dict
    briefing: str
    audio_file: Optional[str] = None
    audio_url: Optional[str] = None
    transcript: Optional[dict] = None
    outline: Optional[dict] = None
    created: Optional[str] = None
    pipeline_progress: Optional[dict] = None
    job_status: Optional[str] = None
    error_message: Optional[str] = None


@router.post("/podcasts/generate", response_model=PodcastGenerationResponse)
async def generate_podcast(request: PodcastGenerationRequest):
    """
    Generate a podcast episode using Episode Profiles.
    Returns immediately with job ID for status tracking.
    """
    try:
        job_id = await PodcastService.submit_generation_job(
            episode_profile_name=request.episode_profile,
            speaker_profile_name=request.speaker_profile,
            episode_name=request.episode_name,
            notebook_id=request.notebook_id,
            content=request.content,
            briefing_suffix=request.briefing_suffix,
        )

        return PodcastGenerationResponse(
            job_id=job_id,
            status="submitted",
            message=f"Podcast generation started for episode '{request.episode_name}'",
            episode_profile=request.episode_profile,
            episode_name=request.episode_name,
        )

    except HTTPException:
        raise
    except OpenNotebookError:
        raise
    except Exception as e:
        logger.error(f"Error generating podcast: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to generate podcast")


@router.get("/podcasts/jobs/{job_id}")
async def get_podcast_job_status(job_id: str):
    """Get the status of a podcast generation job"""
    try:
        status_data = await PodcastService.get_job_status(job_id)
        return status_data

    except HTTPException:
        raise
    except OpenNotebookError:
        raise
    except Exception as e:
        logger.error(f"Error fetching podcast job status: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch job status")


@router.get("/podcasts/episodes", response_model=List[PodcastEpisodeResponse])
async def list_podcast_episodes():
    """List all podcast episodes"""
    try:
        episodes = await PodcastService.list_episodes()

        # Batch-fetch job status for every episode with a command in one
        # query instead of one round trip per episode (see
        # PodcastEpisode.get_job_details_for_commands docstring).
        try:
            details_by_command = await PodcastEpisode.get_job_details_for_commands(
                [episode.command for episode in episodes if episode.command]
            )
        except Exception as e:
            logger.warning(f"Error batch-fetching podcast job statuses: {str(e)}")
            details_by_command = {}

        # Batch-resolve the snapshots' model references (outline_llm,
        # transcript_llm, voice_model) to display fields in one query
        # instead of one lookup per episode.
        models_by_id = await _resolve_snapshot_models(episodes)

        response_episodes = []
        for episode in episodes:
            # Skip incomplete episodes without command or audio
            if not episode.command and not episode.audio_file:
                continue

            # Get job status and error message if available
            job_status = None
            error_message = None
            if episode.command:
                detail = details_by_command.get(str(episode.command))
                if detail is not None:
                    job_status = detail["status"]
                    error_message = detail["error_message"]
                else:
                    job_status = "unknown"
            else:
                # No command but has audio file = completed import
                job_status = "completed"

            audio_url = None
            audio_path = resolve_contained_audio_path(episode.audio_file)
            if audio_path is not None and audio_path.exists():
                audio_url = f"/api/podcasts/episodes/{episode.id}/audio"

            response_episodes.append(
                PodcastEpisodeResponse(
                    id=str(episode.id),
                    name=episode.name,
                    episode_profile=_with_resolved_model_fields(
                        episode.episode_profile,
                        _EPISODE_PROFILE_MODEL_FIELDS,
                        models_by_id,
                    ),
                    speaker_profile=_with_resolved_model_fields(
                        episode.speaker_profile,
                        _SPEAKER_PROFILE_MODEL_FIELDS,
                        models_by_id,
                    ),
                    briefing=episode.briefing,
                    audio_file=episode.audio_file,
                    audio_url=audio_url,
                    transcript=episode.transcript,
                    outline=episode.outline,
                    created=str(episode.created) if episode.created else None,
                    pipeline_progress=podcast_progress(str(episode.id), job_status),
                    job_status=job_status,
                    error_message=error_message,
                )
            )

        return response_episodes

    except HTTPException:
        raise
    except OpenNotebookError:
        raise
    except Exception as e:
        logger.error(f"Error listing podcast episodes: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to list podcast episodes")


@router.get("/podcasts/episodes/{episode_id}", response_model=PodcastEpisodeResponse)
async def get_podcast_episode(episode_id: str):
    """Get a specific podcast episode"""
    try:
        episode = await PodcastService.get_episode(episode_id)

        # Get job status and error message if available
        job_status = None
        error_message = None
        if episode.command:
            try:
                detail = await episode.get_job_detail()
                job_status = detail["status"]
                error_message = detail["error_message"]
            except Exception:
                job_status = "unknown"
        else:
            # No command but has audio file = completed import
            job_status = "completed" if episode.audio_file else "unknown"

        audio_url = None
        audio_path = resolve_contained_audio_path(episode.audio_file)
        if audio_path is not None and audio_path.exists():
            audio_url = f"/api/podcasts/episodes/{episode.id}/audio"

        models_by_id = await _resolve_snapshot_models([episode])

        return PodcastEpisodeResponse(
            id=str(episode.id),
            name=episode.name,
            episode_profile=_with_resolved_model_fields(
                episode.episode_profile,
                _EPISODE_PROFILE_MODEL_FIELDS,
                models_by_id,
            ),
            speaker_profile=_with_resolved_model_fields(
                episode.speaker_profile,
                _SPEAKER_PROFILE_MODEL_FIELDS,
                models_by_id,
            ),
            briefing=episode.briefing,
            audio_file=episode.audio_file,
            audio_url=audio_url,
            transcript=episode.transcript,
            outline=episode.outline,
            created=str(episode.created) if episode.created else None,
            pipeline_progress=podcast_progress(str(episode.id), job_status),
            job_status=job_status,
            error_message=error_message,
        )

    except HTTPException:
        raise
    except OpenNotebookError:
        raise
    except Exception as e:
        logger.error(f"Error fetching podcast episode: {str(e)}")
        raise HTTPException(status_code=404, detail="Episode not found")


@router.get("/podcasts/episodes/{episode_id}/audio")
async def stream_podcast_episode_audio(episode_id: str):
    """Stream the audio file associated with a podcast episode"""
    try:
        episode = await PodcastService.get_episode(episode_id)
    except HTTPException:
        raise
    except OpenNotebookError:
        raise
    except Exception as e:
        logger.error(f"Error fetching podcast episode for audio: {str(e)}")
        raise HTTPException(status_code=404, detail="Episode not found")

    if not episode.audio_file:
        raise HTTPException(status_code=404, detail="Episode has no audio file")

    audio_path = resolve_contained_audio_path(episode.audio_file)
    if audio_path is None:
        logger.warning(
            f"Blocked audio access outside podcasts directory for episode "
            f"{episode_id}: {episode.audio_file}"
        )
        raise HTTPException(status_code=403, detail="Access to file denied")

    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found on disk")

    return FileResponse(
        audio_path,
        media_type="audio/mpeg",
        filename=audio_path.name,
    )


@router.post("/podcasts/episodes/{episode_id}/retry")
async def retry_podcast_episode(episode_id: str):
    """Retry a failed podcast episode by deleting it and submitting a new job"""
    try:
        episode = await PodcastService.get_episode(episode_id)

        if (episode.transcript or {}).get("audio_edit"):
            from api.podcast_edit_service import retry_audio

            return await retry_audio(episode_id)

        if (episode.transcript or {}).get("draft"):
            from api.podcast_edit_service import regenerate_audio
            from open_notebook.podcasts.transcripts import revision

            return await regenerate_audio(episode_id, revision(episode.transcript))

        # Validate episode is in a failed state
        detail = await episode.get_job_detail()
        if detail["status"] not in ("failed", "error"):
            raise HTTPException(
                status_code=400,
                detail=f"Episode is not in a failed state (current: {detail['status']})",
            )

        # Extract params for re-submission
        ep_profile_name = episode.episode_profile.get("name")
        sp_profile_name = episode.speaker_profile.get("name")
        episode_name = episode.name
        content = episode.content

        if not ep_profile_name or not sp_profile_name:
            raise HTTPException(
                status_code=400,
                detail="Cannot retry: episode or speaker profile name missing from stored data",
            )

        # Delete audio file if any
        _delete_episode_audio(episode, episode_id)

        # Delete the failed episode
        await episode.delete()

        # Submit a new job
        job_id = await PodcastService.submit_generation_job(
            episode_profile_name=ep_profile_name,
            speaker_profile_name=sp_profile_name,
            episode_name=episode_name,
            content=content,
        )

        return {"job_id": job_id, "message": "Retry submitted successfully"}

    except HTTPException:
        raise
    except OpenNotebookError:
        raise
    except Exception as e:
        logger.error(f"Error retrying podcast episode: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to retry episode")


@router.delete("/podcasts/episodes/{episode_id}")
async def delete_podcast_episode(episode_id: str):
    """Delete a podcast episode and its associated audio file"""
    try:
        # Get the episode first to check if it exists and get the audio file path
        episode = await PodcastService.get_episode(episode_id)

        # Delete the physical audio file if it exists
        _delete_episode_audio(episode, episode_id)

        # Delete the episode from the database
        await episode.delete()

        logger.info(f"Deleted podcast episode: {episode_id}")
        return {"message": "Episode deleted successfully", "episode_id": episode_id}

    except HTTPException:
        raise
    except OpenNotebookError:
        raise
    except Exception as e:
        logger.error(f"Error deleting podcast episode: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to delete episode")


class VoicePreviewRequest(BaseModel):
    model_id: str
    voice_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.+:-]+$")


@router.get("/podcasts/voices")
async def list_preview_voices(model_id: str):
    from api.voice_preview_service import voices

    return await voices(model_id)


@router.post("/podcasts/voices/preview")
async def preview_voice(request: VoicePreviewRequest):
    from api.voice_preview_service import preview

    path = await preview(request.model_id, request.voice_id)
    return FileResponse(
        path,
        media_type="audio/mpeg",
        headers={"Cache-Control": "private, max-age=3600"},
    )


class TranscriptTurn(BaseModel):
    speaker: str
    dialogue: str = Field(min_length=1, max_length=12000)


class TranscriptDraftRequest(BaseModel):
    expected_revision: int = Field(ge=0)
    entries: List[TranscriptTurn] = Field(min_length=1, max_length=2000)


class AudioRevisionRequest(BaseModel):
    expected_revision: int = Field(ge=0)
    reuse_unchanged: bool = True


@router.put("/podcasts/episodes/{episode_id}/transcript")
async def save_transcript_draft(episode_id: str, request: TranscriptDraftRequest):
    from api.podcast_edit_service import save_draft

    return await save_draft(
        episode_id,
        request.expected_revision,
        [entry.model_dump() for entry in request.entries],
    )


@router.post("/podcasts/episodes/{episode_id}/regenerate-audio")
async def regenerate_episode_audio(episode_id: str, request: AudioRevisionRequest):
    from api.podcast_edit_service import regenerate_audio

    return await regenerate_audio(
        episode_id, request.expected_revision, request.reuse_unchanged
    )


@router.get("/podcasts/voice-cloning/models")
async def cloning_models():
    from api.voice_cloning_service import models

    return await models()


@router.get("/podcasts/voice-cloning/voices")
async def cloning_voices(model_id: str, archived: bool = False):
    from api.voice_cloning_service import request

    return (
        await request(
            model_id, "GET", "clones", params={"archived": str(archived).lower()}
        )
    ).json()


@router.post("/podcasts/voice-cloning/voices")
async def create_cloned_voice(
    model_id: str = Form(...),
    name: str = Form(...),
    file: UploadFile = File(...),
    reference_text: str = Form(""),
):
    from api.voice_cloning_service import MAX_BYTES, request
    from open_notebook.exceptions import InvalidInputError

    try:
        audio = await file.read(MAX_BYTES + 1)
        if len(audio) > MAX_BYTES:
            raise InvalidInputError("Upload an audio sample up to 10 MB")
        if not name.strip() or len(name.strip()) > 80:
            raise InvalidInputError("Enter a voice name of 1–80 characters")
        return (
            await request(
                model_id,
                "POST",
                "clones",
                data={"name": name, "reference_text": reference_text},
                files={"file": ("reference", audio, "application/octet-stream")},
            )
        ).json()
    finally:
        await file.close()


class CloneArchiveRequest(BaseModel):
    archived: bool


@router.patch("/podcasts/voice-cloning/voices/{voice_id}")
async def archive_cloned_voice(voice_id: str, model_id: str, body: CloneArchiveRequest):
    from api.voice_cloning_service import request

    return (
        await request(
            model_id,
            "PATCH",
            "clones/" + valid_clone_id(voice_id),
            json=body.model_dump(),
        )
    ).json()


def valid_clone_id(voice_id):
    import re

    from open_notebook.exceptions import InvalidInputError

    if not re.fullmatch(r"clone_[a-f0-9]{32}", voice_id):
        raise InvalidInputError("Invalid saved voice")
    return voice_id


@router.get("/podcasts/voice-cloning/voices/{voice_id}/reference")
async def cloned_voice_reference(voice_id: str, model_id: str):
    from api.voice_cloning_service import request

    response = await request(
        model_id, "GET", "clones/" + valid_clone_id(voice_id) + "/reference"
    )
    return Response(
        response.content, media_type="audio/wav", headers={"Cache-Control": "no-store"}
    )
