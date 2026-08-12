"""
One Session per WebSocket connection. Phase 1 only needs identity and a
simple state machine; ASR/LLM/TTS handles and conversation history get
attached to this same object in later steps rather than introducing a
second place to look for "what's happening in this call".
"""

import uuid
from enum import StrEnum

from fastapi import WebSocket

from app.events import make_event, EventType


class SessionState(StrEnum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"


class Session:
    def __init__(self, ws: WebSocket):
        self.id = str(uuid.uuid4())
        self.ws = ws
        self.state = SessionState.IDLE
        self.current_request_id: str | None = None
        self.history: list[dict] = []  # [{"role": "user"|"assistant", "content": "..."}]
        self.asr = None  # active DeepgramASR connection for the current request, if any

    def start_request(self) -> str:
        self.current_request_id = str(uuid.uuid4())
        self.state = SessionState.LISTENING
        return self.current_request_id

    def set_state(self, state: SessionState) -> None:
        self.state = state

    async def send(self, event_type: EventType, **payload) -> None:
        event = make_event(event_type, self.id, **payload)
        await self.ws.send_json(event)