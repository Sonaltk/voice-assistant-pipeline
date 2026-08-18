import json
import logging
import base64

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from app.tts import CartesiaTTS, OUTPUT_SAMPLE_RATE

from app.asr import DeepgramASR
from app.events import EventType
from app.llm import GroqReasoner
from app.session import Session, SessionState
from app.metrics_reducer import all_breakdowns
#tts = CartesiaTTS()

load_dotenv()  # reads DEEPGRAM_API_KEY / ANTHROPIC_API_KEY (and later TTS keys) from .env

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("orchestrator")

app = FastAPI()

# One shared reasoner for the whole app, not one per session -- unlike
# DeepgramASR, a Claude streaming call holds no persistent connection to
# manage, so there's nothing session-specific to isolate. Built once here so
# a bad/missing ANTHROPIC_API_KEY fails loudly at startup instead of quietly
# per-request later.
llm = GroqReasoner()
tts = CartesiaTTS()

# session_id -> Session, so later stages (TTS wiring) can look up state
# without threading it through every function call.
sessions: dict[str, Session] = {}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    session = Session(ws)
    sessions[session.id] = session
    log.info(f"[connect] session={session.id} total={len(sessions)}")

    try:
        while True:
            message = await ws.receive()

            if message["type"] == "websocket.disconnect":
                raise WebSocketDisconnect

            if "bytes" in message and message["bytes"] is not None:
                # Real audio frame: forward straight to the active Deepgram
                # connection for this request, if one is open.
                if session.asr is not None:
                    await session.asr.send_audio(message["bytes"])
                continue

            if "text" not in message or message["text"] is None:
                continue

            try:
                msg = json.loads(message["text"])
            except json.JSONDecodeError:
                await session.send(EventType.ERROR, message="invalid JSON")
                continue

            msg_type = msg.get("type")

            if msg_type == EventType.SESSION_START.value:
                request_id = session.start_request()
                sample_rate = msg.get("sample_rate", 16000)
                log.info(
                    f"[session_start] session={session.id} request={request_id} "
                    f"sample_rate={sample_rate}"
                )

                async def send_partial(text: str, _session=session) -> None:
                    # Live captions while the user is still talking -- not
                    # persisted anywhere, purely for UI feedback.
                    await _session.send(
                        EventType.ASR_PARTIAL,
                        request_id=_session.current_request_id,
                        text=text,
                    )

                try:
                    session.asr = DeepgramASR(sample_rate, on_partial=send_partial)
                    await session.asr.connect()
                except Exception as exc:
                    log.error(f"[asr_error] session={session.id} {exc}")
                    await session.send(EventType.ERROR, message=str(exc))
                    session.asr = None

            elif msg_type == EventType.SESSION_END.value:
                session.set_state(SessionState.IDLE)

                # Fired first, before anything else -- this is the reference
                # point Phase 2's ASR-latency calculation measures from: the
                # exact moment the user stopped talking.
                await session.send(
                    EventType.AUDIO_END, request_id=session.current_request_id
                )

                transcript = ""
                if session.asr is not None:
                    transcript = await session.asr.finish()
                    session.asr = None

                log.info(
                    f"[session_end] session={session.id} "
                    f"request={session.current_request_id} "
                    f"transcript={transcript!r}"
                )

                await session.send(
                    EventType.ASR_FINAL,
                    request_id=session.current_request_id,
                    text=transcript,
                )

                if not transcript:
                    continue  # nothing transcribed (e.g. silence) -- skip the LLM call

                session.set_state(SessionState.THINKING)
                session.history.append({"role": "user", "content": transcript})

                request_id = session.current_request_id

                async def send_token(text_delta: str, _session=session, _rid=request_id) -> None:
                    await _session.send(
                        EventType.LLM_TOKEN, request_id=_rid, token=text_delta
                    )

                try:
                    reply = await llm.stream_reply(session.history, on_token=send_token)
                    session.history.append({"role": "assistant", "content": reply})
                    await session.send(
                        EventType.LLM_DONE, request_id=request_id, text=reply
                    )
                    log.info(f"[llm_done] session={session.id} reply={reply!r}")
                    session.set_state(SessionState.SPEAKING)

                    async def send_audio_chunk(chunk: bytes, _session=session, _rid=request_id) -> None:
                        await _session.send(
                            EventType.TTS_CHUNK,
                            request_id=_rid,
                            audio_b64=base64.b64encode(chunk).decode("ascii"),
                            sample_rate=OUTPUT_SAMPLE_RATE,
                        )

                    await tts.synthesize(reply, on_audio_chunk=send_audio_chunk)
                    await session.send(EventType.TTS_DONE, request_id=request_id)
                except Exception as exc:
                    log.error(f"[llm_error] session={session.id} {exc}")
                    await session.send(EventType.ERROR, message=str(exc))
                    # Roll back the user turn we just added -- otherwise a
                    # failed reply still pollutes history for the next turn.
                    session.history.pop()

                session.set_state(SessionState.IDLE)

            else:
                log.info(f"[unhandled] session={session.id} type={msg_type}")

    except WebSocketDisconnect:
        pass
    finally:
        if session.asr is not None:
            # Client vanished mid-recording -- nothing will call finish(),
            # so make sure the Deepgram connection doesn't leak.
            await session.asr.finish(timeout=1.0)
        sessions.pop(session.id, None)
        log.info(f"[disconnect] session={session.id} total={len(sessions)}")


# Serves index.html and pcm-worklet-processor.js over http://localhost:8080/
# instead of file://, which AudioWorklet requires to load reliably (it needs
# a "secure context" -- localhost counts, file:// often doesn't). Mounted
# last so it acts as a catch-all without shadowing the /ws route above.
@app.get("/api/metrics")
async def get_metrics():
    return all_breakdowns()
app.mount("/", StaticFiles(directory="public", html=True), name="public")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.server:app", host="0.0.0.0", port=8080, reload=False)