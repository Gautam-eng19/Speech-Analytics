import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/api/client';
import type { BaselineListResponse } from '@/api/types';

vi.mock('@/state/analysis', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/state/analysis')>();
  return { ...original, analyzeFile: vi.fn().mockResolvedValue(false) };
});

import { AnalyzePage } from '@/features/analyze/AnalyzePage';
import { analysisStore, analyzeFile } from '@/state/analysis';
import { catalogStore, connectionStore } from '@/state/connection';
import { stubFetch } from './helpers';

const catalog: BaselineListResponse = {
  baselines: [{
    baseline_id: 'demo_talk', dataset_version: 'demo', n_baseline_recordings: 5, n_pauses_within_phrase: 40, n_rate_windows: 20,
    passage_id: 'demo_talk', passage_text: 'Good morning, everyone.', passage_title: 'Project talk', passage_word_count: 123,
    sha256: 'a'.repeat(64), thin_pause_statistics: true, thin_rate_statistics: false,
  }],
  unavailable: [],
};
const wav = () => new File([new Uint8Array(8)], 'talk.wav', { type: 'audio/wav' });

describe('AnalyzePage', () => {
  beforeEach(() => {
    stubFetch({ '/api/v1/baselines': () => new Response(JSON.stringify(catalog), { headers: { 'Content-Type': 'application/json' } }) });
    catalogStore.set({ status: 'ready', data: catalog, error: null });
    connectionStore.set({ status: 'online', health: null, checkedAt: 0 });
    analysisStore.set({ status: 'idle', current: null, progress: null, error: null });
    vi.mocked(analyzeFile).mockClear();
  });
  afterEach(() => vi.unstubAllGlobals());

  it('offers the installed baselines and warns about thin statistics', () => {
    render(<AnalyzePage />);
    expect(screen.getByRole('combobox', { name: 'Compare with' })).toHaveValue('demo_talk');
    expect(screen.getByText('Thin statistics')).toBeInTheDocument();
    expect(screen.getByText(/rest on|few observations/)).toBeInTheDocument();
  });

  it('keeps Analyse disabled until there is a recording', () => {
    render(<AnalyzePage />);
    expect(screen.getByRole('button', { name: 'Analyse recording' })).toBeDisabled();
    expect(screen.getByText('Choose a recording to begin.')).toBeInTheDocument();
  });

  it('rejects a file that is not WAV or MP3 and says why', async () => {
    render(<AnalyzePage />);
    const input = document.querySelector<HTMLInputElement>('input[type=file]')!;
    fireEvent.change(input, { target: { files: [new File(['x'], 'notes.txt', { type: 'text/plain' })] } });
    expect(await screen.findByRole('alert')).toHaveTextContent('not a WAV or MP3 file');
    expect(screen.getByRole('button', { name: 'Analyse recording' })).toBeDisabled();
  });

  it('accepts a WAV, shows it, and sends it with the chosen baseline and passage', async () => {
    const user = userEvent.setup();
    render(<AnalyzePage />);
    await user.upload(document.querySelector<HTMLInputElement>('input[type=file]')!, wav());
    expect(await screen.findByText('talk.wav')).toBeInTheDocument();
    const run = screen.getByRole('button', { name: 'Analyse recording' });
    expect(run).toBeEnabled();
    await user.click(run);
    expect(analyzeFile).toHaveBeenCalledTimes(1);
    const [file, params] = vi.mocked(analyzeFile).mock.calls[0]!;
    expect(file.name).toBe('talk.wav');
    expect(params).toEqual({ baselineId: 'demo_talk', passageId: 'demo_talk', manualTranscript: undefined });
  });

  it('sends a manual transcript only when that option is open, and requires it to be filled', async () => {
    const user = userEvent.setup();
    render(<AnalyzePage />);
    await user.upload(document.querySelector<HTMLInputElement>('input[type=file]')!, wav());
    await user.click(screen.getByText('Advanced: supply the transcript yourself'));
    const run = screen.getByRole('button', { name: 'Analyse recording' });
    expect(run).toBeDisabled();
    await user.type(screen.getByLabelText('Transcript of the recording'), 'good morning everyone');
    expect(run).toBeEnabled();
    await user.click(run);
    expect(vi.mocked(analyzeFile).mock.calls[0]![1].manualTranscript).toBe('good morning everyone');
  });

  it('cannot run while the API is offline, and says so', async () => {
    connectionStore.set({ status: 'offline', health: null, checkedAt: 0 });
    const user = userEvent.setup();
    render(<AnalyzePage />);
    await user.upload(document.querySelector<HTMLInputElement>('input[type=file]')!, wav());
    expect(screen.getByRole('button', { name: 'Analyse recording' })).toBeDisabled();
    expect(screen.getByText('The API is offline.', { selector: '.runbar__hint' })).toBeInTheDocument();
  });

  it('explains an empty catalogue and still offers the demo samples', async () => {
    catalogStore.set({ status: 'ready', data: { baselines: [], unavailable: [{ baseline_id: 'broken', reason: 'integrity_check_failed' }] }, error: null });
    render(<AnalyzePage />);
    expect(screen.getByText('No baseline is installed on this server yet.')).toBeInTheDocument();
    expect(screen.getByText(/broken \(integrity check failed\)/)).toBeInTheDocument();
    expect(await screen.findByText('Clean delivery')).toBeInTheDocument();
  });

  it('shows the four demo samples with their injected flaws, and opens one', async () => {
    render(<AnalyzePage />);
    const mixed = await screen.findByText('Mixed flaws');
    expect(screen.getByText('Control take')).toBeInTheDocument();
    fireEvent.click(mixed.closest('button')!);
    expect(window.location.hash).toMatch(/^#\/a\/[0-9a-f-]{36}\/overview$/);
  });

  it('shows upload progress, then the server phase, then an API error with its detail', async () => {
    const { rerender } = render(<AnalyzePage />);
    act(() => analysisStore.set({ status: 'loading', current: null, error: null, progress: { phase: 'uploading', loaded: 1024, total: 4096, startedAt: Date.now() } }));
    expect(screen.getByRole('status')).toHaveTextContent('Uploading the recording');
    expect(screen.getByRole('status')).toHaveTextContent('1 KB of 4 KB sent.');
    act(() => analysisStore.set({ status: 'loading', current: null, error: null, progress: { phase: 'analysing', loaded: 4096, total: 4096, startedAt: Date.now() } }));
    expect(screen.getByRole('status')).toHaveTextContent('Analysing on the server');
    act(() => analysisStore.set({ status: 'error', current: null, progress: null, error: new ApiError('AUDIO_TOO_LONG', 'audio of 400.0 s exceeds limit of 300.0 s', 400) }));
    rerender(<AnalyzePage />);
    expect(screen.getByRole('alert')).toHaveTextContent('The recording is too long');
    expect(screen.getByRole('alert')).toHaveTextContent('300.0 s');
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }));
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull());
  });
});
