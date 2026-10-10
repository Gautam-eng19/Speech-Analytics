import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createRecorder, describeError, listMicrophones, RecorderError, TARGET_RATE, type RecorderEnv } from '@/recording/recorder';

/** Stand-ins for the browser's audio graph that let a test decide what the "microphone" delivers. */
class FakeNode {
  connect = vi.fn();
  disconnect = vi.fn();
}
class FakeWorkletNode extends FakeNode {
  static last: FakeWorkletNode | null = null;
  port: { onmessage: ((event: { data: Float32Array }) => void) | null } = { onmessage: null };
  constructor(public context: unknown, public name: string) {
    super();
    FakeWorkletNode.last = this;
  }
  deliver(block: Float32Array) { this.port.onmessage?.({ data: block }); }
}
class FakeScriptNode extends FakeNode {
  onaudioprocess: ((event: { inputBuffer: { getChannelData: () => Float32Array } }) => void) | null = null;
  deliver(block: Float32Array) { this.onaudioprocess?.({ inputBuffer: { getChannelData: () => block } }); }
}
class FakeContext {
  static last: FakeContext | null = null;
  static withWorklet = true;
  state: string = 'running';
  sampleRate = 48000;
  destination = {};
  audioWorklet: { addModule: ReturnType<typeof vi.fn> } | undefined;
  script = new FakeScriptNode();
  createMediaStreamSource = vi.fn(() => new FakeNode());
  createGain = vi.fn(() => Object.assign(new FakeNode(), { gain: { value: 1 } }));
  createScriptProcessor = vi.fn(() => this.script);
  resume = vi.fn(async () => { this.state = 'running'; });
  close = vi.fn(async () => { this.state = 'closed'; });
  constructor() {
    FakeContext.last = this;
    this.audioWorklet = FakeContext.withWorklet ? { addModule: vi.fn(async () => undefined) } : undefined;
  }
}

const track = { stop: vi.fn(), label: 'Test microphone', getSettings: () => ({ echoCancellation: false, noiseSuppression: false, autoGainControl: false }) };
const fakeStream = () => ({ getTracks: () => [track], getAudioTracks: () => [track] }) as unknown as MediaStream;

function makeEnv(overrides: Partial<RecorderEnv> = {}): { env: RecorderEnv; getUserMedia: ReturnType<typeof vi.fn> } {
  const getUserMedia = vi.fn(async () => fakeStream());
  const env: RecorderEnv = {
    mediaDevices: { getUserMedia } as unknown as MediaDevices,
    AudioContextCtor: FakeContext as unknown as new () => AudioContext,
    AudioWorkletNodeCtor: FakeWorkletNode as unknown as RecorderEnv['AudioWorkletNodeCtor'],
    secureContext: true,
    now: () => new Date(2026, 9, 10, 14, 5, 9),
    ...overrides,
  };
  return { env, getUserMedia };
}

/** jsdom's Blob has no arrayBuffer(); FileReader does the same job. */
const readBytes = (file: Blob) =>
  new Promise<Uint8Array>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(new Uint8Array(reader.result as ArrayBuffer));
    reader.onerror = () => reject(reader.error);
    reader.readAsArrayBuffer(file);
  });

const sine = (hz: number, n: number, rate = 48000) => Float32Array.from({ length: n }, (_, i) => 0.4 * Math.sin((2 * Math.PI * hz * i) / rate));

beforeEach(() => {
  FakeContext.withWorklet = true;
  FakeContext.last = null;
  FakeWorkletNode.last = null;
  track.stop.mockClear();
});

describe('recording a take', () => {
  it('asks for the microphone with voice processing off and reports what the browser applied', async () => {
    const { env, getUserMedia } = makeEnv();
    const info = await createRecorder(env).start();
    expect(getUserMedia).toHaveBeenCalledWith({ audio: { channelCount: 1, echoCancellation: false, noiseSuppression: false, autoGainControl: false } });
    expect(info).toMatchObject({ label: 'Test microphone', sampleRate: 48000, echoCancellation: false, noiseSuppression: false, autoGainControl: false });
  });

  it('can be pointed at a particular microphone', async () => {
    const { env, getUserMedia } = makeEnv();
    await createRecorder(env).start({ deviceId: 'mic-2' });
    expect(getUserMedia.mock.calls[0]![0].audio.deviceId).toEqual({ exact: 'mic-2' });
  });

  it('keeps the capture node connected to the output through a silent gain, so nothing is played back', async () => {
    const { env } = makeEnv();
    await createRecorder(env).start();
    const gain = FakeContext.last!.createGain.mock.results[0]!.value as FakeNode & { gain: { value: number } };
    expect(gain.gain.value).toBe(0);
    expect(gain.connect).toHaveBeenCalledWith(FakeContext.last!.destination);
    expect(FakeContext.last!.audioWorklet!.addModule).toHaveBeenCalledTimes(1);
    expect(FakeWorkletNode.last!.name).toBe('sa-capture');
  });

  it('turns the samples into a 16 kHz mono WAV named after the time', async () => {
    const { env } = makeEnv();
    const levels: number[] = [];
    const recorder = createRecorder(env, { onLevel: (l) => levels.push(l.peak) });
    await recorder.start();
    const node = FakeWorkletNode.last!;
    const second = sine(1000, 48000);
    for (let i = 0; i < 48000; i += 1024) node.deliver(second.slice(i, i + 1024));
    expect(recorder.state).toBe('recording');
    const take = await recorder.stop();
    expect(recorder.state).toBe('idle');
    expect(take.file.name).toBe('recording-20261010-140509.wav');
    expect(take.file.type).toBe('audio/wav');
    expect(take.sampleRate).toBe(TARGET_RATE);
    expect(take.durationS).toBeCloseTo(1, 2);
    expect(take.peak).toBeCloseTo(0.4, 2);
    const bytes = await readBytes(take.file);
    const view = new DataView(bytes.buffer);
    expect(view.getUint32(24, true)).toBe(16000);
    expect(view.getUint16(22, true)).toBe(1);
    expect(bytes.length).toBe(44 + 2 * 16000); // one second at 16 kHz, 16 bits
    expect(levels.length).toBeGreaterThan(40);
    expect(Math.max(...levels)).toBeCloseTo(0.4, 2);
  });

  it('releases the microphone and the audio graph when it stops', async () => {
    const { env } = makeEnv();
    const recorder = createRecorder(env);
    await recorder.start();
    FakeWorkletNode.last!.deliver(sine(440, 1024));
    await recorder.stop();
    expect(track.stop).toHaveBeenCalled();
    expect(FakeContext.last!.close).toHaveBeenCalled();
    expect(FakeWorkletNode.last!.disconnect).toHaveBeenCalled();
  });

  it('throws a take away on cancel and releases everything', async () => {
    const { env } = makeEnv();
    const recorder = createRecorder(env);
    await recorder.start();
    FakeWorkletNode.last!.deliver(sine(440, 1024));
    recorder.cancel();
    expect(recorder.state).toBe('idle');
    expect(track.stop).toHaveBeenCalled();
    await expect(recorder.stop()).rejects.toMatchObject({ code: 'failed' });
  });

  it('ignores blocks that arrive after it has stopped', async () => {
    const { env } = makeEnv();
    const levels = vi.fn();
    const recorder = createRecorder(env, { onLevel: levels });
    await recorder.start();
    const node = FakeWorkletNode.last!;
    node.deliver(sine(440, 1024));
    await recorder.stop();
    levels.mockClear();
    node.deliver(sine(440, 1024));
    expect(levels).not.toHaveBeenCalled();
  });

  it('refuses a second start while recording', async () => {
    const { env } = makeEnv();
    const recorder = createRecorder(env);
    await recorder.start();
    await expect(recorder.start()).rejects.toBeInstanceOf(RecorderError);
  });

  it('says so when nothing was recorded', async () => {
    const { env } = makeEnv();
    const recorder = createRecorder(env);
    await recorder.start();
    await expect(recorder.stop()).rejects.toThrow('Nothing was recorded');
    expect(recorder.state).toBe('idle');
  });

  it('reports the longest take once, so the page can stop it', async () => {
    const { env } = makeEnv();
    const onLimit = vi.fn();
    const recorder = createRecorder(env, { onLimit }, 1);
    await recorder.start();
    const node = FakeWorkletNode.last!;
    for (let i = 0; i < 60; i++) node.deliver(new Float32Array(1024));
    expect(onLimit).toHaveBeenCalledTimes(1);
  });

  it('falls back to a script processor where audio worklets do not exist', async () => {
    FakeContext.withWorklet = false;
    const { env } = makeEnv({ AudioWorkletNodeCtor: undefined });
    const recorder = createRecorder(env);
    await recorder.start();
    FakeContext.last!.script.deliver(sine(500, 4096));
    FakeContext.last!.script.deliver(sine(500, 4096));
    const take = await recorder.stop();
    expect(take.durationS).toBeCloseTo(8192 / 48000, 2);
  });

  it('resumes a suspended audio context (browsers start them paused until a gesture)', async () => {
    const { env } = makeEnv();
    const Suspended = class extends FakeContext { constructor() { super(); this.state = 'suspended'; } };
    await createRecorder({ ...env, AudioContextCtor: Suspended as unknown as RecorderEnv['AudioContextCtor'] }).start();
    expect(FakeContext.last!.resume).toHaveBeenCalled();
  });
});

describe('when recording is not possible', () => {
  const rejectWith = (name: string) => makeEnv({ mediaDevices: { getUserMedia: vi.fn(async () => { throw new DOMException('x', name); }) } as unknown as MediaDevices }).env;

  it.each([
    ['NotAllowedError', 'denied', /blocked/],
    ['SecurityError', 'denied', /blocked/],
    ['NotFoundError', 'no-device', /No microphone/],
    ['OverconstrainedError', 'no-device', /No microphone/],
    ['NotReadableError', 'busy', /in use/],
  ])('maps %s to a plain message', async (name, code, message) => {
    const error = (await createRecorder(rejectWith(name)).start().catch((e: unknown) => e)) as RecorderError;
    expect(error).toBeInstanceOf(RecorderError);
    expect(error.code).toBe(code);
    expect(error.message).toMatch(message);
  });

  it('tells an insecure page from an unsupported browser', async () => {
    const insecure = (await createRecorder(makeEnv({ mediaDevices: undefined, secureContext: false }).env).start().catch((e: unknown) => e)) as RecorderError;
    expect(insecure.code).toBe('insecure');
    const unsupported = (await createRecorder(makeEnv({ mediaDevices: undefined, secureContext: true }).env).start().catch((e: unknown) => e)) as RecorderError;
    expect(unsupported.code).toBe('unsupported');
    const noAudio = (await createRecorder(makeEnv({ AudioContextCtor: undefined }).env).start().catch((e: unknown) => e)) as RecorderError;
    expect(noAudio.code).toBe('unsupported');
  });

  it('releases the microphone when the audio graph cannot be built', async () => {
    const { env } = makeEnv();
    const Broken = class extends FakeContext { constructor() { super(); this.audioWorklet = { addModule: vi.fn(async () => { throw new Error('module blocked'); }) }; } };
    const recorder = createRecorder({ ...env, AudioContextCtor: Broken as unknown as RecorderEnv['AudioContextCtor'] });
    const error = (await recorder.start().catch((e: unknown) => e)) as RecorderError;
    expect(error.code).toBe('failed');
    expect(error.message).toContain('module blocked');
    expect(track.stop).toHaveBeenCalled();
    expect(recorder.state).toBe('idle');
  });

  it('describes unknown errors without hiding them', () => {
    expect(describeError(new Error('boom')).message).toContain('boom');
    expect(describeError('weird').code).toBe('failed');
  });
});

describe('listMicrophones', () => {
  it('lists audio inputs and gives unnamed ones a number', async () => {
    const devices = [
      { kind: 'audioinput', deviceId: 'a', label: 'Studio mic' },
      { kind: 'videoinput', deviceId: 'v', label: 'Camera' },
      { kind: 'audioinput', deviceId: 'b', label: '' },
      { kind: 'audioinput', deviceId: '', label: 'ghost' },
    ];
    const list = await listMicrophones({ mediaDevices: { enumerateDevices: async () => devices } as unknown as MediaDevices });
    expect(list).toEqual([{ id: 'a', label: 'Studio mic' }, { id: 'b', label: 'Microphone 2' }]);
  });
  it('returns nothing where the browser cannot list devices', async () => {
    expect(await listMicrophones({ mediaDevices: undefined })).toEqual([]);
  });
});
