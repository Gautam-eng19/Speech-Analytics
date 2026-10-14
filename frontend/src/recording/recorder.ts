import { resampleAsync } from './resample';
import { encodeWav16 } from './wav';

/**
 * Recording from the microphone, as raw samples.
 *
 * What this does: asks for the microphone with the browser's voice processing switched OFF (echo cancellation, noise suppression and
 * automatic gain all change the signal the analysis is about), collects the samples as they arrive, converts them to 16 kHz mono and
 * writes a 16-bit WAV file that is handed to the upload form like any other file.
 *
 * What this does not do: it measures nothing about the delivery. The input level reported while recording is for setting the
 * microphone (a level bar and a clipping warning); the analysis, the findings and the score all come from the backend.
 */

/** The longest take. It matches the API's default limit (5 minutes); the server stays the authority and says so if its limit differs. */
export const MAX_RECORD_S = 300;
export const TARGET_RATE = 16000;

export type RecorderErrorCode = 'unsupported' | 'insecure' | 'denied' | 'no-device' | 'busy' | 'failed';

export class RecorderError extends Error {
  readonly code: RecorderErrorCode;
  constructor(code: RecorderErrorCode, message: string) {
    super(message);
    this.name = 'RecorderError';
    this.code = code;
  }
}

const MESSAGES: Record<Exclude<RecorderErrorCode, 'failed'>, string> = {
  unsupported: 'This browser cannot record audio. Upload a file instead.',
  insecure: 'Recording needs a secure page (https:// or localhost). Open the dashboard that way, or upload a file.',
  denied: 'Microphone access was blocked. Allow it for this site in the address bar, then try again.',
  'no-device': 'No microphone was found.',
  busy: 'The microphone is in use by another application or could not be opened.',
};

export function describeError(error: unknown): RecorderError {
  if (error instanceof RecorderError) return error;
  const name = (error as { name?: string } | null)?.name;
  if (name === 'NotAllowedError' || name === 'SecurityError') return new RecorderError('denied', MESSAGES.denied);
  if (name === 'NotFoundError' || name === 'OverconstrainedError') return new RecorderError('no-device', MESSAGES['no-device']);
  if (name === 'NotReadableError' || name === 'AbortError') return new RecorderError('busy', MESSAGES.busy);
  const detail = error instanceof Error && error.message ? ` (${error.message})` : '';
  return new RecorderError('failed', `Recording could not start${detail}.`);
}

export interface LevelReading {
  /** 0 to 1 */
  peak: number;
  /** 0 to 1 */
  rms: number;
  elapsedS: number;
}

export interface CaptureInfo {
  label: string;
  sampleRate: number;
  /** The browser's own answer about the processing it applied; `undefined` when it does not say. */
  echoCancellation?: boolean;
  noiseSuppression?: boolean;
  autoGainControl?: boolean;
}

export interface Take {
  file: File;
  durationS: number;
  sampleRate: number;
  /** Largest absolute sample of the take (0 to 1), to warn about clipping. */
  peak: number;
  capture: CaptureInfo;
}

export interface RecorderEnv {
  mediaDevices: Pick<MediaDevices, 'getUserMedia'> | undefined;
  AudioContextCtor: (new () => AudioContext) | undefined;
  AudioWorkletNodeCtor: (new (context: BaseAudioContext, name: string) => AudioWorkletNode) | undefined;
  secureContext: boolean;
  now: () => Date;
}

export function browserEnv(): RecorderEnv {
  const w = window as unknown as { webkitAudioContext?: new () => AudioContext };
  return {
    mediaDevices: navigator.mediaDevices,
    AudioContextCtor: window.AudioContext ?? w.webkitAudioContext,
    AudioWorkletNodeCtor: typeof AudioWorkletNode === 'undefined' ? undefined : AudioWorkletNode,
    secureContext: window.isSecureContext,
    now: () => new Date(),
  };
}

export interface RecorderEvents {
  onLevel?: (reading: LevelReading) => void;
  /** Called once when the longest allowed take has been reached; `stop()` should be called next. */
  onLimit?: () => void;
}

export interface Recorder {
  readonly state: 'idle' | 'recording' | 'finishing';
  start(options?: { deviceId?: string }): Promise<CaptureInfo>;
  stop(): Promise<Take>;
  /** Throws the take away and releases the microphone. */
  cancel(): void;
}

const WORKLET_NAME = 'sa-capture';
// Runs on the audio thread: copies each block (the engine reuses its buffer) and posts it in batches of 1024 samples.
const WORKLET_SOURCE = `
class CaptureProcessor extends AudioWorkletProcessor {
  constructor() { super(); this.buffer = new Float32Array(1024); this.filled = 0; }
  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (channel) {
      for (let i = 0; i < channel.length; i++) {
        this.buffer[this.filled++] = channel[i];
        if (this.filled === this.buffer.length) { this.port.postMessage(this.buffer.slice(0)); this.filled = 0; }
      }
    }
    return true;
  }
}
registerProcessor('${WORKLET_NAME}', CaptureProcessor);
`;

function stamp(date: Date): string {
  const p = (n: number) => String(n).padStart(2, '0');
  return `${date.getFullYear()}${p(date.getMonth() + 1)}${p(date.getDate())}-${p(date.getHours())}${p(date.getMinutes())}${p(date.getSeconds())}`;
}

export function createRecorder(env: RecorderEnv, events: RecorderEvents = {}, limitSeconds = MAX_RECORD_S): Recorder {
  let state: Recorder['state'] = 'idle';
  let stream: MediaStream | null = null;
  let context: AudioContext | null = null;
  let nodes: AudioNode[] = [];
  let chunks: Float32Array[] = [];
  let total = 0;
  let maxAbs = 0;
  let sampleRate = 48000;
  let capture: CaptureInfo | null = null;
  let limitReported = false;

  function release(): void {
    for (const node of nodes) {
      try {
        node.disconnect();
      } catch {
        /* already disconnected */
      }
    }
    nodes = [];
    stream?.getTracks().forEach((track) => track.stop());
    stream = null;
    if (context && context.state !== 'closed') void context.close().catch(() => undefined);
    context = null;
  }

  function push(block: Float32Array): void {
    if (state !== 'recording') return;
    let peak = 0;
    let sumSquares = 0;
    for (let i = 0; i < block.length; i++) {
      const v = Math.abs(block[i] as number);
      if (v > peak) peak = v;
      sumSquares += v * v;
    }
    chunks.push(block);
    total += block.length;
    if (peak > maxAbs) maxAbs = peak;
    const elapsedS = total / sampleRate;
    events.onLevel?.({ peak, rms: Math.sqrt(sumSquares / Math.max(1, block.length)), elapsedS });
    if (elapsedS >= limitSeconds && !limitReported) {
      limitReported = true;
      events.onLimit?.();
    }
  }

  return {
    get state() {
      return state;
    },

    async start(options = {}) {
      if (state !== 'idle') throw new RecorderError('failed', 'A recording is already in progress.');
      if (!env.mediaDevices?.getUserMedia || !env.AudioContextCtor) throw new RecorderError(env.secureContext ? 'unsupported' : 'insecure', MESSAGES[env.secureContext ? 'unsupported' : 'insecure']);
      let granted: MediaStream;
      try {
        granted = await env.mediaDevices.getUserMedia({
          audio: {
            ...(options.deviceId ? { deviceId: { exact: options.deviceId } } : {}),
            channelCount: 1,
            echoCancellation: false,
            noiseSuppression: false,
            autoGainControl: false,
          },
        });
      } catch (error) {
        throw describeError(error);
      }
      stream = granted;
      try {
        const ctx = new env.AudioContextCtor();
        context = ctx;
        if (ctx.state === 'suspended') await ctx.resume();
        sampleRate = ctx.sampleRate;
        const source = ctx.createMediaStreamSource(granted);
        const silence = ctx.createGain();
        silence.gain.value = 0; // the capture node must be part of a graph that reaches the output, but nothing may be played back
        silence.connect(ctx.destination);
        let tap: AudioNode;
        if (ctx.audioWorklet && env.AudioWorkletNodeCtor) {
          const url = URL.createObjectURL(new Blob([WORKLET_SOURCE], { type: 'text/javascript' }));
          try {
            await ctx.audioWorklet.addModule(url);
          } finally {
            URL.revokeObjectURL(url);
          }
          const node = new env.AudioWorkletNodeCtor(ctx, WORKLET_NAME);
          node.port.onmessage = (event: MessageEvent<Float32Array>) => push(event.data);
          tap = node;
        } else {
          const node = ctx.createScriptProcessor(4096, 1, 1);
          node.onaudioprocess = (event) => push(event.inputBuffer.getChannelData(0).slice());
          tap = node;
        }
        source.connect(tap);
        tap.connect(silence);
        nodes = [source, tap, silence];
        const track = granted.getAudioTracks()[0];
        const settings = (track?.getSettings?.() ?? {}) as MediaTrackSettings;
        capture = {
          label: track?.label || 'Microphone',
          sampleRate,
          echoCancellation: settings.echoCancellation,
          noiseSuppression: settings.noiseSuppression,
          autoGainControl: settings.autoGainControl,
        };
        chunks = [];
        total = 0;
        maxAbs = 0;
        limitReported = false;
        state = 'recording';
        return capture;
      } catch (error) {
        release();
        throw describeError(error);
      }
    },

    async stop() {
      if (state !== 'recording' || !capture) throw new RecorderError('failed', 'No recording is in progress.');
      state = 'finishing';
      const info = capture;
      const rate = sampleRate;
      const peak = maxAbs;
      const parts = chunks;
      const length = total;
      release();
      chunks = [];
      total = 0;
      try {
        if (length === 0) throw new RecorderError('failed', 'Nothing was recorded. Check the microphone and try again.');
        const samples = new Float32Array(length);
        let at = 0;
        for (const part of parts) {
          samples.set(part, at);
          at += part.length;
        }
        const converted = await resampleAsync(samples, rate, TARGET_RATE);
        const bytes = encodeWav16(converted, TARGET_RATE);
        const file = new File([bytes], `recording-${stamp(env.now())}.wav`, { type: 'audio/wav' });
        return { file, durationS: converted.length / TARGET_RATE, sampleRate: TARGET_RATE, peak, capture: info };
      } finally {
        state = 'idle';
      }
    },

    cancel() {
      if (state === 'recording') {
        release();
        chunks = [];
        total = 0;
        state = 'idle';
      }
    },
  };
}

/** Microphones the browser lists. Labels are only filled in once access has been granted. */
export async function listMicrophones(env: Pick<RecorderEnv, 'mediaDevices'> = browserEnv()): Promise<{ id: string; label: string }[]> {
  const devices = await (env.mediaDevices as MediaDevices | undefined)?.enumerateDevices?.();
  return (devices ?? []).filter((d) => d.kind === 'audioinput' && d.deviceId).map((d, i) => ({ id: d.deviceId, label: d.label || `Microphone ${i + 1}` }));
}
