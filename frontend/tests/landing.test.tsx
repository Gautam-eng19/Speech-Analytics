import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from '@/app/App';
import { Landing } from '@/features/landing/Landing';
import type { DemoState } from '@/features/landing/useDemoSample';
import { evidenceHeadline } from '@/lib/evidence';
import { fmtClock, fmtNum } from '@/lib/format';
import { readAt } from '@/lib/lookup';
import { DEFAULT_SETTINGS, settingsStore } from '@/lib/settings';
import { closeAnalysis } from '@/state/analysis';
import { clearHistory } from '@/state/history';
import { overlayStore } from '@/state/ui';
import { mixedResult } from './fixtures';
import { stubFetch, stubLayout } from './helpers';

const pauseAppPlayer = vi.hoisted(() => vi.fn());
vi.mock('@/state/player', async (importOriginal) => ({ ...(await importOriginal<typeof import('@/state/player')>()), pause: pauseAppPlayer }));

// The demo sample is loaded once per page load; a test that needs it missing says so here instead of fighting the cache.
const demoOverride = vi.hoisted(() => ({ current: null as null | { status: 'loading' | 'unavailable'; sample: null } }));
vi.mock('@/features/landing/useDemoSample', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/features/landing/useDemoSample')>();
  return { ...actual, useDemoSample: (): DemoState => demoOverride.current ?? actual.useDemoSample() };
});

// jsdom keeps no playback position; give the audio element one so seeking can be observed.
let position = 0;
beforeEach(() => {
  position = 0;
  Object.defineProperty(HTMLMediaElement.prototype, 'currentTime', { configurable: true, get: () => position, set: (v: number) => { position = v; } });
  Object.defineProperty(HTMLMediaElement.prototype, 'paused', { configurable: true, get: () => true });
});

const WIDTH = 1200;
// Role queries walk every node of a 500-element chart and are slow in jsdom, so the chart is queried by class and the page by role.
const flags = () => [...document.querySelectorAll<HTMLButtonElement>('button.hx-flag')];
async function renderLanding() {
  await act(async () => { render(<Landing><p>the analysis flow</p></Landing>); });
  await waitFor(() => expect(flags()).toHaveLength(mixedResult.flaws.length));
}
const stage = () => document.querySelector<HTMLElement>('.hx')!;
const readout = (label: string) => {
  const row = [...document.querySelectorAll('.hx__read-row')].find((r) => r.querySelector('dt')!.textContent === label)!;
  return row.querySelector('dd')!;
};

describe('the landing page', () => {
  beforeEach(() => {
    stubLayout(WIDTH, 400);
    stubFetch();
    closeAnalysis();
    clearHistory();
    pauseAppPlayer.mockClear();
    settingsStore.set({ ...DEFAULT_SETTINGS });
  });
  afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

  it('has one headline, and the two calls to action the brief asks for', async () => {
    await renderLanding();
    const h1 = screen.getAllByRole('heading', { level: 1 });
    expect(h1).toHaveLength(1);
    expect(h1[0]).toHaveTextContent('Hear the difference.');
    expect(h1[0]).toHaveTextContent('Understand the why.');
    expect(screen.getAllByRole('button', { name: /Analyse a recording/, hidden: true }).length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: 'Explore a demo analysis', hidden: true })).toBeInTheDocument();
  });

  it('shows the analysis flow it was given inside the section the first call to action jumps to', async () => {
    await renderLanding();
    const start = document.getElementById('start')!;
    expect(within(start).getByText('the analysis flow')).toBeInTheDocument();
    expect(within(start).getByRole('heading', { level: 2, name: 'Analyse a recording' })).toBeInTheDocument();
  });

  it('draws every finding of the demo sample as a button that names its time and its measured evidence', async () => {
    await renderLanding();
    expect(flags()).toHaveLength(mixedResult.flaws.length);
    mixedResult.flaws.forEach((flaw, i) => {
      const name = flags()[i]!.getAttribute('aria-label')!;
      expect(name).toMatch(/Play this moment\.$/);
      expect(name).toContain(`${fmtClock(flaw.start_s, 1)}–${fmtClock(flaw.end_s, 1)}`);
      expect(name).toContain(evidenceHeadline(flaw));
    });
  });

  it('reads the measurement at the pointer from the result, and goes back to idle when the pointer leaves', async () => {
    await renderLanding();
    const t = 7.2;
    const x = (t / (mixedResult.audio.source_duration_s ?? 1)) * WIDTH;
    fireEvent.pointerEnter(stage());
    fireEvent.pointerMove(stage(), { clientX: x, clientY: 120 });
    const expected = readAt(mixedResult, (x / WIDTH) * (mixedResult.audio.source_duration_s ?? 1));
    await waitFor(() => expect(readout('Time')).toHaveTextContent(fmtClock((x / WIDTH) * (mixedResult.audio.source_duration_s ?? 1), 1)));
    expect(readout('Pace')).toHaveTextContent(`${fmtNum(expected.rate!.wpm, 0)} words/min`);
    expect(readout('Loudness')).toHaveTextContent(`${fmtNum(expected.loudnessDb!, 1)} dBFS`);
    expect(readout('Finding')).toHaveTextContent('Too fast');
    expect(stage().dataset.active).toBe('true');

    fireEvent.pointerLeave(stage());
    expect(readout('Time')).toHaveTextContent('–');
    expect(readout('Finding')).toHaveTextContent('–');
    expect(stage().dataset.active).toBe('false');
  });

  it('clicking the trace seeks the demo audio there, plays it, and silences the app’s own player first', async () => {
    const play = vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined);
    await renderLanding();
    const duration = mixedResult.audio.source_duration_s ?? 1;
    fireEvent.click(stage(), { clientX: (20 / duration) * WIDTH, clientY: 150 });
    expect(position).toBeCloseTo(20, 1);
    expect(play).toHaveBeenCalled();
    expect(pauseAppPlayer).toHaveBeenCalled();
  });

  it('stops the demo audio when the page goes away, and not merely because the page re-rendered', async () => {
    vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined);
    const pause = vi.spyOn(HTMLMediaElement.prototype, 'pause');
    let utils!: ReturnType<typeof render>;
    await act(async () => { utils = render(<Landing><p>the analysis flow</p></Landing>); });
    await waitFor(() => expect(flags()).toHaveLength(mixedResult.flaws.length));
    fireEvent.click(flags()[0]!);                          // starts playing: state changes, the page re-renders
    fireEvent.pointerEnter(stage());
    expect(pause).not.toHaveBeenCalled();
    utils.unmount();
    expect(pause).toHaveBeenCalled();
  });

  it('a finding’s button plays just that interval', async () => {
    const play = vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined);
    await renderLanding();
    fireEvent.click(flags()[1]!);
    expect(position).toBe(mixedResult.flaws[1]!.start_s);
    expect(play).toHaveBeenCalledTimes(1);
  });

  it('falls back to a plainly labelled illustration, with nothing to play and no invented numbers, when the sample is missing', async () => {
    demoOverride.current = { status: 'unavailable', sample: null };
    try {
      await act(async () => { render(<Landing><p>flow</p></Landing>); });
      await waitFor(() => expect(document.querySelector('.hx-flag--static')).not.toBeNull());
      expect(screen.getByText('Illustration.')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'See how it works', hidden: true })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Play the demo recording', hidden: true })).toBeDisabled();
      expect(flags()).toHaveLength(0);
      expect(document.querySelector('.hx__data')!.textContent ?? '').not.toMatch(/\d+s\b/);
      expect(document.querySelector('audio')).toBeNull();
    } finally {
      demoOverride.current = null;
    }
  });

  it('turns every ambient effect off when reduced motion is asked for in Settings', async () => {
    settingsStore.set({ ...DEFAULT_SETTINGS, motion: 'reduce' });
    await renderLanding();
    expect(stage().dataset.motion).toBe('off');
    expect(document.querySelector('.hx-runner')).toBeNull();
  });

  it('keeps the evidence section to what the sample really says: its findings, and the highest-severity one in full', async () => {
    await renderLanding();
    const evidence = document.getElementById('evidence')!;
    const rows = within(evidence).getAllByRole('button', { hidden: true });
    expect(rows).toHaveLength(mixedResult.flaws.length);
    const featured = [...mixedResult.flaws].sort((a, b) => b.severity - a.severity)[0]!;
    expect(evidence).toHaveTextContent(featured.recommendation.slice(0, 40));
    expect(evidence).toHaveTextContent('Measured');
  });
});

describe('the landing navigation', () => {
  beforeEach(() => {
    stubLayout(WIDTH, 400);
    stubFetch();
    closeAnalysis();
    clearHistory();
    settingsStore.set({ ...DEFAULT_SETTINGS });
    overlayStore.set({ palette: false, shortcuts: false, mobileNav: false });
  });
  afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

  async function openHome() {
    window.location.hash = '#/';
    await act(async () => { render(<App />); });
  }

  it('links to the sections and to the pages that already exist, and has no sign-in', async () => {
    await openHome();
    const header = document.querySelector<HTMLElement>('.lnav')!;
    for (const name of ['Method', 'Evidence', 'Journey', 'Library', 'Custom passage', 'Help']) expect(within(header).getByRole('link', { name })).toBeInTheDocument();
    expect(within(header).getByRole('button', { name: 'Analyse a recording' })).toBeInTheDocument();
    expect(screen.queryByText(/sign[ -]?in|log[ -]?in|sign[ -]?up|create an account/i)).toBeNull();
    expect(screen.queryByRole('link', { name: /sign[ -]?in|log[ -]?in/i })).toBeNull();
  });

  it('takes the place of the top bar on the home page, and the sidebar stays reachable as the drawer', async () => {
    await openHome();
    expect(document.querySelector('.topbar')).toBeNull();
    expect(document.querySelector('.app')!.getAttribute('data-landing')).toBe('true');
    fireEvent.click(within(document.querySelector<HTMLElement>('.lnav')!).getByRole('button', { name: 'Open navigation' }));
    expect(overlayStore.get().mobileNav).toBe(true);
    expect(screen.getByRole('complementary', { name: 'Primary' })).toHaveAttribute('data-open', 'true');
  });

  it('jumps within the page without touching the address, and moves focus to the section’s heading', async () => {
    const scroll = vi.spyOn(Element.prototype, 'scrollIntoView').mockImplementation(() => undefined);
    await openHome();
    fireEvent.click(within(document.querySelector<HTMLElement>('.lnav')!).getByRole('link', { name: 'Evidence' }));
    expect(scroll).toHaveBeenCalled();
    expect(window.location.hash).toBe('#/');
    expect(document.activeElement).toBe(document.getElementById('evidence-title'));
  });

  it('moves keyboard focus into the drawer when it opens, closes it on Escape and gives focus back to the menu button', async () => {
    await openHome();
    const menu = within(document.querySelector<HTMLElement>('.lnav')!).getByRole('button', { name: 'Open navigation' });
    act(() => menu.focus());
    fireEvent.click(menu);
    const drawer = screen.getByRole('complementary', { name: 'Primary' });
    expect(drawer.contains(document.activeElement)).toBe(true);
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(overlayStore.get().mobileNav).toBe(false);
    expect(document.activeElement).toBe(menu);
  });

  it('"New analysis" asked for from inside the app goes to the analysis flow and focuses its heading, not back to the hero', async () => {
    const scroll = vi.spyOn(Element.prototype, 'scrollIntoView').mockImplementation(() => undefined);
    window.location.hash = '#/library';
    await act(async () => { render(<App />); });
    fireEvent.click(within(screen.getByRole('complementary', { name: 'Primary' })).getByRole('link', { name: /New analysis/ }));
    await waitFor(() => expect(scroll).toHaveBeenCalled());
    expect(window.location.hash).toBe('#/');
    expect(document.activeElement).toBe(document.getElementById('start-title'));
  });

  it('goes back to the top bar and the sidebar on every other page', async () => {
    window.location.hash = '#/library';
    await act(async () => { render(<App />); });
    expect(document.querySelector('.topbar')).not.toBeNull();
    expect(document.querySelector('.lnav')).toBeNull();
    expect(document.querySelector('.app')!.getAttribute('data-landing')).toBe('false');
  });
});
