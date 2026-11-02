"""Bounded, resumable transformations over every part of a large source."""

import hashlib
from pathlib import Path

from open_notebook.config import DATA_FOLDER
from open_notebook.exceptions import IncompleteGenerationError
from open_notebook.extraction_checkpoints import BatchCheckpoints
from open_notebook.observability import event

PART_CHARS = 120_000


def split_parts(text, limit=PART_CHARS):
    parts = []
    while text:
        cut = min(len(text), limit)
        if cut < len(text):
            boundary = text.rfind("\n", limit // 2, cut)
            if boundary > 0:
                cut = boundary + 1
        parts.append(text[:cut])
        text = text[cut:]
    return parts


async def transform_large(
    content, generate, identity, source_id=None, limit=PART_CHARS
):
    key = hashlib.sha256((identity + "\n" + content).encode()).hexdigest()
    cache = BatchCheckpoints(Path(DATA_FOLDER) / "transformation_checkpoints", key)
    level = 0
    while len(content) > limit:
        pieces = split_parts(content, limit)
        outputs = []
        for index, piece in enumerate(pieces):
            event(
                source_id,
                f"Transforming part {index + 1}/{len(pieces)} (level {level + 1})",
            )
            result = cache.read(level, index)
            if result is None:
                result = await generate(piece, "partial")
                cache.write(level, index, result)
            outputs.append(f"[Part {index + 1} of {len(pieces)}]\n{result}")
        reduced = "\n\n".join(outputs)
        if len(reduced) >= len(content):
            raise IncompleteGenerationError(
                "Staged transformation did not reduce input size; completed parts are checkpointed."
            )
        content = reduced
        level += 1
    event(source_id, "Synthesizing final transformation")
    result = cache.read("final", 0)
    if result is None:
        result = await generate(content, "final")
        cache.write("final", 0, result)
    return result
