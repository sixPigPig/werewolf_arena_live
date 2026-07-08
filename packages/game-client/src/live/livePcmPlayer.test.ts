import { describe, expect, it, vi } from "vitest";

import {
  base64ToPcm16,
  createPcmAudioScheduler,
  pcm16ToFloat32,
} from "./livePcmPlayer";

function encodePcm16ToBase64(samples: readonly number[]): string {
  const bytes = new Uint8Array(samples.length * 2);
  const view = new DataView(bytes.buffer);

  samples.forEach((sample, index) => {
    view.setInt16(index * 2, sample, true);
  });

  return btoa(String.fromCharCode(...bytes));
}

describe("livePcmPlayer", () => {
  it("decodes little-endian base64 PCM16 samples", () => {
    expect(Array.from(base64ToPcm16(encodePcm16ToBase64([0, 32767, -32768])))).toEqual([
      0,
      32767,
      -32768,
    ]);
  });

  it("converts PCM16 samples to Float32 samples", () => {
    expect(Array.from(pcm16ToFloat32(new Int16Array([0, 32767, -32768])))).toEqual([
      0,
      32767 / 32768,
      -1,
    ]);
  });

  it("schedules chunks continuously from the audio context time", async () => {
    const context = createFakeAudioContext({ currentTime: 10 });
    const scheduler = createPcmAudioScheduler(context);

    const firstChunk = await scheduler.schedule(encodePcm16ToBase64([0, 32767]), 2);
    const secondChunk = await scheduler.schedule(encodePcm16ToBase64([-32768, 0]), 2);

    expect([firstChunk, secondChunk]).toEqual([
      { duration: 1, endTime: 11, startTime: 10 },
      { duration: 1, endTime: 12, startTime: 11 },
    ]);
    expect(context.startedAt).toEqual([10, 11]);
    expect(context.buffers.map((buffer) => buffer.samples)).toEqual([
      [0, 32767 / 32768],
      [-1, 0],
    ]);
    expect(context.sources.map((source) => source.buffer)).toEqual(context.buffers);
  });
});

type FakeAudioBuffer = {
  copyToChannel: ReturnType<typeof vi.fn<(samples: Float32Array, channel: number) => void>>;
  duration: number;
  samples: number[];
};

type FakeAudioBufferSourceNode = {
  buffer: FakeAudioBuffer | null;
  connect: ReturnType<typeof vi.fn<(destination: unknown) => void>>;
  start: ReturnType<typeof vi.fn<(when: number) => void>>;
};

type FakeAudioContext = AudioContext & {
  buffers: FakeAudioBuffer[];
  sources: FakeAudioBufferSourceNode[];
  startedAt: number[];
};

function createFakeAudioContext(options: { currentTime: number }): FakeAudioContext {
  const buffers: FakeAudioBuffer[] = [];
  const sources: FakeAudioBufferSourceNode[] = [];
  const startedAt: number[] = [];
  const context = {
    buffers,
    close: vi.fn(async () => undefined),
    createBuffer: vi.fn(
      (_numberOfChannels: number, length: number, sampleRate: number): FakeAudioBuffer => {
        const buffer = {
          copyToChannel: vi.fn((samples: Float32Array, _channel: number) => {
            buffer.samples = Array.from(samples);
          }),
          duration: length / sampleRate,
          samples: [] as number[],
        };
        buffers.push(buffer);
        return buffer;
      },
    ),
    createBufferSource: vi.fn((): FakeAudioBufferSourceNode => {
      const source = {
        buffer: null,
        connect: vi.fn((_destination: unknown) => undefined),
        start: vi.fn((when: number) => {
          startedAt.push(when);
        }),
      };
      sources.push(source);
      return source;
    }),
    currentTime: options.currentTime,
    destination: {},
    resume: vi.fn(async () => undefined),
    sources,
    startedAt,
    state: "running",
    suspend: vi.fn(async () => undefined),
  };

  return context as unknown as FakeAudioContext;
}
