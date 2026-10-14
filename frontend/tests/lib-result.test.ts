import { describe, expect, it } from 'vitest';
import { adjacentFlaw, analysedSpan, dimensionOf, findFlaw, flawsAt, flawsByTime, flawsBySeverity, recordingDuration, wordIndexAt, wordsInRange } from '@/lib/result';
import { hesitantResult, mixedResult, tinyResult } from './fixtures';

describe('durations', () => {
  it('uses the length of the uploaded file for the timeline', () => {
    const r = tinyResult();
    expect(recordingDuration(r)).toBe(12);
    expect(analysedSpan(r)).toEqual({ start: 1, end: 11 });
  });
  it('falls back to trim offset plus analysed length', () => {
    const r = tinyResult();
    r.audio.source_duration_s = null;
    expect(recordingDuration(r)).toBe(11);
  });
});

describe('flaw ordering and lookup', () => {
  it('orders by time and by severity without changing the original', () => {
    const original = [...mixedResult.flaws];
    const byTime = flawsByTime(mixedResult.flaws);
    expect(byTime.map((f) => f.start_s)).toEqual([...byTime.map((f) => f.start_s)].sort((a, b) => a - b));
    const bySeverity = flawsBySeverity(hesitantResult.flaws);
    expect(bySeverity[0]!.severity).toBeGreaterThanOrEqual(bySeverity[bySeverity.length - 1]!.severity);
    expect(mixedResult.flaws).toEqual(original);
  });
  it('finds a flaw by id', () => {
    const first = mixedResult.flaws[0]!;
    expect(findFlaw(mixedResult, first.flaw_id)).toBe(first);
    expect(findFlaw(mixedResult, 'nope')).toBeNull();
    expect(findFlaw(mixedResult, null)).toBeNull();
  });
  it('steps to the next and previous flaw in time', () => {
    const ordered = flawsByTime(hesitantResult.flaws);
    const first = ordered[0]!;
    const second = ordered[1]!;
    expect(adjacentFlaw(ordered, 0, 1)).toBe(first);
    expect(adjacentFlaw(ordered, first.start_s, 1)).toBe(second);
    expect(adjacentFlaw(ordered, second.start_s, -1)).toBe(first);
    expect(adjacentFlaw(ordered, 0, -1)).toBeNull();
    expect(adjacentFlaw(ordered, 9999, 1)).toBeNull();
  });
  it('lists the flaws that cover a moment', () => {
    const f = mixedResult.flaws[0]!;
    expect(flawsAt(mixedResult.flaws, (f.start_s + f.end_s) / 2).map((x) => x.flaw_id)).toContain(f.flaw_id);
    expect(flawsAt(mixedResult.flaws, -1)).toEqual([]);
  });
});

describe('words', () => {
  const words = tinyResult().alignment;
  it('finds the word that has started', () => {
    expect(wordIndexAt(words, 0.5)).toBe(-1);
    expect(wordIndexAt(words, 1.2)).toBe(0);
    expect(wordIndexAt(words, 2.0)).toBe(1);
    expect(wordIndexAt(words, 99)).toBe(2);
  });
  it('lists words whose midpoint is inside an interval', () => {
    expect(wordsInRange(words, 0.9, 2.6)).toEqual([0, 1]);
    expect(wordsInRange(words, 2.1, 3.0)).toEqual([1]);
    expect(wordsInRange(words, 10, 20)).toEqual([]);
  });
});

describe('dimensions', () => {
  it('maps flaw types to the score dimension they belong to', () => {
    expect(dimensionOf('too_fast')).toBe('speech_rate');
    expect(dimensionOf('too_slow')).toBe('speech_rate');
    expect(dimensionOf('excessive_pause')).toBe('pauses');
    expect(dimensionOf('low_energy')).toBe('energy');
    expect(dimensionOf('high_energy')).toBe('energy');
    expect(dimensionOf('flat_pitch')).toBe('pitch');
    expect(dimensionOf('reduced_clarity')).toBeNull();
  });
});
