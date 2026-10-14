import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { BaselineListResponse } from '@/api/types';

vi.mock('@/state/analysis', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/state/analysis')>();
  return { ...original, analyzeFile: vi.fn().mockResolvedValue(false) };
});
vi.mock('@/recording/recorder', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/recording/recorder')>();
  return { ...original, createRecorder: vi.fn() };
});

import { AnalyzePage } from '@/features/analyze/AnalyzePage';
import { RecorderPanel } from '@/features/analyze/RecorderPanel';
import { createRecorder, RecorderError, type CaptureInfo, type Recorder, type RecorderEvents, type Take } from '@/recording/recorder';
import { analysisStore, analyzeFile } from '@/state/analysis';
import { catalogStore, connectionStore } from '@/state/connection';
import { toastStore } from '@/state/ui';
import { stubFetch } from './helpers';

const wavFile = (name = 'recording-20261010-140509.wav', bytes = 32044) => new File([new Uint8Array(bytes)], name, { type: 'audio/wav' });
const capture: CaptureInfo = { label: 'Test microphone', sampleRate: 48000, echoCancellation: false, noiseSuppression: false, autoGainControl: false };
const takeOf = (over: Partial<Take> = {}): Take => ({ file: wavFile(), durationS: 12.3, sampleRate: 16000, peak: 0.4, capture, ...over });

/** A recorder the test drives by hand. */
function fakeRecorder(options: { take?: Take; startError?: unknown; captureInfo?: CaptureInfo } = {}) {
  let events: RecorderEvents = {};
  const recorder: Recorder & { start: ReturnType<typeof vi.fn>; stop: ReturnType<typeof vi.fn>; cancel: ReturnType<typeof vi.fn> } = {
    state: 'idle',
    start: vi.fn(async () => {
      if (options.startError) throw options.startError;
      return options.captureInfo ?? capture;
    }),
    stop: vi.fn(async () => options.take ?? takeOf()),
    cancel: vi.fn(),
  };
  const make = vi.fn((e: RecorderEvents) => { events = e; return recorder; });
  return { make, recorder, level: (peak: number, elapsedS = 1) => events.onLevel?.({ peak, rms: peak / 2, elapsedS }), limit: () => events.onLimit?.() };
}

const passage = { title: 'Project talk', text: 'Good morning, everyone.' };

describe('RecorderPanel', () => {
  beforeEach(() => { toastStore.set([]); });

  it('shows the passage to read, or says why there is none', () => {
    const { rerender } = render(<RecorderPanel passage={passage} onUse={() => undefined} makeRecorder={fakeRecorder().make} />);
    expect(screen.getByRole('region', { name: 'Passage to read' })).toHaveTextContent('Good morning, everyone.');
    rerender(<RecorderPanel passage={null} onUse={() => undefined} makeRecorder={fakeRecorder().make} />);
    expect(screen.getByText(/Choose a baseline in step 2/)).toBeInTheDocument();
  });

  it('records, stops and offers the take with its facts', async () => {
    const fake = fakeRecorder();
    const onUse = vi.fn();
    render(<RecorderPanel passage={passage} onUse={onUse} makeRecorder={fake.make} />);
    fireEvent.click(screen.getByRole('button', { name: 'Start recording' }));
    expect(await screen.findByText('Recording', { selector: '.rec__live' })).toBeInTheDocument();
    expect(fake.recorder.start).toHaveBeenCalledWith({ deviceId: undefined });
    fireEvent.click(screen.getByRole('button', { name: 'Stop' }));
    const name = await screen.findByText('recording-20261010-140509.wav');
    expect(name).toBeInTheDocument();
    expect(screen.getByText(/0:12\.3 · 31 KB · 16 kHz mono WAV/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Use this recording' }));
    expect(onUse).toHaveBeenCalledTimes(1);
    expect(onUse.mock.calls[0]![0].name).toBe('recording-20261010-140509.wav');
  });

  it('shows the input level while recording, on a decibel scale, and flags clipping', async () => {
    const fake = fakeRecorder();
    render(<RecorderPanel passage={passage} onUse={() => undefined} makeRecorder={fake.make} />);
    fireEvent.click(screen.getByRole('button', { name: 'Start recording' }));
    await screen.findByRole('button', { name: 'Stop' });
    act(() => fake.level(0.1, 2.5));
    await waitFor(() => expect(screen.getByRole('meter', { name: 'Input level' })).toHaveAttribute('aria-valuenow', '-20'));
    await waitFor(() => expect(document.querySelector('.rec__time')!.textContent).toBe('0:02.5'));
    expect(document.querySelector('.rec__meter i')!.className).not.toContain('is-clip');
    act(() => fake.level(1, 3));
    await waitFor(() => expect(document.querySelector('.rec__meter i')!.className).toContain('is-clip'));
  });

  it('explains a blocked microphone and lets the user try again', async () => {
    const fake = fakeRecorder({ startError: new RecorderError('denied', 'Microphone access was blocked. Allow it for this site in the address bar, then try again.') });
    render(<RecorderPanel passage={passage} onUse={() => undefined} makeRecorder={fake.make} />);
    fireEvent.click(screen.getByRole('button', { name: 'Start recording' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Microphone access was blocked');
    expect(screen.getByRole('button', { name: 'Start recording' })).toBeEnabled();
  });

  it('warns when the take clipped', async () => {
    const fake = fakeRecorder({ take: takeOf({ peak: 1 }) });
    render(<RecorderPanel passage={passage} onUse={() => undefined} makeRecorder={fake.make} />);
    fireEvent.click(screen.getByRole('button', { name: 'Start recording' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Stop' }));
    expect(await screen.findByText('Clipped')).toBeInTheDocument();
  });

  it('says so when the browser kept its voice processing on', async () => {
    const fake = fakeRecorder({ captureInfo: { ...capture, echoCancellation: true } });
    render(<RecorderPanel passage={passage} onUse={() => undefined} makeRecorder={fake.make} />);
    fireEvent.click(screen.getByRole('button', { name: 'Start recording' }));
    expect(await screen.findByText('Voice processing is on')).toBeInTheDocument();
  });

  it('stops by itself at the longest take and says why', async () => {
    const fake = fakeRecorder();
    render(<RecorderPanel passage={passage} onUse={() => undefined} makeRecorder={fake.make} />);
    fireEvent.click(screen.getByRole('button', { name: 'Start recording' }));
    await screen.findByRole('button', { name: 'Stop' });
    act(() => fake.limit());
    await screen.findByText('recording-20261010-140509.wav');
    expect(fake.recorder.stop).toHaveBeenCalledTimes(1);
    expect(toastStore.get().some((t) => /Stopped at 5 minutes/.test(t.message))).toBe(true);
  });

  it('discards a take, and releases the microphone when the page is left mid-recording', async () => {
    const fake = fakeRecorder();
    const { unmount } = render(<RecorderPanel passage={passage} onUse={() => undefined} makeRecorder={fake.make} />);
    fireEvent.click(screen.getByRole('button', { name: 'Start recording' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Stop' }));
    await screen.findByText('recording-20261010-140509.wav');
    fireEvent.click(screen.getByRole('button', { name: 'Discard' }));
    expect(screen.queryByText('recording-20261010-140509.wav')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Start recording' }));
    await screen.findByRole('button', { name: 'Stop' });
    unmount();
    expect(fake.recorder.cancel).toHaveBeenCalled();
  });

  it('cannot start while disabled', () => {
    render(<RecorderPanel passage={passage} onUse={() => undefined} makeRecorder={fakeRecorder().make} disabled />);
    expect(screen.getByRole('button', { name: 'Start recording' })).toBeDisabled();
  });
});

describe('recording on the New analysis page', () => {
  const catalog: BaselineListResponse = {
    baselines: [{
      baseline_id: 'demo_talk', dataset_version: 'demo', n_baseline_recordings: 5, n_pauses_within_phrase: 40, n_rate_windows: 20,
      passage_id: 'demo_talk', passage_text: 'Good morning, everyone.', passage_title: 'Project talk', passage_word_count: 4,
      sha256: 'a'.repeat(64), thin_pause_statistics: false, thin_rate_statistics: false, custom: false,
    }],
    unavailable: [],
  };
  beforeEach(() => {
    stubFetch();
    catalogStore.set({ status: 'ready', data: catalog, error: null });
    connectionStore.set({ status: 'online', health: null, checkedAt: 0 });
    analysisStore.set({ status: 'idle', current: null, progress: null, error: null });
    vi.mocked(analyzeFile).mockClear();
  });

  it('shows the chosen baseline’s passage as the prompt and sends the recording like an uploaded file', async () => {
    const fake = fakeRecorder();
    vi.mocked(createRecorder).mockImplementation(((events: RecorderEvents) => fake.make(events)) as unknown as typeof createRecorder);
    const user = userEvent.setup();
    render(<AnalyzePage />);
    await user.click(screen.getByRole('radio', { name: 'Record now' }));
    expect(screen.getByRole('region', { name: 'Passage to read' })).toHaveTextContent('Good morning, everyone.');
    await user.click(screen.getByRole('button', { name: 'Start recording' }));
    await user.click(await screen.findByRole('button', { name: 'Stop' }));
    await user.click(await screen.findByRole('button', { name: 'Use this recording' }));
    expect(await screen.findByText('recording-20261010-140509.wav')).toBeInTheDocument();
    const run = screen.getByRole('button', { name: 'Analyse recording' });
    expect(run).toBeEnabled();
    await user.click(run);
    const [file, params] = vi.mocked(analyzeFile).mock.calls[0]!;
    expect(file.name).toBe('recording-20261010-140509.wav');
    expect(params).toMatchObject({ baselineId: 'demo_talk', passageId: 'demo_talk' });
  });

  it('can go back to uploading a file', async () => {
    const user = userEvent.setup();
    render(<AnalyzePage />);
    await user.click(screen.getByRole('radio', { name: 'Record now' }));
    await user.click(screen.getByRole('radio', { name: 'Upload a file' }));
    expect(screen.getByText('Drop a WAV or MP3 here')).toBeInTheDocument();
  });
});
