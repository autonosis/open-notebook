"""Transcript envelopes preserve the script associated with existing audio."""

from typing import Any


def entries(envelope: Any) -> list[dict]:
    value = (envelope or {}).get("transcript", [])
    # Accept a historical nested parser envelope as well as the current list.
    if isinstance(value, dict):
        value = value.get("transcript", [])
    return value if isinstance(value, list) else []


def revision(envelope: dict) -> int:
    return int(
        (envelope.get("draft") or {}).get("revision", envelope.get("revision", 0))
    )


def validate_turns(turns: list[dict], speaker_snapshot: dict) -> None:
    names = {speaker["name"] for speaker in speaker_snapshot.get("speakers", [])}
    if not turns or len(turns) > 2000:
        raise ValueError("A transcript must contain between 1 and 2000 turns.")
    for turn in turns:
        if set(turn) != {"speaker", "dialogue"} or turn["speaker"] not in names:
            raise ValueError(
                "Each turn must use a speaker from the episode's saved profile."
            )
        if not isinstance(turn["dialogue"], str) or not turn["dialogue"].strip():
            raise ValueError("Every turn needs spoken text.")
        if len(turn["dialogue"]) > 12000:
            raise ValueError(
                "Split turns longer than 12000 characters before generating audio."
            )
