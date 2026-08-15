"""
Every event that flows over the WebSocket (in either direction) follows the
same shape: {type, session_id, request_id, ts, ...payload}.

session_id  -> one per WebSocket connection (one user, one conversation)
request_id  -> one per user utterance (one round trip: speech -> reply)
ts          -> epoch milliseconds, set at creation time. This is the field
               Phase 2's latency tracker will reduce over.

Keeping this module as the single source of truth for event names now saves
pain later -- ASR/LLM/TTS modules and the client will all reference these
instead of typing string literals that can drift out of sync.
"""

import time
from enum import StrEnum
from typing import Any


class EventType(StrEnum):
    # client -> server
    AUDIO_CHUNK = "audio_chunk"  # binary audio frame from the mic
    SESSION_START = "session_start"
    SESSION_END = "session_end"

    # server -> client (and internally, stage -> orchestrator)
    AUDIO_END = "audio_end"
    ASR_PARTIAL = "asr_partial"  # interim transcript, not finalized
    ASR_FINAL = "asr_final"  # finalized utterance, triggers the LLM call
    LLM_TOKEN = "llm_token"  # one streamed token/chunk from the LLM
    LLM_DONE = "llm_done"
    TTS_CHUNK = "tts_chunk"  # one chunk of synthesized audio bytes
    TTS_DONE = "tts_done"
    ERROR = "error"


def make_event(event_type: EventType, session_id: str, **payload: Any) -> dict:
    """
    Build a well-formed event dict. Always stamps `ts` at call time so every
    event carries an accurate creation timestamp for later latency analysis
    -- callers should never set ts manually.
    """
    return {
        "type": event_type.value,
        "session_id": session_id,
        "ts": int(time.time() * 1000),
        **payload,
    }