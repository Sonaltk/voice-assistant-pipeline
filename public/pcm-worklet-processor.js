// Runs on the dedicated audio rendering thread, not the main thread -- this
// keeps PCM conversion isolated from UI work and WebSocket handling so audio
// capture never gets blocked by anything happening elsewhere on the page.
//
// process() is called by the browser roughly every 128 samples (~3ms at
// 48kHz). Sending a message that often would flood postMessage with tiny
// buffers, so we accumulate samples locally and only flush once we have a
// full chunk.

class PCMWorkletProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buffer = [];
    this.chunkSize = 2048; // samples per flushed chunk (~43ms at 48kHz)
  }

  process(inputs) {
    const input = inputs[0];
    if (input.length === 0) return true; // no mic input this render quantum

    const channelData = input[0]; // mono: first channel only
    for (let i = 0; i < channelData.length; i++) {
      this.buffer.push(channelData[i]);
    }

    while (this.buffer.length >= this.chunkSize) {
      const floatChunk = this.buffer.splice(0, this.chunkSize);
      const pcm16 = new Int16Array(floatChunk.length);

      for (let i = 0; i < floatChunk.length; i++) {
        // Clamp to [-1, 1] then scale to the Int16 range. Asymmetric
        // scaling (0x8000 vs 0x7fff) matches the signed 16-bit range
        // exactly, avoiding a one-bit clipping error on the negative side.
        const s = Math.max(-1, Math.min(1, floatChunk[i]));
        pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
      }

      // Transfer (not copy) the underlying buffer to the main thread --
      // this avoids an extra allocation/copy on every chunk.
      this.port.postMessage(pcm16.buffer, [pcm16.buffer]);
    }

    return true; // keep the processor alive
  }
}

registerProcessor("pcm-worklet-processor", PCMWorkletProcessor);