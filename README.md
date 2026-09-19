# Voice Assistant Pipeline

A real-time, low-latency voice AI pipeline — speak into your browser, get a spoken response back, streamed end-to-end over a single WebSocket connection.

**Live demo:** `https://voice-assistant-nb2a.onrender.com/` *(hosted on Render's free tier — first load may take ~30s to wake the server after inactivity)*

## What it does

Hold a button, talk, release — the assistant transcribes your speech, generates a response, and speaks it back to you, all streamed in real time rather than waiting for each stage to fully complete before starting the next.

```
Browser mic  →  WebSocket  →  FastAPI orchestrator  →  Deepgram (STT)
                                                     →  Groq (LLM)
                                                     →  Cartesia (TTS)
                                                     →  streamed back as audio
```

Every stage of that pipeline is timestamped and logged, and a built-in dashboard visualizes per-stage latency (ASR / LLM / TTS breakdown) — useful for actually seeing where time goes in a voice pipeline, not just assuming it's "fast enough."

## Architecture

- **Frontend**: React (Vite), using the Web Audio API's `AudioWorklet` for real-time mic capture — audio is converted to PCM16 and streamed to the backend in small chunks as you speak, not recorded-then-uploaded
- **Backend**: FastAPI, single WebSocket endpoint (`/ws`), driven by a custom event protocol (`session_start`, `asr_partial`/`asr_final`, `llm_token`/`llm_done`, `tts_chunk`/`tts_done`, `session_end`)
- **STT**: [Deepgram](https://deepgram.com), streaming transcription over its raw WebSocket API
- **LLM**: [Groq](https://groq.com), streamed token-by-token as the response is generated
- **TTS**: [Cartesia](https://cartesia.ai), streamed back as PCM audio chunks and played incrementally in the browser
- **Observability**: every event is logged to a structured JSONL event stream and reduced into latency breakdowns, served at `/api/metrics` and visualized on `/dashboard.html`

## Running it locally

**Requirements:** Python 3.12+, Node 20+, API keys for Deepgram, Groq, and Cartesia.

1. Clone and set up the backend:
   ```bash
   git clone https://github.com/Sonaltk/voice-assistant-pipeline.git
   cd voice-assistant-pipeline
   python -m venv venv && source venv/bin/activate
   pip install -r requirements.txt
   cp .env.example .env   # then fill in your real API keys
   ```

2. Build the frontend:
   ```bash
   cd frontend
   npm install
   npm run build
   cd ..
   ```

3. Run it:
   ```bash
   uvicorn app.server:app --host 0.0.0.0 --port 8080
   ```

4. Open `http://localhost:8080`, click **Connect**, allow mic access, and hold the talk button to speak.

**For frontend development** (hot-reload instead of rebuilding each time), run the backend as above in one terminal, and in another:
```bash
cd frontend
npm run dev
```
This serves the frontend separately on Vite's dev server while still talking to the same backend WebSocket.

## Running it with Docker

```bash
docker build -t voice-assistant .
docker run -p 8080:8080 --env-file .env voice-assistant
```

The Dockerfile does a multi-stage build — it builds the React app in a Node stage, then copies only the built static files into a lean Python runtime image. No Node.js in the final image.

## CI/CD

Every push to `main` triggers a GitHub Actions workflow that builds the Docker image and publishes it to GitHub Container Registry (`ghcr.io`). Deployment to Render is configured to auto-deploy from `main` as well, so a push to `main` results in both a published image and a live redeploy.

## Environment variables

| Variable | Required for |
|---|---|
| `DEEPGRAM_API_KEY` | Speech-to-text |
| `GROQ_API_KEY` | LLM inference |
| `CARTESIA_API_KEY` | Text-to-speech |
| `CARTESIA_VOICE_ID` | Selects the TTS voice (from the Cartesia console's Voices library) |

## Roadmap / possible next steps

- [ ] Interruption handling (let the user talk over the assistant mid-response)
- [ ] Voice activity detection instead of push-to-talk
- [ ] Persisted conversation history across sessions