import { describe, expect, it } from 'vitest';
import { clamp, clampWindow, floorIndex, FULL, nearestIndex, panBy, span, tickLabel, timeTicks, windowAround, zoomAt } from '@/lib/time';

describe('windows', () => {
  it('keeps a window inside the recording without changing its span', () => {
    expect(clampWindow({ t0: -3, t1: 7 }, 60)).toEqual({ t0: 0, t1: 10 });
    expect(clampWindow({ t0: 55, t1: 65 }, 60)).toEqual({ t0: 50, t1: 60 });
  });
  it('shrinks a window that is longer than the recording', () => {
    expect(clampWindow({ t0: 0, t1: 100 }, 60)).toEqual({ t0: 0, t1: 60 });
  });
  it('zooms in around an anchor, keeping its place on screen', () => {
    const next = zoomAt({ t0: 0, t1: 10 }, 2, 5, 60);
    expect(next.t0).toBeCloseTo(2.5);
    expect(next.t1).toBeCloseTo(7.5);
    const atStart = zoomAt({ t0: 0, t1: 10 }, 2, 0, 60);
    expect(atStart).toEqual({ t0: 0, t1: 5 });
  });
  it('keeps an off-centre anchor at the same relative position', () => {
    const next = zoomAt({ t0: 0, t1: 10 }, 2, 2, 60);
    expect(next.t0).toBeCloseTo(1);
    expect(next.t1).toBeCloseTo(6);
    const late = zoomAt({ t0: 10, t1: 20 }, 4, 18, 60);
    expect((18 - late.t0) / (late.t1 - late.t0)).toBeCloseTo(0.8, 5);
  });
  it('never zooms in past the smallest span or out past the recording', () => {
    expect(span(zoomAt({ t0: 10, t1: 10.6 }, 100, 10.3, 60))).toBeCloseTo(0.5);
    expect(zoomAt({ t0: 10, t1: 40 }, 0.01, 20, 60)).toEqual(FULL(60));
  });
  it('pans and clamps at the edges', () => {
    expect(panBy({ t0: 10, t1: 20 }, 5, 60)).toEqual({ t0: 15, t1: 25 });
    expect(panBy({ t0: 2, t1: 12 }, -10, 60)).toEqual({ t0: 0, t1: 10 });
    expect(panBy({ t0: 45, t1: 55 }, 30, 60)).toEqual({ t0: 50, t1: 60 });
  });
  it('shows context around an interval', () => {
    const w = windowAround(10, 14, 60, 0.5);
    expect(w).toEqual({ t0: 8, t1: 16 });
    expect(windowAround(0, 2, 60, 1)).toEqual({ t0: 0, t1: 6 });
  });
  it('clamps numbers', () => {
    expect(clamp(5, 0, 3)).toBe(3);
    expect(clamp(-1, 0, 3)).toBe(0);
  });
});

describe('ticks', () => {
  it('chooses round steps so labels are far enough apart', () => {
    const ticks = timeTicks({ t0: 0, t1: 10 }, 1000, 84);
    expect(ticks[0]).toBe(0);
    expect(ticks[1]! - ticks[0]!).toBeGreaterThanOrEqual(0.84);
    const px = ((ticks[1]! - ticks[0]!) / 10) * 1000;
    expect(px).toBeGreaterThanOrEqual(84);
  });
  it('starts at the first tick inside the window', () => {
    const ticks = timeTicks({ t0: 12.3, t1: 40 }, 800, 84);
    expect(ticks[0]).toBeGreaterThanOrEqual(12.3);
    expect(ticks.every((t) => t <= 40)).toBe(true);
  });
  it('returns nothing for an empty window', () => {
    expect(timeTicks({ t0: 5, t1: 5 }, 800)).toEqual([]);
    expect(timeTicks({ t0: 0, t1: 5 }, 0)).toEqual([]);
  });
  it('labels ticks, with the seconds zero-padded after a minute', () => {
    expect(tickLabel(5, 1)).toBe('5s');
    expect(tickLabel(65, 5)).toBe('1:05');
    expect(tickLabel(65.5, 0.5)).toBe('1:05.5');
    expect(tickLabel(1.5, 0.5)).toBe('1.5s');
  });
});

describe('lookup in sorted arrays', () => {
  const xs = [0, 1, 2, 4, 8];
  it('finds the last element not after x', () => {
    expect(floorIndex(xs, -1)).toBe(-1);
    expect(floorIndex(xs, 0)).toBe(0);
    expect(floorIndex(xs, 3)).toBe(2);
    expect(floorIndex(xs, 99)).toBe(4);
  });
  it('finds the nearest element', () => {
    expect(nearestIndex(xs, 2.9)).toBe(2);
    expect(nearestIndex(xs, 3.1)).toBe(3);
    expect(nearestIndex(xs, -5)).toBe(0);
    expect(nearestIndex(xs, 100)).toBe(4);
    expect(nearestIndex([], 1)).toBe(-1);
  });
});
