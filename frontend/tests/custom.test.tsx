import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/api/client';
import type { BaselineListResponse, CustomBaselineResult } from '@/api/types';

vi.mock('@/state/analysis', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/state/analysis')>();
  return { ...original, analyzeFile: vi.fn().mockResolvedValue(false) };
});
vi.mock('@/state/custom', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/state/custom')>();
  return { ...original, createCustomBaseline: vi.fn().mockResolvedValue(false), deleteCustomBaseline: vi.fn().mockResolvedValue(true) };
});

import { CustomPage, LIMITS, describePassage, passageProblem } from '@/features/custom/CustomPage';
import { analysisStore, analyzeFile } from '@/state/analysis';
import { catalogStore, connectionStore } from '@/state/connection';
import { createCustomBaseline, customStore, deleteCustomBaseline } from '@/state/custom';
import { stubFetch } from './helpers';

const SENTENCE = 'Today we study the signal and measure every single word with care. ';
const PASSAGE = SENTENCE.repeat(4).trim();                      // 48 words, 4 sentences
const wav = (name = 'a.wav') => new File([new Uint8Array(8)], name, { type: 'audio/wav' });

const mine: BaselineListResponse = {
  baselines: [
    { baseline_id: 'demo_talk', dataset_version: 'demo', n_baseline_recordings: 5, n_pauses_within_phrase: 40, n_rate_windows: 20, passage_id: 'demo_talk',
      passage_text: 'Project text.', passage_title: 'Project talk', passage_word_count: 123, sha256: 'a'.repeat(64), thin_pause_statistics: false, thin_rate_statistics: false, custom: false },
    { baseline_id: 'custom-0123456789ab', dataset_version: 'custom-1', n_baseline_recordings: 3, n_pauses_within_phrase: 20, n_rate_windows: 30, passage_id: 'custom-0123456789ab',
      passage_text: PASSAGE, passage_title: 'My talk', passage_word_count: 48, sha256: 'b'.repeat(64), thin_pause_statistics: false, thin_rate_statistics: false, custom: true },
  ],
  unavailable: [],
};

const made: CustomBaselineResult = {
  baseline_id: 'custom-0123456789ab', passage_id: 'custom-0123456789ab', title: 'My talk', passage_text: PASSAGE, passage_word_count: 48, n_recordings: 3,
  already_existed: false, word_profile_built: true, pitch_profile_built: false,
  takes: [
    { filename: 'one.wav', duration_s: 21.4, words_per_min: 150, timed_word_share: 1, content_match: 0.97 },
    { filename: 'two.wav', duration_s: 22.1, words_per_min: 145.2, timed_word_share: 0.95, content_match: null },
  ],
  warnings: ['“two.wav”: the recognised words match the passage only 70%; check that it reads the passage.'],
};

function reset(catalog: BaselineListResponse = { baselines: [], unavailable: [] }) {
  stubFetch({ '/api/v1/baselines': () => new Response(JSON.stringify(catalog), { headers: { 'Content-Type': 'application/json' } }) });
  catalogStore.set({ status: 'ready', data: catalog, error: null });
  connectionStore.set({ status: 'online', health: null, checkedAt: 0 });
  analysisStore.set({ status: 'idle', current: null, progress: null, error: null });
  customStore.set({ status: 'idle', progress: null, result: null, error: null });
  vi.mocked(analyzeFile).mockClear();
  vi.mocked(createCustomBaseline).mockClear();
  vi.mocked(deleteCustomBaseline).mockClear();
}

const chooseTakes = (files: File[]) => fireEvent.change(document.querySelector<HTMLInputElement>('input[type=file][multiple]')!, { target: { files } });
const typePassage = async (text = PASSAGE) => {
  const user = userEvent.setup();
  await user.clear(screen.getByLabelText('Passage text'));
  await user.click(screen.getByLabelText('Passage text'));
  await user.paste(text);
  return user;
};

describe('the hints under the passage box', () => {
  it('counts words and sentences', () => {
    expect(describePassage('')).toEqual({ words: 0, sentences: 0 });
    expect(describePassage('One two three. Four five? Six')).toEqual({ words: 6, sentences: 2 });
    expect(describePassage('He said "stop." Then he left.')).toEqual({ words: 6, sentences: 2 });
    expect(describePassage('Version 3.5 is out.')).toEqual({ words: 4, sentences: 1 });                  // a full stop inside a number is not a sentence end
  });
  it('says what is missing, in order', () => {
    expect(passageProblem('')).toMatch(/Type or paste/);
    expect(passageProblem('Short. Text.')).toBe(`${LIMITS.minWords - 2} more words needed (at least ${LIMITS.minWords}).`);
    expect(passageProblem('word '.repeat(LIMITS.maxWords + 1) + '.')).toMatch(/too many/);
    expect(passageProblem('word '.repeat(40) + '.')).toMatch(/at least two sentences/);
    expect(passageProblem(PASSAGE)).toBeNull();
  });
});

describe('CustomPage', () => {
  beforeEach(() => reset());
  afterEach(() => vi.unstubAllGlobals());

  it('guides the user: nothing can be made until the passage is long enough and two recordings are added', async () => {
    render(<CustomPage />);
    const make = screen.getByRole('button', { name: 'Make the baseline' });
    expect(make).toBeDisabled();
    expect(screen.getAllByText('Type or paste the passage you will read.', { exact: false })).toHaveLength(2);        // under the box and next to the button
    await typePassage();
    expect(screen.getByText(/48 words/)).toBeInTheDocument();
    expect(screen.getByText(/Good\. This is checked again by the server\./)).toBeInTheDocument();
    expect(make).toBeDisabled();                                                                // still no recordings
    chooseTakes([wav('one.wav')]);
    expect(await screen.findByText(/add at least 1 more/)).toBeInTheDocument();
    expect(make).toBeDisabled();
    chooseTakes([wav('two.wav')]);
    expect(await screen.findByText(/a third gives the word-by-word comparison/)).toBeInTheDocument();
    expect(make).toBeEnabled();
    chooseTakes([wav('three.wav')]);
    expect(await screen.findByText(/3 recordings: good\./)).toBeInTheDocument();
  });

  it('refuses files that are not WAV or MP3 and more than six recordings, and says so', async () => {
    render(<CustomPage />);
    chooseTakes([new File(['x'], 'notes.txt', { type: 'text/plain' })]);
    expect(await screen.findByRole('alert')).toHaveTextContent('“notes.txt” is not a WAV or MP3 file.');
    expect(screen.queryByRole('list', { name: 'Baseline recordings' })).toBeNull();
    chooseTakes(Array.from({ length: 8 }, (_, i) => wav(`t${i}.wav`)));
    expect(await screen.findByRole('alert')).toHaveTextContent('At most 6 recordings can be used; 2 files left out.');
    expect(within(screen.getByRole('list', { name: 'Baseline recordings' })).getAllByRole('listitem')).toHaveLength(6);
  });

  it('removes a recording from the list', async () => {
    const user = userEvent.setup();
    render(<CustomPage />);
    chooseTakes([wav('one.wav'), wav('two.wav')]);
    await user.click(await screen.findByRole('button', { name: 'Remove one.wav' }));
    const list = screen.getByRole('list', { name: 'Baseline recordings' });
    expect(within(list).getAllByRole('listitem')).toHaveLength(1);
    expect(within(list).getByText(/two\.wav/)).toBeInTheDocument();
  });

  it('sends the passage, the name and the recordings when the baseline is made', async () => {
    render(<CustomPage />);
    const user = await typePassage();
    await user.type(screen.getByLabelText(/Name/), '  My talk ');
    const one = wav('one.wav'), two = wav('two.wav');
    chooseTakes([one, two]);
    await user.click(await screen.findByRole('button', { name: 'Make the baseline' }));
    expect(createCustomBaseline).toHaveBeenCalledWith({ passageText: PASSAGE, title: '  My talk ', files: [one, two] });
  });

  it('shows the progress while the server works, and can cancel', async () => {
    render(<CustomPage />);
    act(() => customStore.set({ status: 'working', progress: { phase: 'building', loaded: 10, total: 10, startedAt: Date.now() }, result: null, error: null }));
    const status = screen.getByRole('status');
    expect(status).toHaveTextContent('Making the baseline on the server');
    expect(status).toHaveTextContent('roughly a minute per recording');
    expect(screen.queryByRole('button', { name: 'Make the baseline' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeInTheDocument();
  });

  it('shows the refusal of the server in plain words and lets the user dismiss it', async () => {
    const user = userEvent.setup();
    render(<CustomPage />);
    act(() => customStore.set({ status: 'error', progress: null, result: null, error: new ApiError('VALIDATION_ERROR', '“one.wav” does not seem to be a reading of this passage.', 422) }));
    expect(screen.getByRole('alert')).toHaveTextContent('The baseline could not be made');
    expect(screen.getByRole('alert')).toHaveTextContent('does not seem to be a reading of this passage');
    await user.click(screen.getByRole('button', { name: 'Dismiss' }));
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('reports the baseline that was made: what it can do, what was measured per recording, and the warnings', () => {
    render(<CustomPage />);
    act(() => customStore.set({ status: 'ready', progress: null, result: made, error: null }));
    const card = screen.getByRole('group', { name: 'The baseline that was made' });
    expect(within(card).getByText('Baseline ready')).toBeInTheDocument();
    expect(within(card).getByText('Word-by-word comparison')).toBeInTheDocument();
    expect(within(card).getByText('Flat pitch not checked')).toBeInTheDocument();
    const rows = within(card).getAllByRole('row');
    expect(rows).toHaveLength(3);
    expect(rows[1]).toHaveTextContent('one.wav21.4 s150 wpm100%97%');
    expect(rows[2]).toHaveTextContent('145 wpm95%—');
    expect(within(card).getByText(/match the passage only 70%/)).toBeInTheDocument();
    expect(card).toHaveTextContent('recordings are not kept');
  });

  it('says plainly when only the overall averages could be used', () => {
    render(<CustomPage />);
    act(() => customStore.set({ status: 'ready', progress: null, result: { ...made, word_profile_built: false, takes: [], warnings: [], already_existed: true }, error: null }));
    expect(screen.getByText('Overall averages only')).toBeInTheDocument();
    expect(screen.getByText('Already existed, nothing recomputed')).toBeInTheDocument();
  });

  it('keeps step 3 closed until a baseline exists', () => {
    render(<CustomPage />);
    expect(screen.getByText('Make a baseline first.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Analyse my reading' })).toBeNull();
  });
});

describe('CustomPage with a custom baseline', () => {
  beforeEach(() => reset(mine));
  afterEach(() => vi.unstubAllGlobals());

  it('lists only the custom baselines and compares the reading with the one in use', async () => {
    render(<CustomPage />);
    const panel = screen.getByRole('heading', { name: 'Custom baselines' }).closest('section')!;
    expect(within(panel).getByText('My talk')).toBeInTheDocument();
    expect(within(panel).queryByText('Project talk')).toBeNull();
    expect(within(panel).getByRole('button', { name: 'In use' })).toBeInTheDocument();
    expect(screen.getByText(/Compared with/)).toHaveTextContent('Compared with My talk');
  });

  it('analyses the reading against the custom baseline, using its id for the passage too', async () => {
    const user = userEvent.setup();
    render(<CustomPage />);
    expect(screen.getByRole('button', { name: 'Analyse my reading' })).toBeDisabled();
    fireEvent.change(document.querySelector<HTMLInputElement>('input[type=file]:not([multiple])')!, { target: { files: [wav('me.wav')] } });
    const run = await screen.findByRole('button', { name: 'Analyse my reading' });
    await waitFor(() => expect(run).toBeEnabled());
    await user.click(run);
    expect(analyzeFile).toHaveBeenCalledWith(expect.objectContaining({ name: 'me.wav' }), { baselineId: 'custom-0123456789ab', passageId: 'custom-0123456789ab' });
  });

  it('asks before deleting and then deletes', async () => {
    const user = userEvent.setup();
    render(<CustomPage />);
    await user.click(screen.getByRole('button', { name: 'Delete My talk' }));
    const dialog = screen.getByRole('dialog', { name: 'Delete this custom baseline?' });
    expect(dialog).toHaveTextContent('“My talk” and its passage text will be removed');
    await user.click(within(dialog).getByRole('button', { name: 'Keep it' }));
    expect(deleteCustomBaseline).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Delete My talk' }));
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Delete' }));
    expect(deleteCustomBaseline).toHaveBeenCalledWith('custom-0123456789ab');
  });
});
