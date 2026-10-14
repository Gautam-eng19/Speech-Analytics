import { fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { FlawsPage } from '@/features/flaws/FlawsPage';
import { flawsFilterStore, selectionStore } from '@/state/ui';
import { cleanResult, loaded, mixedResult } from './fixtures';
import { stubFetch, stubLayout, stubWideScreen } from './helpers';

const analysis = loaded(mixedResult);
const flaws = [...mixedResult.flaws].sort((a, b) => a.start_s - b.start_s);

describe('FlawsPage', () => {
  beforeEach(() => { stubLayout(900); stubFetch(); stubWideScreen(true); flawsFilterStore.set({ types: [], sort: 'time' }); selectionStore.set({ flawId: null }); });
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  it('lists every finding in time order and shows the first one in the detail pane', () => {
    render(<FlawsPage analysis={analysis} />);
    expect(screen.getAllByRole('option')).toHaveLength(flaws.length);
    expect(screen.getByText(`Finding 1 of ${flaws.length}`, { exact: false })).toBeInTheDocument();
  });

  it('shows the finding named in the address with its evidence, explanation and recommendation exactly as the backend wrote them', () => {
    const target = flaws[1]!;
    render(<FlawsPage analysis={analysis} flawId={target.flaw_id} />);
    expect(screen.getByText(`Finding 2 of ${flaws.length}`, { exact: false })).toBeInTheDocument();
    const text = (title: string) => screen.getByRole('heading', { name: title }).closest('.panel')!.textContent ?? '';
    expect(text('Explanation')).toContain(target.explanation);
    expect(text('Recommendation')).toContain(target.recommendation);
    expect(text('Evidence')).toContain(target.type === 'excessive_pause' ? 'Pause length' : 'Participant rate');
  });

  it('explains the detection rule in words, with the backend thresholds', () => {
    const rate = flaws.find((f) => f.type === 'too_fast')!;
    render(<FlawsPage analysis={analysis} flawId={rate.flaw_id} />);
    const panel = screen.getByRole('heading', { name: 'Detection rule' }).closest('.panel')!;
    expect(panel.textContent).toContain(`above ${rate.rule!.threshold_z.toFixed(1)}`);
    expect(panel.textContent).toContain(`${rate.rule!.min_duration_s.toFixed(1)} s`);
  });

  it('says what a word-by-word rule compares with, and uses the plain rule text for the overall one', () => {
    const rate = flaws.find((f) => f.type === 'too_fast')!;
    expect(rate.rule!.feature).toBe('rate_run_z');
    const { unmount } = render(<FlawsPage analysis={analysis} flawId={rate.flaw_id} />);
    let panel = screen.getByRole('heading', { name: 'Detection rule' }).closest('.panel')!;
    expect(panel.textContent).toContain('word-by-word pace z-score');
    expect(panel.textContent).toContain('what the baseline readings of the passage did with these same words');
    unmount();
    const overall = { ...mixedResult, flaws: mixedResult.flaws.map((f) => (f.flaw_id === rate.flaw_id ? { ...f, rule: { ...f.rule!, feature: 'rate_z' } } : f)) };
    render(<FlawsPage analysis={loaded(overall)} flawId={rate.flaw_id} />);
    panel = screen.getByRole('heading', { name: 'Detection rule' }).closest('.panel')!;
    expect(panel.textContent).toContain('speech-rate z-score');
    expect(panel.textContent).not.toContain('what the baseline readings of the passage did with these same words');
  });

  it('shows the finding’s own warnings', () => {
    const f = flaws.find((x) => (x.warnings?.length ?? 0) > 0)!;
    render(<FlawsPage analysis={analysis} flawId={f.flaw_id} />);
    expect(screen.getByText(f.warnings![0]!)).toBeInTheDocument();
  });

  it('filters the list by type and says how many of each there are', () => {
    render(<FlawsPage analysis={analysis} />);
    const chips = screen.getByRole('group', { name: 'Filter by finding type' });
    fireEvent.click(within(chips).getByRole('button', { name: /Excessive pause/ }));
    const options = screen.getAllByRole('option');
    expect(options).toHaveLength(flaws.filter((f) => f.type === 'excessive_pause').length);
    for (const option of options) expect(option.textContent).toContain('Excessive pause');
    fireEvent.click(within(chips).getByRole('button', { name: /^All/ }));
    expect(screen.getAllByRole('option')).toHaveLength(flaws.length);
  });

  it('sorts by severity when asked', () => {
    render(<FlawsPage analysis={loaded({ ...mixedResult, flaws: mixedResult.flaws.map((f, i) => ({ ...f, severity: [0.2, 0.9, 0.5][i] ?? 0.1 })) })} />);
    fireEvent.click(screen.getByRole('radio', { name: 'By severity' }));
    const values = screen.getAllByRole('option').map((o) => Number(o.querySelector('.sev__value')!.textContent));
    expect(values).toEqual([...values].sort((a, b) => b - a));
  });

  it('opens a finding when it is chosen in the list', () => {
    render(<FlawsPage analysis={analysis} />);
    fireEvent.click(screen.getAllByRole('option')[1]!);
    expect(window.location.hash).toBe(`#/a/${mixedResult.analysis_id}/flaws/${flaws[1]!.flaw_id}`);
    expect(selectionStore.get().flawId).toBe(flaws[1]!.flaw_id);
  });

  it('moves between findings with j and k', () => {
    render(<FlawsPage analysis={analysis} flawId={flaws[0]!.flaw_id} />);
    fireEvent.keyDown(window, { key: 'j' });
    expect(window.location.hash).toBe(`#/a/${mixedResult.analysis_id}/flaws/${flaws[1]!.flaw_id}`);
  });

  it('ignores j and k while typing in a field', () => {
    render(<><input aria-label="field" /><FlawsPage analysis={analysis} flawId={flaws[0]!.flaw_id} /></>);
    window.location.hash = '';
    fireEvent.keyDown(screen.getByLabelText('field'), { key: 'j' });
    expect(window.location.hash).toBe('');
  });

  it('has a friendly page when nothing was found', () => {
    const empty = loaded({ ...cleanResult, flaws: [] });
    render(<FlawsPage analysis={empty} />);
    expect(screen.getByText('Nothing crossed a detection rule')).toBeInTheDocument();
  });

  it('on a narrow screen shows the list first and the detail with a way back', () => {
    stubWideScreen(false);
    const { rerender } = render(<FlawsPage analysis={analysis} />);
    expect(screen.getAllByRole('option')).toHaveLength(flaws.length);
    expect(screen.queryByText(/Finding 1 of/)).toBeNull();
    rerender(<FlawsPage analysis={analysis} flawId={flaws[0]!.flaw_id} />);
    expect(screen.getByRole('button', { name: /All findings/ })).toBeInTheDocument();
    expect(screen.queryByRole('listbox')).toBeNull();
  });
});
