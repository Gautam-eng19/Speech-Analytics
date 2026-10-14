import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { OverviewPage } from '@/features/overview/OverviewPage';
import { analysisPath } from '@/app/router';
import { noteMeta } from '@/lib/notesMeta';
import { cleanResult, hesitantResult, loaded, mixedResult, tinyResult } from './fixtures';
import { renderAsync, stubFetch, stubLayout } from './helpers';

describe('OverviewPage', () => {
  beforeEach(() => { stubLayout(900); stubFetch(); });
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  it('shows the backend score, summary and finding count without recomputing anything', async () => {
    await renderAsync(<OverviewPage analysis={loaded(hesitantResult)} />);
    expect(screen.getByRole('heading', { level: 2, name: 'Hesitant delivery' })).toBeInTheDocument();
    expect(document.querySelector('.score__num')!.textContent).toBe(hesitantResult.scores.composite_score.toFixed(1));
    const summary = hesitantResult.overall_summary!;
    const firstSentence = summary.split(/(?<=\.)\s+(?=[A-Z])/)[0]!;
    expect(document.querySelector('.readout__lead')!.textContent).toBe(firstSentence);
    expect(document.querySelectorAll('.ledger__row')).toHaveLength(hesitantResult.flaws.length);
  });

  it('lists findings strongest first, each linking to its evidence', async () => {
    await renderAsync(<OverviewPage analysis={loaded(hesitantResult)} />);
    const rows = [...document.querySelectorAll<HTMLAnchorElement>('.ledger__row')];
    const severities = rows.map((row) => Number(row.querySelector('.sev__value')!.textContent));
    expect(severities).toEqual([...severities].sort((a, b) => b - a));
    const id = hesitantResult.analysis_id;
    expect(rows.every((row) => row.getAttribute('href')!.startsWith(`#/a/${id}/flaws/flaw_`))).toBe(true);
  });

  it('opens a finding when its row is clicked', async () => {
    await renderAsync(<OverviewPage analysis={loaded(hesitantResult)} />);
    const row = document.querySelector<HTMLAnchorElement>('.ledger__row')!;
    fireEvent.click(row);
    expect(window.location.hash).toBe(row.getAttribute('href'));
  });

  it('draws the score profile from the backend\'s dimension scores and keeps it in step with the list', async () => {
    await renderAsync(<OverviewPage analysis={loaded(mixedResult)} />);
    const axes = screen.getAllByRole('button', { name: /out of 100|not scored/ });
    expect(axes).toHaveLength(4);
    const scores = mixedResult.scores.feature_scores;
    for (const [key, label] of [['speech_rate', 'Speech rate'], ['pauses', 'Pauses'], ['energy', 'Energy']] as const) {
      const entry = scores[key]!;
      expect(screen.getByRole('button', { name: new RegExp(`^${label}: ${entry.score.toFixed(1)} out of 100`) })).toBeInTheDocument();
    }
    const rows = [...document.querySelectorAll<HTMLElement>('.dims .dim')];
    fireEvent.pointerEnter(axes[1]!);
    expect(rows.map((r) => r.classList.contains('is-active'))).toEqual([false, true, false, false]);
    fireEvent.pointerEnter(rows[2]!);
    expect(document.querySelector('.radar__axis.is-active')!.getAttribute('aria-label')).toMatch(/^Energy/);
    fireEvent.pointerLeave(rows[2]!);
    expect(document.querySelector('.radar__axis.is-active')).toBeNull();
  });

  it('opens the strongest finding of a dimension when its spoke is clicked, and does nothing for a dimension without findings', async () => {
    await renderAsync(<OverviewPage analysis={loaded(mixedResult)} />);
    window.location.hash = '#/start';
    const strongest = [...mixedResult.flaws].filter((f) => f.type === 'too_fast' || f.type === 'too_slow').sort((a, b) => b.severity - a.severity)[0]!;
    fireEvent.click(screen.getByRole('button', { name: /^Speech rate:/ }));
    expect(window.location.hash).toBe(`#${analysisPath(mixedResult.analysis_id, 'flaws', strongest.flaw_id)}`);
    window.location.hash = '#/start';
    const quiet = screen.getAllByRole('button', { name: /out of 100/ }).find((b) => /, 0 findings/.test(b.getAttribute('aria-label') ?? ''));
    if (quiet) { fireEvent.click(quiet); expect(window.location.hash).toBe('#/start'); }
  });

  it('scores pitch when the baseline has a pitch profile (the demo baseline has one)', async () => {
    await renderAsync(<OverviewPage analysis={loaded(mixedResult)} />);
    const pitch = screen.getByText('Pitch', { selector: '.dim__name' }).closest('.dim')! as HTMLElement;
    const entry = mixedResult.scores.feature_scores.pitch!;
    expect(pitch.querySelector('.dim__value')!.textContent).toBe(entry.score.toFixed(1));
    expect(within(pitch).queryByText('not scored')).toBeNull();
  });

  it('says plainly when a dimension was not scored and why', async () => {
    const { pitch: _left_out, ...scored } = mixedResult.scores.feature_scores;       // a baseline built before the pitch profile existed: the backend leaves pitch out and says why
    const note = { code: 'pitch_not_scored', message: 'Pitch was not evaluated and is not part of the score: flat_pitch: the baseline has no pitch profile.' };
    const withoutPitch = { ...mixedResult, scores: { ...mixedResult.scores, feature_scores: scored }, notes: [...(mixedResult.notes ?? []), note] };
    await renderAsync(<OverviewPage analysis={loaded(withoutPitch)} />);
    const pitch = screen.getByText('Pitch', { selector: '.dim__name' }).closest('.dim')!;
    expect(within(pitch as HTMLElement).getByText('not scored')).toBeInTheDocument();
    expect(pitch.textContent).toContain(note.message);
  });

  it('shows dimension scores with their effective weights', async () => {
    await renderAsync(<OverviewPage analysis={loaded(mixedResult)} />);
    const rate = screen.getByText('Speech rate', { selector: '.dim__name' }).closest('.dim')! as HTMLElement;
    const entry = mixedResult.scores.feature_scores.speech_rate!;
    expect(rate.querySelector('.dim__value')!.textContent).toBe(entry.score.toFixed(1));
    expect(rate.textContent).toContain(`weight ${Math.round(entry.weight * 100)} %`);
  });

  it('reproduces every note the backend attached, grouped, with cautions counted', async () => {
    await renderAsync(<OverviewPage analysis={loaded(mixedResult)} />);
    const panel = screen.getByRole('heading', { name: 'Notes and limitations' }).closest('.panel') as HTMLElement;
    for (const note of mixedResult.notes!) expect(within(panel).getByText(note.message)).toBeInTheDocument();
    const cautions = mixedResult.notes!.filter((n) => noteMeta(n.code).level === 'caution').length;
    expect(within(panel).getByText(new RegExp(`${mixedResult.notes!.length} notes? · ${cautions} caution`))).toBeInTheDocument();
  });

  it('shows provenance with the full hashes one hover away', async () => {
    await renderAsync(<OverviewPage analysis={loaded(mixedResult)} />);
    expect(screen.getAllByTitle(mixedResult.analysis_id).length).toBeGreaterThan(0);
    expect(screen.getAllByTitle(mixedResult.audio.sha256).length).toBeGreaterThan(0);
    expect(screen.getAllByTitle(mixedResult.baseline.sha256).length).toBeGreaterThan(0);
  });

  it('labels a synthetic sample and lists its injected flaws with the outcome the generator stored', async () => {
    const injected = loaded(mixedResult).sample!.injected;
    await renderAsync(<OverviewPage analysis={loaded(mixedResult)} />);
    expect(screen.getAllByText('Synthetic sample').length).toBeGreaterThan(0);
    expect(screen.getByText('Synthetic demonstration')).toBeInTheDocument();
    expect(screen.getAllByText('detected')).toHaveLength(injected.filter((t) => t.detected).length);
    expect(screen.queryAllByText('not detected')).toHaveLength(injected.filter((t) => !t.detected).length);
    await waitFor(() => expect(screen.getByText(/How this sample was chosen/)).toBeInTheDocument());
  });

  it('says so when a sample was not detected: an injected flaw that was missed is shown as missed', async () => {
    const base = loaded(mixedResult);
    const missed = { ...base.sample!, injected: base.sample!.injected.map((t, i) => (i === 0 ? { ...t, detected: false } : t)) };
    await renderAsync(<OverviewPage analysis={{ ...base, sample: missed }} />);
    expect(screen.getAllByText('not detected')).toHaveLength(1);
    expect(screen.getAllByText('detected')).toHaveLength(base.sample!.injected.length - 1);
  });

  it('does not show the sample banner for an uploaded recording', async () => {
    await renderAsync(<OverviewPage analysis={loaded(tinyResult(), { source: 'upload', sample: null })} />);
    expect(screen.queryByText('Synthetic demonstration')).toBeNull();
    expect(screen.getByText('Uploaded recording')).toBeInTheDocument();
  });

  it('says so when nothing was flagged', async () => {
    await renderAsync(<OverviewPage analysis={loaded(cleanResult)} />);
    if (cleanResult.flaws.length === 0) {
      expect(screen.getByText('No findings')).toBeInTheDocument();
      expect(screen.getByText('No deviation flagged')).toBeInTheDocument();
    } else {
      expect(document.querySelectorAll('.ledger__row').length).toBeGreaterThan(0);
    }
  });

  it('opens the timeline at the clicked moment of the figure', async () => {
    await renderAsync(<OverviewPage analysis={loaded(mixedResult)} />);
    const plots = document.querySelector('.stack__plots')!;
    fireEvent.pointerDown(plots, { clientX: 450, button: 0, pointerId: 1 });
    fireEvent.pointerUp(plots, { clientX: 450, pointerId: 1 });
    expect(window.location.hash).toBe(`#${analysisPath(mixedResult.analysis_id, 'timeline')}`);
  });
});
