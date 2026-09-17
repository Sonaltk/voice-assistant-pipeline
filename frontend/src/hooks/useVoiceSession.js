import { useState, useRef, useCallback } from "react";

const WS_URL =
  import.meta.env.VITE_WS_URL ||
  `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}/ws`;

export function useVoiceSession() {
  const [connected, setConnected] = useState(false);
  const [micReady, setMicReady] = useState(false);
  const [recording, setRecording] = useState(false);
  const [log, setLog] = useState([]);

  // Refs, not state -- these are mutable objects we read/write imperatively
  // (WebSocket, AudioContext, etc.), not values the UI renders from directly.
  const wsRef = useRef(null);
  const audioContextRef = useRef(null);
  const workletNodeRef = useRef(null);
  const micStreamRef = useRef(null);
  const nextPlayTimeRef = useRef(0);

  const appendLog = useCallback((msg) => {
    setLog((prev) => [...prev, `${new Date().toLocaleTimeString()}  ${msg}`]);
  }, []);

  const playPCM16Chunk = useCallback((base64Audio, sampleRate) => {
    const audioContext = audioContextRef.current;
    const binary = atob(base64Audio);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);

    const int16 = new Int16Array(bytes.buffer);
    const float32 = new Float32Array(int16.length);
    for (let i = 0; i < int16.length; i++) float32[i] = int16[i] / 32768;

    const buffer = audioContext.createBuffer(1, float32.length, sampleRate);
    buffer.copyToChannel(float32, 0);

    const source = audioContext.createBufferSource();
    source.buffer = buffer;
    source.connect(audioContext.destination);

    const startAt = Math.max(audioContext.currentTime, nextPlayTimeRef.current);
    source.start(startAt);
    nextPlayTimeRef.current = startAt + buffer.duration;
  }, []);

  const connect = useCallback(async () => {
    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = async () => {
      appendLog("connected to server");
      setConnected(true);

      const micStream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });
      micStreamRef.current = micStream;

      const audioContext = new AudioContext();
      audioContextRef.current = audioContext;
      await audioContext.audioWorklet.addModule("/pcm-worklet-processor.js");

      const source = audioContext.createMediaStreamSource(micStream);
      const workletNode = new AudioWorkletNode(audioContext, "pcm-worklet-processor");
      workletNodeRef.current = workletNode;
      source.connect(workletNode);

      workletNode.port.onmessage = (event) => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(event.data); // binary PCM16 chunk
        }
      };

      appendLog(`mic ready (sample rate: ${audioContext.sampleRate} Hz)`);
      setMicReady(true);
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === "tts_chunk") {
        playPCM16Chunk(data.audio_b64, data.sample_rate);
        appendLog(`playing audio chunk`);
      } else {
        appendLog(`received: ${event.data}`);
      }
    };

    ws.onclose = () => {
      appendLog("disconnected");
      setConnected(false);
      setMicReady(false);
    };

    ws.onerror = (err) => appendLog(`error: ${err.message || "unknown"}`);
  }, [appendLog, playPCM16Chunk]);

  const startTalking = useCallback(() => {
    if (recording || !audioContextRef.current) return;
    setRecording(true);
    wsRef.current.send(
      JSON.stringify({
        type: "session_start",
        sample_rate: audioContextRef.current.sampleRate,
      })
    );
    appendLog("recording started");
  }, [recording, appendLog]);

  const stopTalking = useCallback(() => {
    if (!recording) return;
    setRecording(false);
    wsRef.current.send(JSON.stringify({ type: "session_end" }));
    appendLog("recording stopped");
  }, [recording, appendLog]);

  return { connected, micReady, recording, log, connect, startTalking, stopTalking };
}