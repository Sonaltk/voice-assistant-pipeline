"""
Wraps one Cartesia streaming WebSocket connection for synthesizing a single
complete reply into speech.

Like DeepgramASR, this opens a fresh connection per call rather than staying
persistently connected -- simplest correct behavior for a push-to-talk,
one-reply-per-turn pipeline.

Design note: Cartesia's protocol is built around "contexts" (context_id) that
let you feed text to a single synthesis job in pieces, useful for streaming
LLM tokens straight into TTS sentence-by-sentence for lower latency. Step 5
uses the simpler shape -- one complete piece of text, "continue": false --
since we wait for the LLM's full reply first. Switching to per-sentence
streaming later is a natural Phase 2/3 latency optimization once there's
real timing data to justify it.
"""

import base64
import json
import logging
import os
import uuid

import websockets

log = logging.getLogger("tts")

CARTESIA_URL = "wss://api.cartesia.ai/tts/websocket"
CARTESIA_VERSION = "2026-03-01"
DEFAULT_MODEL = "sonic-3.5"
OUTPUT_SAMPLE_RATE = 24000  # Hz -- the rate we ask Cartesia to render PCM16 audio at


class CartesiaTTS:
    def __init__(self, api_key: str | None = None, voice_id: str | None = None, model: str = DEFAULT_MODEL):
        self.api_key = api_key or os.environ.get("CARTESIA_API_KEY")
        if not self.api_key:
            raise RuntimeError(
                "CARTESIA_API_KEY is not set. Add it to a .env file in the project root."
            )
        self.voice_id = voice_id or os.environ.get("CARTESIA_VOICE_ID")
        if not self.voice_id:
            raise RuntimeError(
                "CARTESIA_VOICE_ID is not set. Add it to a .env file -- "
                "copy a voice ID from the Voices library in the Cartesia console."
            )
        self.model = model

    async def synthesize(self, text: str, on_audio_chunk=None) -> None:
        """
        Sends the given text to Cartesia as one complete utterance and streams
        the resulting PCM16 audio back, calling on_audio_chunk(bytes) for each
        chunk as it's generated. Returns once Cartesia signals the utterance
        is fully synthesized.
        """
        context_id = str(uuid.uuid4())

        async with websockets.connect(
            CARTESIA_URL,
            extra_headers={
                "X-API-Key": self.api_key,
                "Cartesia-Version": CARTESIA_VERSION,
            },
        ) as ws:
            request = {
                "transcript": text,
                "continue": False,  # this is the whole utterance, nothing more follows
                "context_id": context_id,
                "model_id": self.model,
                "voice": {"mode": "id", "id": self.voice_id},
                "output_format": {
                    "container": "raw",
                    "encoding": "pcm_s16le",
                    "sample_rate": OUTPUT_SAMPLE_RATE,
                },
                "language": "en",
            }
            await ws.send(json.dumps(request))

            async for raw in ws:
                msg = json.loads(raw)
                msg_type = msg.get("type")

                if msg_type == "chunk":
                    audio_bytes = base64.b64decode(msg["data"])
                    if on_audio_chunk is not None:
                        await on_audio_chunk(audio_bytes)
                elif msg_type == "done":
                    break
                elif msg_type == "error":
                    raise RuntimeError(f"Cartesia error: {msg}")
                # "timestamps" and "flush_done" messages are ignored for now
