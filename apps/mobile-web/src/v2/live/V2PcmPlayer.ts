import type { V2AudioFrame, V2Presentation } from "../contracts";

export class V2PcmPlayer {
  private readonly context: AudioContext;
  private presentation: V2Presentation | null = null;
  private expectedChunk: number | null = null;
  private expectedSample = 0;
  private nextStartTime: number | null = null;
  private readonly sources = new Set<AudioBufferSourceNode>();

  constructor() {
    this.context = new AudioContext();
  }

  async unlock(): Promise<void> {
    await this.context.resume();
  }

  begin(presentation: V2Presentation): void {
    if (this.presentation?.presentation_id === presentation.presentation_id) return;
    this.stop();
    this.presentation = presentation;
    this.expectedSample = presentation.join_sample_cursor;
  }

  push(frame: V2AudioFrame): void {
    const presentation = this.presentation;
    if (!presentation) throw new Error("收到没有展示归属的 V2 音频");
    const header = frame.header;
    if (
      header.action_id !== presentation.action_id ||
      header.presentation_seq !== presentation.presentation_seq ||
      header.presentation_id !== presentation.presentation_id ||
      header.speech_id !== presentation.speech_id ||
      header.segment_index !== presentation.segment_index
    ) {
      throw new Error("V2 音频归属与当前展示不一致");
    }
    if (this.expectedChunk !== null) {
      if (header.chunk_index === this.expectedChunk - 1) return;
      if (header.chunk_index !== this.expectedChunk) {
        throw new Error("V2 音频块越序");
      }
    }
    if (header.start_sample !== this.expectedSample) {
      throw new Error("V2 音频 sample 不连续");
    }
    this.expectedChunk = header.chunk_index + 1;
    this.expectedSample += header.sample_count;

    const pcm = new DataView(frame.pcm);
    const samples = new Float32Array(header.sample_count);
    for (let index = 0; index < header.sample_count; index += 1) {
      samples[index] = pcm.getInt16(index * 2, true) / 32768;
    }
    const buffer = this.context.createBuffer(1, samples.length, header.sample_rate);
    buffer.copyToChannel(samples, 0);
    const source = this.context.createBufferSource();
    source.buffer = buffer;
    source.connect(this.context.destination);
    source.addEventListener("ended", () => this.sources.delete(source), { once: true });
    const startAt = Math.max(
      this.context.currentTime + 0.04,
      this.nextStartTime ?? this.context.currentTime + 0.04,
    );
    source.start(startAt);
    this.nextStartTime = startAt + samples.length / header.sample_rate;
    this.sources.add(source);
  }

  stop(): void {
    for (const source of this.sources) {
      try {
        source.stop();
      } catch {
        // The source may already have ended.
      }
    }
    this.sources.clear();
    this.presentation = null;
    this.expectedChunk = null;
    this.expectedSample = 0;
    this.nextStartTime = null;
  }

  async close(): Promise<void> {
    this.stop();
    await this.context.close();
  }
}
