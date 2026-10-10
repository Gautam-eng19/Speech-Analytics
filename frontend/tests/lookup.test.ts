import { describe, expect, it } from 'vitest';
import { readAt } from '@/lib/lookup';
import { tinyResult } from './fixtures';

describe('readAt', () => {
  const r = tinyResult();
  it('reads values at a frame', () => {
    const at = readAt(r, 1.02);
    expect(at.loudnessDb).toBe(-18);
    expect(at.f0Hz).toBe(152);
    expect(at.word?.word).toBe('one');
  });
  it('reports unvoiced frames explicitly', () => {
    expect(readAt(r, 1.0).f0Hz).toBe('unvoiced');
  });
  it('reports times outside the analysed audio as absent, not as zero', () => {
    const at = readAt(r, 0.2);
    expect(at.loudnessDb).toBeNull();
    expect(at.f0Hz).toBeNull();
    expect(at.word).toBeNull();
  });
  it('reports the gap between words as no word', () => {
    expect(readAt(r, 1.7).word).toBeNull();
  });
  it('finds the pause that contains the time', () => {
    expect(readAt(r, 1.7).pause?.duration_s).toBe(0.5);
    expect(readAt(r, 2.2).pause).toBeNull();
  });
  it('uses the nearest rate window and says where it is centred', () => {
    expect(readAt(r, 2.4).rate).toEqual({ wpm: 120, centre: 2 });
    expect(readAt(r, 5.9).rate).toEqual({ wpm: 140, centre: 6 });
  });
});
