import { describe, expect, it } from 'vitest';
import { evidenceHeadline } from '@/lib/evidence';
import { fmtClock, fmtNum } from '@/lib/format';
import { assignTiers, buildScene, illustrativeInput, inputFromResult, LOUDNESS_FLOOR_DB, monotonePath, peakBuckets } from '@/features/landing/heroModel';
import { cleanResult, mixedResult } from './fixtures';

/** Pull the numbers back out of a path string: M x y, then C c1x c1y c2x c2y x y for every segment. */
function segments(path: string): { y0: number; y1: number; c1y: number; c2y: number }[] {
  const nums = (path.match(/-?\d+(?:\.\d+)?/g) ?? []).map(Number);
  const out: { y0: number; y1: number; c1y: number; c2y: number }[] = [];
  let y0 = nums[1] as number;
  for (let i = 2; i + 5 < nums.length + 0; i += 6) {
    out.push({ y0, c1y: nums[i + 1] as number, c2y: nums[i + 3] as number, y1: nums[i + 5] as number });
    y0 = nums[i + 5] as number;
  }
  return out;
}

describe('monotonePath', () => {
  it('is empty for no points and a lone move for one', () => {
    expect(monotonePath([])).toBe('');
    expect(monotonePath([{ x: 3, y: 4 }])).toBe('M3 4');
  });

  it('starts at the first point and ends at the last', () => {
    const d = monotonePath([{ x: 0, y: 10 }, { x: 10, y: 4 }, { x: 20, y: 12 }]);
    expect(d.startsWith('M0 10')).toBe(true);
    expect(d.endsWith('20 12')).toBe(true);
  });

  it('never leaves the range of the two samples it joins, so a smoothed rate never claims a value the data did not reach', () => {
    const points = [0, 5, 6, 30, 31, 8, 8, 9, 50].map((y, i) => ({ x: i * 10, y }));
    const parts = segments(monotonePath(points));
    expect(parts).toHaveLength(points.length - 1);
    for (const s of parts) {
      const lo = Math.min(s.y0, s.y1);
      const hi = Math.max(s.y0, s.y1);
      expect(s.c1y).toBeGreaterThanOrEqual(lo - 0.01);
      expect(s.c1y).toBeLessThanOrEqual(hi + 0.01);
      expect(s.c2y).toBeGreaterThanOrEqual(lo - 0.01);
      expect(s.c2y).toBeLessThanOrEqual(hi + 0.01);
    }
  });

  it('keeps a flat run flat', () => {
    const parts = segments(monotonePath([{ x: 0, y: 7 }, { x: 10, y: 7 }, { x: 20, y: 7 }]));
    for (const s of parts) expect([s.y0, s.c1y, s.c2y, s.y1]).toEqual([7, 7, 7, 7]);
  });

  it('gives the same string every time', () => {
    const points = [3, 9, 4, 4, 12].map((y, i) => ({ x: i * 7.5, y }));
    expect(monotonePath(points)).toBe(monotonePath(points));
  });
});

describe('peakBuckets', () => {
  it('keeps the loudest value of each slice of time', () => {
    expect(peakBuckets([0.1, 0.4, 0.6], [-50, -20, -30], 1, 2)).toEqual([-20, -30]);
  });

  it('reads an empty slice as the meter floor and ignores values that are not numbers or lie outside the recording', () => {
    expect(peakBuckets([0.1, 0.9, 5, -1, Number.NaN], [-40, Number.NaN, -10, -10, -10], 1, 4)).toEqual([-40, LOUDNESS_FLOOR_DB, LOUDNESS_FLOOR_DB, LOUDNESS_FLOOR_DB]);
  });

  it('copes with nothing to count', () => {
    expect(peakBuckets([], [], 1, 0)).toEqual([]);
    expect(peakBuckets([0.2], [-30], 0, 3)).toEqual([LOUDNESS_FLOOR_DB, LOUDNESS_FLOOR_DB, LOUDNESS_FLOOR_DB]);
  });
});

describe('assignTiers', () => {
  it('puts labels that do not touch on the first tier', () => {
    expect(assignTiers([{ left: 0, width: 50 }, { left: 100, width: 50 }, { left: 200, width: 50 }], 3)).toEqual([0, 0, 0]);
  });

  it('moves a label that would overlap down a tier, and back up once the first tier is free again', () => {
    expect(assignTiers([{ left: 0, width: 120 }, { left: 60, width: 80 }, { left: 140, width: 40 }], 3)).toEqual([0, 1, 0]);
  });

  it('never drops a label when every tier is taken, and is deterministic', () => {
    const items = [{ left: 0, width: 200 }, { left: 10, width: 200 }, { left: 20, width: 200 }];
    const first = assignTiers(items, 2);
    expect(first).toHaveLength(3);
    expect(first).toEqual(assignTiers(items, 2));
    expect(first.every((t) => t === 0 || t === 1)).toBe(true);
  });
});

describe('buildScene from the mixed-flaws result', () => {
  const input = inputFromResult(mixedResult);
  const scene = buildScene(input, 1200);

  it('has one labelled interval per finding, in time order, inside the picture, with the backend’s own evidence line', () => {
    expect(scene.flags.map((f) => f.id)).toEqual(mixedResult.flaws.map((f) => f.flaw_id));
    mixedResult.flaws.forEach((flaw, i) => {
      const flag = scene.flags[i]!;
      expect(flag.type).toBe(flaw.type);
      expect(flag.start).toBe(flaw.start_s);
      expect(flag.end).toBe(flaw.end_s);
      expect(flag.evidence).toBe(evidenceHeadline(flaw));
      expect(flag.interval).toBe(`${fmtClock(flaw.start_s, 1)}–${fmtClock(flaw.end_s, 1)}`);
      expect(flag.x0).toBeGreaterThanOrEqual(0);
      expect(flag.x1).toBeGreaterThan(flag.x0);
      expect(flag.x1).toBeLessThanOrEqual(scene.width);
      expect(flag.left).toBeGreaterThanOrEqual(0);
      expect(flag.left + flag.width).toBeLessThanOrEqual(scene.width);
    });
  });

  it('colours a loudness bar as a deviation exactly when its time lies inside a finding', () => {
    const step = scene.duration / scene.loud.bars.length;
    scene.loud.bars.forEach((bar, i) => {
      const centre = (i + 0.5) * step;
      const inside = mixedResult.flaws.some((f) => centre >= f.start_s && centre <= f.end_s);
      expect(bar.hot, `bar ${i} at ${centre.toFixed(2)} s`).toBe(inside);
    });
    expect(scene.loud.bars.some((b) => b.hot)).toBe(true);
  });

  it('draws the reference corridor from the baseline’s own statistics and names it with them', () => {
    const stats = mixedResult.baseline_stats;
    expect(scene.rate.corridorLabel).toBe(`reference ${fmtNum(stats.rate_wpm_mean, 0)} ± ${fmtNum(stats.rate_wpm_std, 0)} words/min`);
    expect(scene.rate.band1).not.toBeNull();
    const [top, bottom] = scene.rate.band1!;
    expect(bottom).toBeGreaterThan(top);
    expect(scene.rate.mean).toBeGreaterThan(top);
    expect(scene.rate.mean).toBeLessThan(bottom);
  });

  it('puts the trace where the rate samples are: one point per sample, at its time and value', () => {
    const rate = mixedResult.features.speech_rate_timeline;
    expect(scene.rate.points).toHaveLength(rate.times_s.length);
    scene.rate.points.forEach((p, i) => {
      expect(p.x).toBeCloseTo(scene.toX(rate.times_s[i]!), 1);
      expect(p.y).toBeCloseTo(scene.rate.toY(rate.words_per_min[i]!), 1);
    });
    const faster = scene.rate.points.reduce((best, p) => (p.y < best.y ? p : best));
    expect(scene.rate.toY(Math.max(...rate.words_per_min))).toBeCloseTo(faster.y, 1);
  });

  it('maps pixels back to times and stays inside the recording', () => {
    expect(scene.toTime(-50)).toBe(0);
    expect(scene.toTime(10_000)).toBeCloseTo(scene.duration, 6);
    expect(scene.toTime(scene.toX(20))).toBeCloseTo(20, 6);
  });

  it('labels the time axis and gives the same picture twice', () => {
    expect(scene.axis.ticks.length).toBeGreaterThan(3);
    expect(scene.axis.ticks.every((t) => t.label.length > 0)).toBe(true);
    expect(JSON.stringify(buildScene(input, 1200))).toBe(JSON.stringify(scene));
  });

  it('on a narrow screen uses fewer, shorter labels and still keeps every label clear of its neighbour', () => {
    const narrow = buildScene(input, 390);
    expect(narrow.compact).toBe(true);
    expect(narrow.flags).toHaveLength(mixedResult.flaws.length);
    const byTier = new Map<number, typeof narrow.flags>();
    for (const f of narrow.flags) byTier.set(f.tier, [...(byTier.get(f.tier) ?? []), f]);
    for (const row of byTier.values()) {
      const ordered = [...row].sort((a, b) => a.left - b.left);
      ordered.forEach((f, i) => { if (i > 0) expect(f.left).toBeGreaterThanOrEqual(ordered[i - 1]!.left + ordered[i - 1]!.width); });
    }
    expect(narrow.flags.every((f) => f.evidence === '')).toBe(true);
    for (const f of narrow.flags) {                                       // and none sticks out of the picture, at either edge
      expect(f.left).toBeGreaterThanOrEqual(0);
      expect(f.left + f.width).toBeLessThanOrEqual(narrow.width);
    }
  });
});

describe('buildScene without findings or without data', () => {
  it('a clean delivery has no labels and a slim label band', () => {
    const scene = buildScene(inputFromResult(cleanResult), 1000);
    expect(scene.flags).toEqual([]);
    expect(scene.flagBand).toBeLessThan(30);
    expect(scene.loud.bars.some((b) => b.hot)).toBe(false);
  });

  it('survives a degenerate width and an empty rate series', () => {
    const input = { ...inputFromResult(mixedResult), rate: { t: [], wpm: [] }, corridor: null };
    const scene = buildScene(input, 40);
    expect(scene.rate.line).toBe('');
    expect(scene.rate.corridorLabel).toBeNull();
    expect(scene.loud.bars.length).toBeGreaterThanOrEqual(8);
  });

  it('the illustration is fixed, flagged as an illustration, and carries no time labels or evidence numbers', () => {
    const a = illustrativeInput();
    expect(a.illustrative).toBe(true);
    expect(JSON.stringify(a)).toBe(JSON.stringify(illustrativeInput()));
    const scene = buildScene(a, 900);
    expect(scene.illustrative).toBe(true);
    expect(scene.axis.ticks.every((t) => t.label === '')).toBe(true);
    expect(scene.flags).toHaveLength(1);
    expect(scene.flags[0]!.label).toBe('Deviation');
    expect(scene.flags[0]!.evidence).toBe('');
    expect(scene.flags[0]!.interval).toBe('illustrative');
    expect(scene.rate.corridorLabel).toBe('reference corridor');
  });
});
