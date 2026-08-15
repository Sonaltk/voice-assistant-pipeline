"""
Reads the raw event log (logs/events.jsonl, written by Session.send() via
metrics.log_event) and reduces it into a per-request latency breakdown.

This module knows nothing about the live pipeline -- it only reads events
that have already happened. That separation matters: it means you can
compute latency stats at any time, even with the server offline, and it
means the dashboard (Phase 2's next piece) has a single, simple function to
call rather than needing to understand the raw event stream itself.
"""

import json
import os
from collections import defaultdict

from app.metrics import LOG_PATH


def load_events_by_request(path: str = LOG_PATH) -> dict[str, list[dict]]:
    """
    Reads the JSONL log and groups every event by request_id. Events without
    a request_id (there shouldn't be many -- mostly just connection-level
    errors) are skipped, since latency is inherently a per-request concept.
    """
    grouped: dict[str, list[dict]] = defaultdict(list)

    if not os.path.exists(path):
        return grouped

    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            event = json.loads(line)
            request_id = event.get("request_id")
            if request_id:
                grouped[request_id].append(event)

    return grouped


def _first_ts(events: list[dict], event_type: str) -> int | None:
    """Returns the ts of the *first* event of the given type, or None if absent."""
    for e in events:
        if e["type"] == event_type:
            return e["ts"]
    return None


def _last_ts(events: list[dict], event_type: str) -> int | None:
    """Returns the ts of the *last* event of the given type, or None if absent."""
    result = None
    for e in events:
        if e["type"] == event_type:
            result = e["ts"]
    return result


def compute_breakdown(events: list[dict]) -> dict:
    """
    Given all events for one request_id, returns the latency breakdown.
    Any stage that never happened (e.g. the LLM call failed, so there's no
    tts_chunk) comes back as None rather than raising -- a partial/failed
    request is still useful to see on the dashboard, just with gaps.
    """
    events = sorted(events, key=lambda e: e["ts"])

    audio_end = _first_ts(events, "audio_end")
    asr_final = _first_ts(events, "asr_final")
    llm_first_token = _first_ts(events, "llm_token")
    llm_done = _first_ts(events, "llm_done")
    tts_first_chunk = _first_ts(events, "tts_chunk")
    tts_done = _first_ts(events, "tts_done")

    def diff(a, b):
        # Both timestamps must exist and be in the expected order --
        # otherwise the stage didn't happen (e.g. no LLM call because the
        # transcript was empty) and reporting a number would be misleading.
        if a is None or b is None:
            return None
        d = b - a
        return d if d >= 0 else None

    return {
        "request_id": events[0]["request_id"],
        "session_id": events[0].get("session_id"),
        "audio_end": audio_end,
        "asr_final": asr_final,
        "llm_first_token": llm_first_token,
        "llm_done": llm_done,
        "tts_first_chunk": tts_first_chunk,
        "tts_done": tts_done,
        "asr_latency_ms": diff(audio_end, asr_final),
        "llm_ttft_ms": diff(asr_final, llm_first_token),
        "llm_total_ms": diff(llm_first_token, llm_done),
        "tts_ttfb_ms": diff(llm_done, tts_first_chunk),
        "tts_total_ms": diff(tts_first_chunk, tts_done),
        "total_ms": diff(audio_end, tts_done),
    }


def all_breakdowns(path: str = LOG_PATH) -> list[dict]:
    """
    Convenience entry point: load the whole log and compute a breakdown for
    every request found in it, most recent first.
    """
    grouped = load_events_by_request(path)
    breakdowns = [compute_breakdown(events) for events in grouped.values()]
    breakdowns.sort(key=lambda b: b.get("audio_end") or 0, reverse=True)
    return breakdowns
