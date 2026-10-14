import { describe, expect, it } from 'vitest';
import { matchScore } from '@/app/CommandPalette';
import { NOTE_CATEGORY_ORDER, noteMeta } from '@/lib/notesMeta';
import { FLAW_META, FLAW_ORDER, flawMeta } from '@/lib/flawMeta';

describe('noteMeta', () => {
  it('knows the notes the backend sends', () => {
    expect(noteMeta('thresholds_uncalibrated')).toMatchObject({ category: 'calibration', level: 'caution' });
    expect(noteMeta('baseline_thin_rate').category).toBe('baseline');
  });
  it('recognises the not-scored and unavailable patterns', () => {
    expect(noteMeta('pitch_not_scored')).toMatchObject({ category: 'scoring', title: 'Pitch is not scored' });
    expect(noteMeta('energy_unavailable')).toMatchObject({ category: 'scoring', level: 'caution' });
  });
  it('still shows a note it has never heard of', () => {
    expect(noteMeta('brand_new_code')).toMatchObject({ category: 'system', title: 'Brand new code' });
  });
  it('lists every category once, in display order', () => {
    expect(new Set(NOTE_CATEGORY_ORDER).size).toBe(NOTE_CATEGORY_ORDER.length);
  });
});

describe('flaw glossary', () => {
  it('covers every flaw type in the vocabulary', () => {
    expect(FLAW_ORDER).toHaveLength(8);
    for (const type of FLAW_ORDER) {
      const meta = FLAW_META[type];
      expect(meta.label.length).toBeGreaterThan(0);
      expect(meta.definition.length).toBeGreaterThan(10);
    }
  });
  it('marks the types the backend cannot detect yet: flat pitch is detected word by word, instability and clarity are not', () => {
    expect(FLAW_META.flat_pitch.available).toBe(true);
    expect(FLAW_META.pitch_instability.available).toBe(false);
    expect(FLAW_META.reduced_clarity.available).toBe(false);
    expect(FLAW_META.too_fast.available).toBe(true);
  });
  it('titles the note that says flat pitch was not checked', () => {
    expect(noteMeta('pitch_not_judged')).toEqual({ category: 'scoring', level: 'caution', title: 'Flat pitch was not checked' });
  });
  it('degrades gracefully for an unknown type', () => {
    expect(flawMeta('mystery_flaw')).toMatchObject({ label: 'mystery flaw', available: false });
  });
});

describe('matchScore', () => {
  it('matches only when every token is present', () => {
    expect(matchScore('too fast', 'Too fast, 0.5–12.6 s')).not.toBeNull();
    expect(matchScore('too slow', 'Too fast, 0.5–12.6 s')).toBeNull();
  });
  it('ranks earlier and word-start matches ahead', () => {
    const early = matchScore('lib', 'Library')!;
    const late = matchScore('lib', 'Open the library')!;
    expect(early).toBeLessThan(late);
  });
  it('matches everything for an empty query and ignores case', () => {
    expect(matchScore('', 'anything')).toBe(0);
    expect(matchScore('LIBRARY', 'library')).not.toBeNull();
  });
});
