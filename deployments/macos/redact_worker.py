"""Pin-specific privacy fix for surreal-commands' unconditional argument dump."""

import re
from pathlib import Path

p = Path("/app/.venv/lib/python3.12/site-packages/surreal_commands/core/worker.py")
s = p.read_text()
s, n = re.subn(
    r'console\.log\(JSON\(json\.dumps\(([^\n]+\["args"\])\)\)\)',
    r'console.log("Job arguments omitted; correlate using command/source IDs")',
    s,
)
assert n >= 1, "Pinned surreal-commands worker changed; review redaction hook"
p.write_text(s)
# Recover before accepting work: a sole replacement worker cannot have inherited
# a live running coroutine from its predecessor. Never enable for a worker fleet.
needle = "    # Create a semaphore to limit concurrent tasks\n"
assert s.count(needle) == 1
s = s.replace(
    needle,
    "    from open_notebook.observability import recover_interrupted_jobs\n    await recover_interrupted_jobs()\n\n"
    + needle,
)
s = s.replace(" - Args: {cmd.get('args', {})}", "")
p.write_text(s)
