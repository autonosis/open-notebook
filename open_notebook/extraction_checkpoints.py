"""Private, atomic extraction batches keyed by input bytes and processing settings."""

import hashlib
import json
import os
import tempfile
from pathlib import Path


def fingerprint(source, settings):
    digest = hashlib.sha256()
    with open(source, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    digest.update(json.dumps(settings, sort_keys=True).encode())
    return digest.hexdigest()


class BatchCheckpoints:
    def __init__(self, root, key):
        self.directory = Path(root) / key
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)

    def read(self, start, end):
        try:
            record = json.loads((self.directory / f"{start}-{end}.json").read_text())
            payload = json.dumps(record["payload"], sort_keys=True).encode()
            if hashlib.sha256(payload).hexdigest() == record["sha256"]:
                return record["payload"]
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return None

    def write(self, start, end, payload):
        record = {
            "payload": payload,
            "sha256": hashlib.sha256(
                json.dumps(payload, sort_keys=True).encode()
            ).hexdigest(),
        }
        fd, name = tempfile.mkstemp(dir=self.directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump(record, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.directory / f"{start}-{end}.json")
        finally:
            if os.path.exists(name):
                os.unlink(name)
