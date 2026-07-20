export type PcmScheduledChunk = {
  duration: number;
  endTime: number;
  startTime: number;
};

export type PcmAudioScheduler = {
  close(): Promise<void>;
  fadeOut(durationMs: number): Promise<void>;
  resume(): Promise<void>;
  schedule(base64Pcm: string, sampleRate: number): Promise<PcmScheduledChunk>;
  suspend(): Promise<void>;
};

export function base64ToPcm16(data: string): Int16Array {
  const binary = globalThis.atob(data);
  const bytes = new Uint8Array(binary.length);

  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }

  const sampleCount = Math.floor(bytes.byteLength / 2);
  const samples = new Int16Array(sampleCount);
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);

  for (let index = 0; index < sampleCount; index += 1) {
    samples[index] = view.getInt16(index * 2, true);
  }

  return samples;
}

export function pcm16ToFloat32(samples: Int16Array): Float32Array<ArrayBuffer> {
  const floats: Float32Array<ArrayBuffer> = new Float32Array(samples.length);

  for (let index = 0; index < samples.length; index += 1) {
    floats[index] = Math.max(-1, Math.min(1, samples[index] / 32768));
  }

  return floats;
}

export function createPcmAudioScheduler(context: AudioContext): PcmAudioScheduler {
  let nextPlaybackTime = context.currentTime;
  const outputGain = context.createGain();
  outputGain.connect(context.destination);

  return {
    async close(): Promise<void> {
      await context.close();
    },

    async fadeOut(durationMs: number): Promise<void> {
      const seconds = Math.max(0.08, Math.min(0.15, durationMs / 1000));
      const now = context.currentTime;
      outputGain.gain.cancelScheduledValues(now);
      outputGain.gain.setValueAtTime(outputGain.gain.value, now);
      outputGain.gain.linearRampToValueAtTime(0, now + seconds);
      await new Promise((resolve) => globalThis.setTimeout(resolve, seconds * 1000));
      await context.close();
    },

    async resume(): Promise<void> {
      if (context.state !== "running") {
        await context.resume();
      }

      nextPlaybackTime = Math.max(nextPlaybackTime, context.currentTime);
    },

    async schedule(base64Pcm: string, sampleRate: number): Promise<PcmScheduledChunk> {
      const samples = pcm16ToFloat32(base64ToPcm16(base64Pcm));
      const buffer = context.createBuffer(1, samples.length, sampleRate);
      buffer.copyToChannel(samples, 0);

      const source = context.createBufferSource();
      source.buffer = buffer;
      source.connect(outputGain);

      const startTime = Math.max(nextPlaybackTime, context.currentTime);
      source.start(startTime);
      const endTime = startTime + buffer.duration;
      nextPlaybackTime = endTime;

      return { duration: buffer.duration, endTime, startTime };
    },

    async suspend(): Promise<void> {
      if (context.state === "running") {
        await context.suspend();
      }
    },
  };
}
