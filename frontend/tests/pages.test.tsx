import { act, fireEvent, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { BaselinePage } from '@/features/baseline/BaselinePage';
import { HelpPage } from '@/features/help/HelpPage';
import { LibraryPage } from '@/features/library/LibraryPage';
import { ReportPage } from '@/features/report/ReportPage';
import { SettingsPage } from '@/features/settings/SettingsPage';
import { SignalsPage } from '@/features/signals/SignalsPage';
import { TimelinePage } from '@/features/timeline/TimelinePage';
import { TranscriptPage } from '@/features/transcript/TranscriptPage';
import { DEFAULT_SETTINGS, settingsStore } from '@/lib/settings';
import { clearHistory, recordHistory } from '@/state/history';
import { hoverStore, selectionStore, setView, viewStore } from '@/state/ui';
import { catalogStore, connectionStore } from '@/state/connection';
import { flawOfType, hesitantResult, loaded, mixedResult, tinyResult } from './fixtures';
import { renderAsync, stubFetch, stubLayout, stubWideScreen } from './helpers';

const mixed = loaded(mixedResult);

beforeEach(() => {
  stubLayout(900);
  stubFetch();
  stubWideScreen(true);
  settingsStore.set({ ...DEFAULT_SETTINGS });
  selectionStore.set({ flawId: null });
  hoverStore.set(null);
  setView({ t0: 0, t1: mixedResult.audio.source_duration_s! });
  clearHistory();
  catalogStore.set({ status: 'idle', data: null, error: null });
  connectionStore.set({ status: 'online', health: { status: 'ok', api_contract_version: '1.2.0', config_version: '1.0.0', pipeline_version: '1.0.0' }, checkedAt: 0 });
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe('TimelinePage', () => {
  it('draws the lanes, starts fully zoomed out, and offers zoom controls', async () => {
    await renderAsync(<TimelinePage analysis={mixed} />);
    expect(document.querySelector('.scope__window')!.textContent).toContain('×1.0');
    for (const lane of ['flaws', 'truth', 'words', 'loudness', 'pitch', 'rate', 'pauses']) expect(document.querySelector(`.lane--${lane}`), lane).not.toBeNull();
    expect(screen.getByRole('button', { name: 'Zoom out' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Zoom in' }));
    expect(viewStore.get().t1 - viewStore.get().t0).toBeLessThan(mixedResult.audio.source_duration_s!);
    expect(screen.getByRole('button', { name: 'Zoom out' })).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: 'Fit the whole recording' }));
    expect(viewStore.get()).toEqual({ t0: 0, t1: mixedResult.audio.source_duration_s });
  });

  it('zooms with + and - and fits with 0', async () => {
    await renderAsync(<TimelinePage analysis={mixed} />);
    fireEvent.keyDown(window, { key: '+' });
    const zoomed = viewStore.get().t1 - viewStore.get().t0;
    expect(zoomed).toBeLessThan(mixedResult.audio.source_duration_s!);
    fireEvent.keyDown(window, { key: '-' });
    expect(viewStore.get().t1 - viewStore.get().t0).toBeGreaterThan(zoomed);
    fireEvent.keyDown(window, { key: '0' });
    expect(viewStore.get()).toEqual({ t0: 0, t1: mixedResult.audio.source_duration_s });
  });

  it('hides and shows lanes from the toolbar and remembers the choice', async () => {
    await renderAsync(<TimelinePage analysis={mixed} />);
    const pitch = screen.getByRole('button', { name: 'Pitch' });
    fireEvent.click(pitch);
    expect(document.querySelector('.lane--pitch')).toBeNull();
    expect(settingsStore.get().lanes.pitch).toBe(false);
    fireEvent.click(pitch);
    expect(document.querySelector('.lane--pitch')).not.toBeNull();
  });

  it('shows the ground-truth lane only for samples, and only when switched on', async () => {
    const { unmount } = await renderAsync(<TimelinePage analysis={mixed} />);
    fireEvent.click(screen.getByRole('button', { name: /Ground truth/ }));
    expect(document.querySelector('.lane--truth')).toBeNull();
    unmount();
    await renderAsync(<TimelinePage analysis={loaded(mixedResult, { sample: null, source: 'upload' })} />);
    expect(screen.queryByRole('button', { name: /Ground truth/ })).toBeNull();
  });

  it('fills the inspector with the finding’s evidence when its band is chosen', async () => {
    await renderAsync(<TimelinePage analysis={mixed} />);
    expect(screen.getByText(/Click a coloured band/)).toBeInTheDocument();
    const rate = flawOfType(mixedResult, 'too_fast');
    fireEvent.click(document.querySelector(`[data-flaw="${rate.flaw_id}"]`)!);
    const panel = screen.getByRole('region', { name: 'Selected finding' });
    expect(within(panel).getByText((rate.evidence as { rate_participant_wpm: number }).rate_participant_wpm.toFixed(1))).toBeInTheDocument();
    expect(panel.textContent).toContain(rate.explanation);
    expect(selectionStore.get().flawId).toBe(rate.flaw_id);
  });

  it('reads the values under the pointer from the result', async () => {
    await renderAsync(<TimelinePage analysis={mixed} />);
    const rate = flawOfType(mixedResult, 'too_fast');
    act(() => hoverStore.set((rate.start_s + rate.end_s) / 2));                       // inside the finding, wherever the analysis put it
    const panel = screen.getByRole('region', { name: 'Values at the cursor' });
    expect(within(panel).getByText('At the pointer')).toBeInTheDocument();
    expect(panel.textContent).toContain('Too fast');
    expect(panel.textContent).toContain('dBFS');
  });
});

describe('SignalsPage', () => {
  it('shows the four signals, the pause table and the MFCC summary from the backend', async () => {
    await renderAsync(<SignalsPage analysis={mixed} />);
    for (const title of ['Speech rate', 'Loudness', 'Pitch (F0)', 'Pauses']) expect(screen.getAllByText(title).length).toBeGreaterThan(0);
    const pauseRows = screen.getByRole('heading', { name: `${mixedResult.features.pause_events.length} pauses` }).closest('.panel')!.querySelectorAll('tbody tr');
    expect(pauseRows).toHaveLength(mixedResult.features.pause_events.length);
    const mfcc = screen.getByRole('heading', { name: 'MFCC summary' }).closest('.panel')!;
    expect(mfcc.querySelectorAll('tbody tr')).toHaveLength(13);
  });

  it('links a flagged pause to its finding and can sort by length', async () => {
    await renderAsync(<SignalsPage analysis={mixed} />);
    const link = screen.getByRole('button', { name: flawOfType(mixedResult, 'excessive_pause').flaw_id });
    expect(link).toBeInTheDocument();
    fireEvent.click(screen.getByRole('radio', { name: 'By length' }));
    const first = document.querySelector('tbody tr .num.r')!;
    const lengths = [...document.querySelectorAll('.panel tbody tr')].slice(0, 2).map((row) => parseFloat(row.querySelectorAll('td')[3]!.textContent!));
    expect(lengths[0]).toBeGreaterThanOrEqual(lengths[1]!);
    expect(first).toBeTruthy();
  });

  it('keeps the pitch note and says so when the MFCC summary is missing', async () => {
    const result = tinyResult({ notes: [{ code: 'mfcc_unavailable', message: 'MFCCs could not be computed here.' }, { code: 'pitch_not_scored', message: 'Pitch is context only.' }] });
    await renderAsync(<SignalsPage analysis={loaded(result)} />);
    expect(screen.getByText('MFCCs could not be computed here.')).toBeInTheDocument();
    expect(screen.getByText('Pitch is context only.')).toBeInTheDocument();
  });
});

describe('TranscriptPage', () => {
  it('shows every aligned word and underlines the ones inside findings', async () => {
    await renderAsync(<TranscriptPage analysis={mixed} />);
    const words = document.querySelectorAll('.tword');
    expect(words).toHaveLength(mixedResult.alignment.length);
    expect(document.querySelectorAll('.tword.has-flaw').length).toBeGreaterThan(0);
    expect(document.querySelectorAll('.tword.has-flaw').length).toBeLessThan(words.length);
  });

  it('draws the pauses between words as spaces, sized by the backend durations', async () => {
    await renderAsync(<TranscriptPage analysis={mixed} />);
    const gaps = [...document.querySelectorAll<HTMLElement>('.tgap')];
    expect(gaps.length).toBeGreaterThan(0);
    const longest = Math.max(...mixedResult.features.pause_events.map((p) => p.duration_s));
    const widest = Math.max(...gaps.map((g) => parseFloat(g.style.width)));
    expect(widest).toBeCloseTo(longest * 22, 0);
  });

  it('highlights the words of a selected finding and lists findings to jump to', async () => {
    selectionStore.set({ flawId: flawOfType(mixedResult, 'too_fast').flaw_id });
    await renderAsync(<TranscriptPage analysis={mixed} />);
    expect(document.querySelectorAll('.tword.is-selected').length).toBeGreaterThan(0);
    expect(screen.getAllByRole('button', { name: /Too (fast|slow)|Excessive pause/ }).length).toBeGreaterThan(0);
  });

  it('quotes the recognised text exactly as returned', async () => {
    await renderAsync(<TranscriptPage analysis={mixed} />);
    expect(document.querySelector('.transcript__recognised')!.textContent).toContain(mixedResult.transcript);
  });
});

describe('BaselinePage', () => {
  it('shows the baseline statistics with their units and what each is used for', async () => {
    await renderAsync(<BaselinePage analysis={mixed} />);
    const table = screen.getByRole('heading', { name: 'Baseline statistics' }).closest('.panel')!;
    expect(table.textContent).toContain('141.2 ± 11.6');
    expect(table.textContent).toContain('words/min');
    expect(table.textContent).toContain('Too fast, too slow');
    expect(table.textContent).toContain('not available');
  });
  it('lists all eight finding types and says which are not detected yet', async () => {
    await renderAsync(<BaselinePage analysis={mixed} />);
    const vocabulary = screen.getByRole('heading', { name: 'Finding types' }).closest('.panel')!;
    expect(vocabulary.querySelectorAll('tbody tr')).toHaveLength(8);
    expect(within(vocabulary as HTMLElement).getAllByText('Not yet')).toHaveLength(2);          // pitch instability and reduced clarity; flat pitch is detected
  });
  it('shows the passage for a sample and the baseline identity', async () => {
    await renderAsync(<BaselinePage analysis={mixed} />);
    expect(await screen.findByText('Project talk (demo passage)')).toBeInTheDocument();
    const identity = screen.getByRole('heading', { name: 'This baseline' }).closest('.panel')!;
    const fact = (label: string) => [...identity.querySelectorAll('.fact')].find((row) => row.querySelector('dt')!.textContent === label)!.querySelector('dd')!.textContent;
    expect(fact('Baseline id')).toBe(mixedResult.baseline.baseline_id);
    expect(fact('Dataset')).toBe(mixedResult.baseline.dataset_version);
    expect(fact('Recordings')).toBe('5');
  });
});

describe('ReportPage', () => {
  it('contains every finding with its evidence, explanation and recommendation', async () => {
    await renderAsync(<ReportPage analysis={mixed} />);
    const report = document.querySelector('.report')!;
    for (const f of mixedResult.flaws) {
      expect(report.textContent).toContain(f.explanation);
      expect(report.textContent).toContain(f.recommendation);
    }
    expect(report.textContent).toContain(mixedResult.analysis_id);
    expect(report.textContent).toContain(mixedResult.audio.sha256);
    expect(report.textContent).toContain(mixedResult.baseline.sha256);
  });
  it('prints through the browser and labels a sample as synthetic', async () => {
    const print = vi.spyOn(window, 'print').mockImplementation(() => undefined);
    await renderAsync(<ReportPage analysis={mixed} />);
    fireEvent.click(screen.getByRole('button', { name: /Print or save as PDF/ }));
    expect(print).toHaveBeenCalledTimes(1);
    expect(document.querySelector('.report__sample')!.textContent).toContain('synthetic');
  });
});

describe('LibraryPage', () => {
  it('lists the samples and an empty state for the user’s own analyses', async () => {
    await renderAsync(<LibraryPage />);
    expect(await screen.findByText('Clean delivery')).toBeInTheDocument();
    expect(screen.getByText('Nothing here yet')).toBeInTheDocument();
  });
  it('lists opened analyses, filters them, and removes one', async () => {
    recordHistory(mixedResult, 'Alpha take', 'upload');
    recordHistory(hesitantResult, 'Beta take', 'upload');
    await renderAsync(<LibraryPage />);
    const table = document.querySelector('table.table')!;
    expect(table.querySelectorAll('tbody tr')).toHaveLength(2);
    await userEvent.type(screen.getByLabelText('Filter the library'), 'alpha');
    expect(table.querySelectorAll('tbody tr')).toHaveLength(1);
    expect(table.textContent).toContain('Alpha take');
    await userEvent.clear(screen.getByLabelText('Filter the library'));
    fireEvent.click(screen.getByRole('button', { name: 'Remove Alpha take from this list' }));
    expect(document.querySelector('table.table')!.textContent).not.toContain('Alpha take');
  });
  it('confirms before clearing the list', async () => {
    recordHistory(mixedResult, 'Alpha take', 'upload');
    await renderAsync(<LibraryPage />);
    fireEvent.click(screen.getByRole('button', { name: /Clear list/ }));
    const dialog = await screen.findByRole('dialog', { name: 'Clear the list?' });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Keep them' }));
    expect(document.querySelector('table.table')).not.toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /Clear list/ }));
    fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Clear the list' }));
    expect(screen.getByText('Nothing here yet')).toBeInTheDocument();
  });
  it('opens a stored analysis by id and refuses ids that are not a single path segment', async () => {
    await renderAsync(<LibraryPage />);
    const box = screen.getByLabelText('Analysis id');
    await userEvent.type(box, 'bad/id');
    fireEvent.submit(box.closest('form')!);
    expect(window.location.hash).not.toContain('bad');
    await userEvent.clear(box);
    await userEvent.type(box, 'abc-123');
    fireEvent.submit(box.closest('form')!);
    expect(window.location.hash).toBe('#/a/abc-123/overview');
  });
});

describe('SettingsPage', () => {
  it('changes appearance settings immediately', async () => {
    await renderAsync(<SettingsPage />);
    fireEvent.click(screen.getByRole('radio', { name: 'Dark' }));
    expect(settingsStore.get().theme).toBe('dark');
    fireEvent.click(screen.getByRole('radio', { name: 'Compact' }));
    expect(settingsStore.get().density).toBe('compact');
    fireEvent.click(screen.getByRole('radio', { name: '65.3 s' }));
    expect(settingsStore.get().timecode).toBe('seconds');
  });
  it('shows the server versions and warns about an incompatible contract', async () => {
    connectionStore.set({ status: 'online', health: { status: 'ok', api_contract_version: '9.0.0', config_version: '1.0.0', pipeline_version: '1.0.0' }, checkedAt: 0 });
    await renderAsync(<SettingsPage />);
    expect(screen.getByText('9.0.0')).toBeInTheDocument();
    expect(screen.getByText(/different major version/)).toBeInTheDocument();
  });
  it('saves a new API address without a trailing slash', async () => {
    await renderAsync(<SettingsPage />);
    await userEvent.type(screen.getByLabelText('API address'), 'http://localhost:9000/');
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Save and test' })); });
    expect(settingsStore.get().apiBase).toBe('http://localhost:9000');
  });
  it('resets to the defaults after confirmation', async () => {
    settingsStore.set({ ...DEFAULT_SETTINGS, theme: 'dark', density: 'compact' });
    await renderAsync(<SettingsPage />);
    fireEvent.click(screen.getByRole('button', { name: 'Reset settings' }));
    await act(async () => { fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Reset' })); });
    expect(settingsStore.get().theme).toBe('system');
    expect(settingsStore.get().density).toBe('comfortable');
  });
});

describe('HelpPage', () => {
  it('explains the views, the glossary and lists the shortcuts', async () => {
    await renderAsync(<HelpPage />);
    expect(screen.getByRole('heading', { name: 'The six views' })).toBeInTheDocument();
    expect(screen.getByText('z-score')).toBeInTheDocument();
    expect(screen.getByText('Search and jump to anything (⌘K on Mac)')).toBeInTheDocument();
    expect(screen.getByText('Is anything written by an AI?')).toBeInTheDocument();
  });
  it('says how to record in the browser and how to export the findings', async () => {
    await renderAsync(<HelpPage />);
    const record = screen.getByText('How should I record a take in the browser?').closest('div') as HTMLElement;
    expect(record).toHaveTextContent('echo cancellation, noise suppression and automatic gain off');
    expect(record).toHaveTextContent('https:// or localhost');
    const exported = screen.getByText('Can I take the findings into a spreadsheet?').closest('div') as HTMLElement;
    expect(exported).toHaveTextContent('Export CSV');
  });
});
