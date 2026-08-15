"""
Every event that flows through Session.send() gets appended here as one JSON
line. This is deliberately simple -- no database, no schema -- because all
Phase 2 needs is "every event, in order, on disk," and a JSONL file gives us
that with zero setup.

Note on blocking I/O: this uses a plain synchronous file write inside an
otherwise fully async server. For this project's request volume that's a
non-issue (writing one short line is microseconds), but it's worth naming
as a known simplification -- a high-throughput version of this server would
move logging onto a background queue instead, so a slow disk can never stall
the event loop that's also handling live WebSocket traffic. That kind of
fix is exactly the sort of thing Phase 3's resilience work is about.
"""

import json
import os
import threading

LOG_PATH = os.environ.get("METRICS_LOG_PATH", "logs/events.jsonl")

_lock = threading.Lock()


def log_event(event: dict) -> None:
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with _lock:
        with open(LOG_PATH, "a") as f:
            f.write(json.dumps(event) + "\n")
