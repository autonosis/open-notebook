"""Editing preserves original audio; regeneration never runs language models."""

import asyncio
import copy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from api import podcast_edit_service as edit
from commands import podcast_audio_commands as audio
from open_notebook.podcasts import progress
from open_notebook.podcasts.transcripts import entries, validate_turns

TURNS = [
    {"speaker": "Host", "dialogue": "A graph records assumptions."},
    {"speaker": "Guest", "dialogue": "Assumptions need evidence."},
]
SPEAKERS = {
    "voice_model": "model:kokoro",
    "speakers": [
        {"name": "Host", "voice_id": "af_heart"},
        {"name": "Guest", "voice_id": "am_michael"},
    ],
}


class Record:
    store = {}

    def __init__(self, **data):
        self.__dict__.update(data)
        self.id = data.get("id")
        self.command = data.get("command")
        self.audio_file = data.get("audio_file")

    async def save(self):
        if not self.id:
            self.id = "episode:child" + str(len(self.store))
        self.store[str(self.id)] = self

    @classmethod
    async def get(cls, key):
        return cls.store[str(key)]

    async def get_job_status(self):
        return "pending" if self.command else "completed" if self.audio_file else None


@pytest.fixture
def records(monkeypatch):
    Record.store = {}
    source = Record(
        id="episode:source",
        name="Episode",
        episode_profile={},
        speaker_profile=copy.deepcopy(SPEAKERS),
        briefing="Keep grounded.",
        content="Source.",
        audio_file="original.mp3",
        transcript={"transcript": copy.deepcopy(TURNS)},
        outline={},
    )
    Record.store[source.id] = source
    monkeypatch.setattr(edit, "PodcastEpisode", Record)
    monkeypatch.setattr(audio, "PodcastEpisode", Record)
    return source


@pytest.mark.asyncio
async def test_save_draft_keeps_audio_script_and_rejects_stale_saves(
    records, monkeypatch
):
    database = AsyncMock(return_value=[{"id": records.id}])
    monkeypatch.setattr(edit, "repo_query", database)
    changed = copy.deepcopy(TURNS)
    changed[0]["dialogue"] = "A causal graph makes assumptions explicit."
    draft = await edit.save_draft(records.id, 0, changed)
    assert draft["revision"] == 1
    assert records.audio_file == "original.mp3" and entries(records.transcript) == TURNS
    records.transcript["draft"] = draft
    with pytest.raises(HTTPException) as error:
        await edit.save_draft(records.id, 0, changed)
    assert error.value.status_code == 409
    database.return_value = []
    with pytest.raises(HTTPException) as error:
        await edit.save_draft(records.id, 1, changed)
    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_duplicate_generate_requests_submit_one_audio_job(records, monkeypatch):
    records.transcript["draft"] = {"revision": 1, "entries": copy.deepcopy(TURNS)}

    async def query(sql, values):
        target = Record.store[str(values["episode"])]
        if "output_episode" in sql:
            target.transcript["draft"]["output_episode"] = values["child"]
        elif "SET command" in sql:
            target.command = str(values["command"])
        return [{"id": target.id}]

    monkeypatch.setattr(edit, "repo_query", query)
    submit = Mock(return_value="command:render")
    monkeypatch.setattr(edit, "submit_command", submit)
    results = await asyncio.gather(
        edit.regenerate_audio(records.id, 1), edit.regenerate_audio(records.id, 1)
    )
    assert results[0]["episode_id"] == results[1]["episode_id"]
    assert submit.call_count == 1
    assert submit.call_args.args[1] == "regenerate_podcast_audio"
    child = Record.store[results[0]["episode_id"]]
    assert child.speaker_profile == records.speaker_profile
    assert records.audio_file == "original.mp3" and child.audio_file is None


def test_unknown_speaker_empty_turn_and_nested_legacy_envelope():
    assert entries({"transcript": {"transcript": TURNS}}) == TURNS
    for turns in [
        [{"speaker": "Invented", "dialogue": "Hello"}],
        [{"speaker": "Host", "dialogue": " "}],
    ]:
        with pytest.raises(ValueError):
            validate_turns(turns, SPEAKERS)


@pytest.mark.asyncio
async def test_audio_only_render_reuses_unchanged_clip_and_publishes_last(
    records, monkeypatch, tmp_path
):
    original = tmp_path / "old/audio/original.mp3"
    original.parent.mkdir(parents=True)
    original.write_bytes(b"original audio")
    clips = tmp_path / "old/clips"
    clips.mkdir()
    (clips / "0000.mp3").write_bytes(b"A" * 200)
    (clips / "0001.mp3").write_bytes(b"B" * 200)
    revised = copy.deepcopy(TURNS)
    revised[0]["dialogue"] = "A causal graph makes assumptions explicit."
    child = Record(
        id="episode:child",
        speaker_profile=copy.deepcopy(SPEAKERS),
        transcript={
            "transcript": revised,
            "audio_edit": {
                "request_id": "request",
                "source_episode": records.id,
                "reuse_unchanged": True,
            },
        },
    )
    Record.store[child.id] = child
    monkeypatch.setattr(audio, "PODCASTS_FOLDER", str(tmp_path / "new"))
    monkeypatch.setattr(progress, "ROOT", tmp_path / "progress")
    monkeypatch.setattr(audio, "resolve_contained_audio_path", lambda _: original)
    monkeypatch.setattr(audio, "to_relative_audio_path", lambda p: str(p))
    speech = AsyncMock()

    async def generate(**kwargs):
        Path(kwargs["output_file"]).write_bytes(b"NEW" * 100)

    speech.side_effect = generate
    factory = Mock(return_value=SimpleNamespace(agenerate_speech=speech))
    monkeypatch.setattr(audio.AIFactory, "create_text_to_speech", factory)
    monkeypatch.setattr(
        audio, "_resolve_model_config", AsyncMock(return_value=("local", "kokoro", {}))
    )

    async def combine(source, name, destination, **kwargs):
        assert (source / "0001.mp3").read_bytes() == b"B" * 200
        destination.mkdir()
        file = destination / name
        file.write_bytes(b"assembled")
        return {"combined_audio_path": str(file)}

    monkeypatch.setattr(audio, "combine_audio_files", combine)
    database = AsyncMock(return_value=[{"id": child.id}])
    monkeypatch.setattr(audio, "repo_query", database)
    result = await audio.render_audio(child.id, "request")
    assert result["clips_generated"] == 1 and result["clips_reused"] == 1
    assert (
        speech.await_count == 1
        and speech.call_args.kwargs["text"] == revised[0]["dialogue"]
    )
    assert original.read_bytes() == b"original audio"
    assert "audio_file" in database.call_args.args[0]


@pytest.mark.asyncio
async def test_speech_failure_never_publishes_or_changes_original(
    records, monkeypatch, tmp_path
):
    child = Record(
        id="episode:failed",
        speaker_profile=SPEAKERS,
        transcript={
            "transcript": copy.deepcopy(TURNS),
            "audio_edit": {
                "request_id": "request",
                "source_episode": records.id,
                "reuse_unchanged": False,
            },
        },
    )
    Record.store[child.id] = child
    monkeypatch.setattr(audio, "PODCASTS_FOLDER", str(tmp_path))
    monkeypatch.setattr(progress, "ROOT", tmp_path / "progress")
    monkeypatch.setattr(audio, "resolve_contained_audio_path", lambda _: None)
    monkeypatch.setattr(
        audio.AIFactory,
        "create_text_to_speech",
        Mock(
            return_value=SimpleNamespace(
                agenerate_speech=AsyncMock(side_effect=RuntimeError("speech offline"))
            )
        ),
    )
    monkeypatch.setattr(
        audio, "_resolve_model_config", AsyncMock(return_value=("local", "kokoro", {}))
    )
    database = AsyncMock()
    monkeypatch.setattr(audio, "repo_query", database)
    with pytest.raises(RuntimeError):
        await audio.render_audio(child.id, "request")
    assert child.audio_file is None and records.audio_file == "original.mp3"
    assert database.await_count == 0
    assert progress.read(child.id)["stage"] == "failed"


@pytest.mark.asyncio
async def test_different_reuse_policy_creates_new_render(records, monkeypatch):
    records.transcript["draft"] = {"revision": 1, "entries": copy.deepcopy(TURNS)}

    async def query(sql, values):
        target = Record.store[str(values["episode"])]
        if "output_episode" in sql:
            target.transcript["draft"]["output_episode"] = values["child"]
        elif "SET command" in sql:
            target.command = str(values["command"])
        return [{"id": target.id}]

    monkeypatch.setattr(edit, "repo_query", query)
    submit = Mock(side_effect=["command:first", "command:second"])
    monkeypatch.setattr(edit, "submit_command", submit)
    a = await edit.regenerate_audio(records.id, 1, True)
    b = await edit.regenerate_audio(records.id, 1, False)
    assert a["episode_id"] != b["episode_id"] and submit.call_count == 2


def test_retry_progress_resets_finished_time_and_error(monkeypatch, tmp_path):
    monkeypatch.setattr(progress, "ROOT", tmp_path)
    progress.update(
        "episode:retry", "failed", started_at=1, finished_at=2, error_type="OldError"
    )
    progress.update("episode:retry", "speech", reset=True, started_at=3, clips_done=0)
    result = progress.snapshot("episode:retry", "running")
    assert result["stage"] == "speech" and "error_type" not in result
    assert "finished_at" not in result and len(result["timeline"]) == 1


@pytest.mark.asyncio
async def test_unknown_job_status_does_not_duplicate_speech(monkeypatch):
    record = Record(
        id="episode:pending",
        command="command:existing",
        name="Pending",
        transcript={"audio_edit": {}},
    )
    record.get_job_status = AsyncMock(return_value="unknown")
    submit = Mock()
    monkeypatch.setattr(edit, "submit_command", submit)
    result = await edit._submit(record)
    assert result["job_id"] == "command:existing"
    submit.assert_not_called()


@pytest.mark.asyncio
async def test_render_submission_conflict_does_not_leave_an_orphan(
    records, monkeypatch
):
    records.transcript["draft"] = {"revision": 1, "entries": copy.deepcopy(TURNS)}
    database = AsyncMock(return_value=[])
    monkeypatch.setattr(edit, "repo_query", database)
    submit = Mock()
    monkeypatch.setattr(edit, "submit_command", submit)
    with pytest.raises(HTTPException) as error:
        await edit.regenerate_audio(records.id, 1)
    assert error.value.status_code == 409
    submit.assert_not_called()
    assert database.call_args.args[0] == "DELETE $episode"
    assert str(database.call_args.args[1]["episode"]) != records.id


@pytest.mark.asyncio
async def test_retry_with_saved_edits_uses_audio_only_render(monkeypatch):
    from api.routers import podcasts

    episode = SimpleNamespace(
        transcript={"transcript": TURNS, "draft": {"revision": 4, "entries": TURNS}}
    )
    monkeypatch.setattr(
        podcasts.PodcastService, "get_episode", AsyncMock(return_value=episode)
    )
    generate = AsyncMock(
        return_value={"episode_id": "episode:revised", "job_id": "command:audio"}
    )
    monkeypatch.setattr(edit, "regenerate_audio", generate)
    original = AsyncMock()
    monkeypatch.setattr(podcasts.PodcastService, "submit_generation_job", original)
    result = await podcasts.retry_podcast_episode("episode:original")
    assert result["job_id"] == "command:audio"
    generate.assert_awaited_once_with("episode:original", 4)
    original.assert_not_called()


@pytest.mark.asyncio
async def test_deleted_source_falls_back_to_synthesis(monkeypatch, tmp_path):
    from open_notebook.exceptions import NotFoundError

    child = Record(
        id="episode:child",
        speaker_profile=SPEAKERS,
        transcript={
            "transcript": TURNS,
            "audio_edit": {
                "request_id": "request",
                "source_episode": "episode:deleted",
                "reuse_unchanged": True,
            },
        },
    )

    async def get(key):
        if str(key) == "episode:deleted":
            raise NotFoundError("Deleted source")
        return child

    monkeypatch.setattr(audio.PodcastEpisode, "get", get)
    monkeypatch.setattr(audio, "PODCASTS_FOLDER", str(tmp_path))
    monkeypatch.setattr(progress, "ROOT", tmp_path / "progress")
    monkeypatch.setattr(
        audio, "_resolve_model_config", AsyncMock(return_value=("local", "kokoro", {}))
    )

    async def synthesize(**kwargs):
        Path(kwargs["output_file"]).write_bytes(b"new" * 100)

    monkeypatch.setattr(
        audio.AIFactory,
        "create_text_to_speech",
        Mock(return_value=SimpleNamespace(agenerate_speech=synthesize)),
    )

    async def combine(clips, name, output, **kwargs):
        output.mkdir()
        file = output / name
        file.write_bytes(b"combined")
        return {"combined_audio_path": str(file)}

    monkeypatch.setattr(audio, "combine_audio_files", combine)
    monkeypatch.setattr(audio, "to_relative_audio_path", str)
    monkeypatch.setattr(audio, "repo_query", AsyncMock(return_value=[{"id": child.id}]))
    result = await audio.render_audio(child.id, "request")
    assert result["clips_generated"] == 2 and result["clips_reused"] == 0


@pytest.mark.asyncio
async def test_deleted_revision_can_be_generated_again(records, monkeypatch):
    from open_notebook.exceptions import NotFoundError

    records.transcript["draft"] = {
        "revision": 1,
        "entries": copy.deepcopy(TURNS),
        "output_episode": "episode:deleted",
    }
    original_get = Record.get

    async def get(key):
        if key == "episode:deleted":
            raise NotFoundError("Deleted revision")
        return await original_get(key)

    monkeypatch.setattr(Record, "get", get)
    monkeypatch.setattr(
        edit, "repo_query", AsyncMock(return_value=[{"id": records.id}])
    )
    submit = Mock(return_value="command:replacement")
    monkeypatch.setattr(edit, "submit_command", submit)
    result = await edit.regenerate_audio(records.id, 1)
    assert result["episode_id"] != "episode:deleted"
    assert submit.call_count == 1
