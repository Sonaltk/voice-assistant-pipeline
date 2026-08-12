"""
Wraps one Deepgram streaming WebSocket connection for the lifetime of a
single push-to-talk utterance (one connection per request, not per session --
each button press is a fully separate transcription as far as Deepgram is
concerned).

Uses Deepgram's raw WebSocket API directly (documented at
https://developers.deepgram.com/docs/lower-level-websockets) rather than
their SDK, since the underlying protocol is simple and this keeps the
dependency surface small and the behavior fully visible.

Design note: because the client tells us exactly when an utterance ends (the
button release -> session_end), we don't rely on Deepgram's silence-based
endpointing to detect end-of-speech. We just forward audio while recording,
then explicitly tell Deepgram "no more audio" and drain whatever final
results come back. Deepgram's own endpointing becomes relevant again once
this project moves to continuous (non-push-to-talk) listening.
"""

import asyncio
import json
import logging
import os

import websockets

log = logging.getLogger("asr")

DEEPGRAM_URL = "wss://api.deepgram.com/v1/listen"


class DeepgramASR:
    def __init__(self, sample_rate: int, on_partial=None, api_key: str | None = None):
        self.sample_rate = sample_rate
        self.on_partial = on_partial  # optional async callback(text: str)
        self.api_key = api_key or os.environ.get("DEEPGRAM_API_KEY")
        if not self.api_key:
            raise RuntimeError(
                "DEEPGRAM_API_KEY is not set. Add it to a .env file in the project root."
            )

        self._ws: websockets.WebSocketClientProtocol | None = None
        self._reader_task: asyncio.Task | None = None
        self._closed_event = asyncio.Event()
        self.final_transcript_parts: list[str] = []

    async def connect(self) -> None:
        params = (
            "encoding=linear16"
            f"&sample_rate={self.sample_rate}"
            "&channels=1"
            "&interim_results=true"
            "&punctuate=true"
            "&model=nova-2"
            "&language=en-US"
        )
        url = f"{DEEPGRAM_URL}?{params}"

        self._ws = await websockets.connect(
            url,
            extra_headers={"Authorization": f"Token {self.api_key}"},
        )
        self._reader_task = asyncio.create_task(self._reader_loop())
        log.info(f"Deepgram connected (sample_rate={self.sample_rate})")

    async def send_audio(self, chunk: bytes) -> None:
        if self._ws is not None:
            await self._ws.send(chunk)

    async def finish(self, timeout: float = 5.0) -> str:
        """
        Tell Deepgram no more audio is coming, wait for it to drain and
        close the connection, then return the combined final transcript.
        """
        if self._ws is None:
            return ""

        await self._ws.send(json.dumps({"type": "CloseStream"}))

        try:
            await asyncio.wait_for(self._closed_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            log.warning("Deepgram did not close within timeout, forcing close")

        await self._ws.close()
        return " ".join(self.final_transcript_parts).strip()

    async def _reader_loop(self) -> None:
        # Single long-running reader for this connection's whole lifetime --
        # both live partials (while recording) and the final drain (after
        # CloseStream) are handled by this same loop, since only one
        # coroutine can consume a websocket's incoming messages at a time.
        try:
            async for raw in self._ws:
                data = json.loads(raw)
                await self._handle_message(data)
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self._closed_event.set()

    async def _handle_message(self, data: dict) -> None:
        if data.get("type") != "Results":
            return  # ignore Metadata / UtteranceEnd / other message types

        alternatives = data.get("channel", {}).get("alternatives", [])
        if not alternatives:
            return

        transcript = alternatives[0].get("transcript", "")
        if not transcript:
            return  # Deepgram sends empty-transcript results during silence

        if data.get("is_final"):
            self.final_transcript_parts.append(transcript)
        elif self.on_partial is not None:
            await self.on_partial(transcript)