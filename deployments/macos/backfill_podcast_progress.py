"""Recover one single-worker episode's content-free stages from saved worker logs.

Run inside the matching application image; logs arrive on stdin. This is a
one-time migration for a run predating live instrumentation, not a log daemon.
"""

import argparse
import re
import sys
from datetime import datetime, timezone

from open_notebook.podcasts.progress import consume, update

parser = argparse.ArgumentParser()
parser.add_argument("--episode", required=True)
parser.add_argument("--started-at", required=True)
args = parser.parse_args()
start = datetime.fromisoformat(args.started_at).timestamp()
update(args.episode, "preparing", started_at=start, at=start, recovered_from_logs=True)
for line in sys.stdin:
    match = re.match(r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d+).*? - (.*)", line)
    if not match:
        continue
    stamp = datetime.fromisoformat(match[1]).replace(tzinfo=timezone.utc).timestamp()
    if stamp < start:
        continue
    text = match[2]
    if "podcast_creator.nodes:" in line:
        consume(args.episode, text, at=stamp)
    if "Successfully generated podcast episode: " + args.episode + " " in text:
        update(args.episode, "completed", at=stamp, finished_at=stamp)
        break
