import { describe, expect, it } from 'vitest';
import { areaPath, envelope, extent, linePath, niceTicks, scaleLinear, stepPath, voicedRuns } from '@/lib/decimate';

const series = (n: number, f: (i: number) => number) => ({ t: Array.from({ length: n }, (_, i) => i * 0.01), v: Array.from({ length: n }, (_, i) => f(i)) });

describe('envelope', () => {
  it('returns every point when the series is short', () => {
    const { t, v } = series(10, (i) => i);
    const out = envelope(t, v, 0, 0.09, 100);
    expect(out.length).toBe(10);
  });
  it('thins long series but keeps the extremes of every bucket', () => {
    const { t, v } = series(5000, (i) => (i === 2500 ? 99 : i === 1234 ? -99 : Math.sin(i / 7)));
    const out = envelope(t, v, 0, 50, 200);
    expect(out.length).toBeLessThanOrEqual(400 + 2);
    expect(Math.max(...out.map((p) => p.v))).toBe(99);
    expect(Math.min(...out.map((p) => p.v))).toBe(-99);
  });
  it('in peak mode keeps one point per bucket and never loses the maximum', () => {
    const { t, v } = series(5000, (i) => (i === 3000 ? 50 : Math.sin(i / 5)));
    const out = envelope(t, v, 0, 50, 200, 'peak');
    expect(out.length).toBeLessThanOrEqual(201);
    expect(Math.max(...out.map((p) => p.v))).toBe(50);
  });
  it('returns nothing for empty input or an empty window', () => {
    expect(envelope([], [], 0, 1, 100)).toEqual([]);
    expect(envelope([0, 1], [1, 2], 5, 5, 100)).toEqual([]);
  });
  it('includes a neighbour on each side so lines reach the edges', () => {
    const out = envelope([0, 1, 2, 3, 4, 5], [0, 1, 2, 3, 4, 5], 2.5, 3.5, 100);
    expect(out.map((p) => p.t)).toEqual([2, 3, 4]);
  });
});

describe('voicedRuns', () => {
  it('splits at unvoiced samples so gaps are real gaps', () => {
    const runs = voicedRuns([0, 1, 2, 3, 4, 5], [100, 101, null, null, 102, 103], 0, 5, 1000);
    expect(runs.map((r) => r.points.map((p) => p.v))).toEqual([[100, 101], [102, 103]]);
  });
  it('returns no runs when nothing is voiced', () => {
    expect(voicedRuns([0, 1], [null, null], 0, 1, 100)).toEqual([]);
  });
});

describe('scales, paths and ticks', () => {
  it('maps a domain onto a range, including inverted ranges', () => {
    const y = scaleLinear(0, 10, 100, 0);
    expect(y(0)).toBe(100);
    expect(y(10)).toBe(0);
    expect(y(2.5)).toBe(75);
    expect(scaleLinear(5, 5, 0, 10)(7)).toBe(0);
  });
  it('finds the extent while skipping gaps', () => {
    expect(extent([3, null, 1, Number.NaN, 7])).toEqual([1, 7]);
    expect(extent([null, null])).toBeNull();
  });
  it('writes line, step and area paths', () => {
    const pts = [{ t: 0, v: 0 }, { t: 1, v: 2 }];
    const x = (t: number) => t * 10;
    const y = (v: number) => 20 - v * 5;
    expect(linePath(pts, x, y)).toBe('M0.0 20.0L10.0 10.0');
    expect(stepPath(pts, x, y)).toBe('M0.0 20.0H10.0V10.0');
    expect(areaPath(pts, x, y, 30)).toBe('M0.0 20.0L10.0 10.0L10.0 30.0L0.0 30.0Z');
    expect(linePath([], x, y)).toBe('');
    expect(areaPath([], x, y, 30)).toBe('');
  });
  it('chooses round ticks inside the range', () => {
    expect(niceTicks(0, 100, 4)).toEqual([0, 20, 40, 60, 80, 100]);
    expect(niceTicks(-80, 0, 4)).toEqual([-80, -60, -40, -20, 0]);
    expect(niceTicks(0.1, 0.9, 4).every((v) => v >= 0.1 && v <= 0.9)).toBe(true);
    expect(niceTicks(0, 90, 10)).toEqual([0, 10, 20, 30, 40, 50, 60, 70, 80, 90]);
    expect(niceTicks(0, 7, 2)).toEqual([0, 5]);
    expect(niceTicks(5, 5)).toEqual([]);
  });
});
