import { render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Sidebar } from '@/app/Sidebar';
import { Dialog, ScrollRegion } from '@/components/ui';
import { AnalyzePage } from '@/features/analyze/AnalyzePage';
import { TranscriptPage } from '@/features/transcript/TranscriptPage';
import { DEFAULT_SETTINGS, settingsStore } from '@/lib/settings';
import { closeAnalysis } from '@/state/analysis';
import { catalogStore, connectionStore } from '@/state/connection';
import { loaded, mixedResult } from './fixtures';
import { renderAsync, stubFetch, stubLayout } from './helpers';

/** Regressions found by the axe audit (frontend/scripts/a11y.mjs), pinned where a unit test can see them. */
describe('accessibility details', () => {
  beforeEach(() => { stubLayout(900); stubFetch(); settingsStore.set({ ...DEFAULT_SETTINGS }); closeAnalysis(); });
  afterEach(() => vi.unstubAllGlobals());

  it('names every sidebar link even when the labels are hidden', async () => {
    settingsStore.set({ ...DEFAULT_SETTINGS, sidebarCollapsed: true });
    await renderAsync(<Sidebar />);
    const nav = screen.getByRole('complementary', { name: 'Primary' });
    const links = within(nav).getAllByRole('link');
    expect(links.length).toBeGreaterThanOrEqual(5);
    for (const link of links) expect(link).toHaveAccessibleName();
    expect(within(nav).getByRole('link', { name: 'Library' })).toBeInTheDocument();
  });

  it('lets keyboard users reach scrollable regions', () => {
    render(<ScrollRegion label="Pauses"><p>wide table</p></ScrollRegion>);
    const region = screen.getByRole('region', { name: 'Pauses' });
    expect(region).toHaveAttribute('tabindex', '0');
  });

  it('makes the body of a dialog focusable so it can be scrolled by keyboard', () => {
    render(<Dialog open onClose={() => undefined} title="Long content"><p>text</p></Dialog>);
    const dialog = screen.getByRole('dialog', { name: 'Long content' });
    expect(dialog.querySelector('.dialog__body')).toHaveAttribute('tabindex', '0');
  });

  it('labels the hidden file input of the upload form', async () => {
    catalogStore.set({ status: 'ready', data: { baselines: [], unavailable: [] }, error: null });
    connectionStore.set({ status: 'online', health: null, checkedAt: 0 });
    await renderAsync(<AnalyzePage />);
    expect(screen.getByLabelText(/Choose an audio file/)).toHaveAttribute('type', 'file');
  });

  it('gives each pause drawn in the transcript a name, and shows low-confidence words by tint instead of fading the text', async () => {
    const low = { ...mixedResult, alignment: mixedResult.alignment.map((w, i) => (i === 3 ? { ...w, confidence: 0.4 } : w)) };
    await renderAsync(<TranscriptPage analysis={loaded(low)} />);
    const gaps = screen.getAllByRole('img', { name: /second pause/ });
    expect(gaps.length).toBe(document.querySelectorAll('.tgap').length);
    const word = document.getElementById('w-3')!;
    expect(word.style.getPropertyValue('--low')).toBe('0.6');
    expect(word.style.opacity).toBe('');
  });
});
