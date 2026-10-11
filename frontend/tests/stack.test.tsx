import { fireEvent, render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TimelineStack } from '@/charts/TimelineStack';
import { fmtLevel, fmtNum } from '@/lib/format';
import { FULL } from '@/lib/time';
import { hoverStore, selectionStore } from '@/state/ui';
import { loaded, mixedResult } from './fixtures';
import { stubLayout } from './helpers';

const analysis = loaded(mixedResult);
const duration = mixedResult.audio.source_duration_s!;

function setup(props: Partial<React.ComponentProps<typeof TimelineStack>> = {}) {
  const onView = vi.fn();
  const onSelect = vi.fn();
  const onPlotClick = vi.fn();
  const utils = render(
    <TimelineStack
      analysis={analysis}
      lanes={['flaws', 'words', 'loudness', 'pitch', 'rate', 'pauses']}
      view={{ t0: 10, t1: 20 }}
      onView={onView}
      selected={null}
      onSelect={onSelect}
      onPlotClick={onPlotClick}
      showTruth
      label="test timeline"
      {...props}
    />,
  );
  const plots = utils.container.querySelector('.stack__plots') as HTMLElement;
  return { ...utils, plots, onView, onSelect, onPlotClick };
}

describe('TimelineStack', () => {
  beforeEach(() => { stubLayout(900); hoverStore.set(null); selectionStore.set({ flawId: null }); });
  afterEach(() => vi.restoreAllMocks());

  it('draws every requested lane plus the axis, and the ground-truth lane for samples', () => {
    const { container } = setup();
    for (const lane of ['axis', 'flaws', 'truth', 'words', 'loudness', 'pitch', 'rate', 'pauses']) {
      expect(container.querySelector(`.lane--${lane}`), lane).not.toBeNull();
    }
  });
  it('leaves out the ground-truth lane when asked, and lanes that are not requested', () => {
    const { container } = setup({ showTruth: false, lanes: ['flaws', 'loudness'] });
    expect(container.querySelector('.lane--truth')).toBeNull();
    expect(container.querySelector('.lane--pitch')).toBeNull();
    expect(container.querySelector('.lane--loudness')).not.toBeNull();
  });
  it('labels each lane from the result, with baseline numbers at fixed decimals', () => {
    const { container } = setup();
    expect(container.querySelector('.glabel--rate')!.textContent).toContain('baseline 141 ± 12');
    const stats = mixedResult.baseline_stats;
    expect(container.querySelector('.glabel--loudness')!.textContent).toContain(`baseline ${fmtLevel(stats.energy_db_mean, 1)} ± ${fmtNum(stats.energy_db_std, 1)}`);
  });
  it('shows one button per finding that is on screen and reports which was chosen', () => {
    const { container, onSelect } = setup({ view: FULL(duration) });
    const bands = container.querySelectorAll('.flawband');
    expect(bands.length).toBe(mixedResult.flaws.length);
    fireEvent.click(bands[0]!);
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ flaw_id: mixedResult.flaws[0]!.flaw_id }));
  });
  it('marks the selected finding', () => {
    const { container } = setup({ view: FULL(duration), selected: mixedResult.flaws[1]! });
    const pressed = [...container.querySelectorAll('.flawband')].filter((b) => b.getAttribute('aria-pressed') === 'true');
    expect(pressed).toHaveLength(1);
    expect(pressed[0]!.getAttribute('data-flaw')).toBe(mixedResult.flaws[1]!.flaw_id);
  });

  it('zooms in around the pointer on wheel, keeping the time under it fixed', () => {
    const { plots, onView } = setup();
    fireEvent.wheel(plots, { deltaY: -500, clientX: 450 });
    expect(onView).toHaveBeenCalledTimes(1);
    const next = onView.mock.calls[0]![0] as { t0: number; t1: number };
    expect(next.t1 - next.t0).toBeLessThan(10);
    const anchorBefore = 10 + 0.5 * 10;
    const anchorAfter = next.t0 + 0.5 * (next.t1 - next.t0);
    expect(anchorAfter).toBeCloseTo(anchorBefore, 5);
  });
  it('zooms out on a downward wheel', () => {
    const { plots, onView } = setup();
    fireEvent.wheel(plots, { deltaY: 500, clientX: 450 });
    const next = onView.mock.calls[0]![0] as { t0: number; t1: number };
    expect(next.t1 - next.t0).toBeGreaterThan(10);
  });
  it('pans on Shift + wheel', () => {
    const { plots, onView } = setup();
    fireEvent.wheel(plots, { deltaY: 90, shiftKey: true, clientX: 450 });
    const next = onView.mock.calls[0]![0] as { t0: number; t1: number };
    expect(next.t0).toBeGreaterThan(10);
    expect(next.t1 - next.t0).toBeCloseTo(10, 5);
  });
  it('pans by dragging, in the opposite direction of the movement', () => {
    const { plots, onView } = setup();
    fireEvent.pointerDown(plots, { clientX: 600, button: 0, pointerId: 1 });
    fireEvent.pointerMove(plots, { clientX: 510, pointerId: 1 });
    const next = onView.mock.calls.at(-1)![0] as { t0: number; t1: number };
    expect(next.t0).toBeCloseTo(11, 5);
    expect(next.t1).toBeCloseTo(21, 5);
  });
  it('treats a press without movement as a click on the plot', () => {
    const { plots, onPlotClick, onView } = setup();
    fireEvent.pointerDown(plots, { clientX: 450, button: 0, pointerId: 1 });
    fireEvent.pointerUp(plots, { clientX: 450, pointerId: 1 });
    expect(onView).not.toHaveBeenCalled();
    expect(onPlotClick).toHaveBeenCalledTimes(1);
    expect(onPlotClick.mock.calls[0]![0]).toBeCloseTo(15, 5);
  });
  it('does not treat a drag as a click', () => {
    const { plots, onPlotClick } = setup();
    fireEvent.pointerDown(plots, { clientX: 600, button: 0, pointerId: 1 });
    fireEvent.pointerMove(plots, { clientX: 400, pointerId: 1 });
    fireEvent.pointerUp(plots, { clientX: 400, pointerId: 1 });
    expect(onPlotClick).not.toHaveBeenCalled();
  });
  it('fits the whole recording on double-click', () => {
    const { plots, onView } = setup();
    fireEvent.doubleClick(plots);
    expect(onView).toHaveBeenCalledWith({ t0: 0, t1: duration });
  });
  it('publishes the pointer time for the crosshair and clears it on leave', () => {
    const { plots } = setup();
    fireEvent.pointerMove(plots, { clientX: 225, pointerId: 1 });
    expect(hoverStore.get()).toBeCloseTo(12.5, 5);
    fireEvent.pointerLeave(plots);
    expect(hoverStore.get()).toBeNull();
  });
  it('is read-only (no zoom or pan) without an onView handler', () => {
    const { plots, onPlotClick } = setup({ onView: undefined });
    fireEvent.wheel(plots, { deltaY: -500 });
    fireEvent.pointerDown(plots, { clientX: 450, button: 0, pointerId: 1 });
    fireEvent.pointerUp(plots, { clientX: 450, pointerId: 1 });
    expect(onPlotClick).toHaveBeenCalledTimes(1);
  });
});
