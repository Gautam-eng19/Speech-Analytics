import { describe, expect, it } from 'vitest';
import { evidenceGauge, evidenceHeadline, evidenceRows } from '@/lib/evidence';
import type { Flaw } from '@/api/types';
import { flawOfType, hesitantResult, mixedResult } from './fixtures';

describe('evidence rows', () => {
  it('shows a rate finding with the backend numbers at fixed decimals', () => {
    const f = flawOfType(mixedResult, 'too_fast');
    const rows = evidenceRows(f);
    expect(rows.map((r) => r.label)).toEqual(['Participant rate', 'Baseline rate', 'Difference', 'z-score', 'Window']);
    expect(rows[0]).toMatchObject({ value: '197.4', unit: 'words/min' });
    expect(rows[1]!.value).toBe('141.2 ± 11.6');
    expect(rows[2]!.value).toBe('+56.2');
    expect(rows[3]!.value).toBe('+4.83');
  });
  it('shows a pause finding with its boundary type', () => {
    const f = flawOfType(mixedResult, 'excessive_pause');
    const rows = evidenceRows(f);
    const e = f.evidence as { pause_duration_s: number };
    expect(rows[0]).toMatchObject({ label: 'Pause length', value: e.pause_duration_s.toFixed(2) });
    expect(rows.find((r) => r.label === 'Where')?.value).toBe('Cross sentence');
  });
  it('falls back to listing whatever numbers arrive for evidence it does not know', () => {
    const odd = { ...flawOfType(mixedResult, 'too_fast'), evidence: { hf_ratio_z: 2.5, window_duration_s: 3 } } as unknown as Flaw;
    const rows = evidenceRows(odd);
    expect(rows.map((r) => r.label)).toEqual(['Hf ratio z', 'Window duration s']);
    expect(rows[0]!.value).toBe('2.50');
  });
});

describe('evidence gauge', () => {
  it('describes the participant value against the baseline', () => {
    const g = evidenceGauge(flawOfType(hesitantResult, 'too_slow'))!;
    expect(g.unit).toBe('words/min');
    expect(g.value).toBeLessThan(g.mean);
    expect(g.z).toBeLessThan(0);
    expect(g.std).toBeGreaterThan(0);
  });
  it('has a gauge for pauses and none for evidence it cannot draw', () => {
    expect(evidenceGauge(flawOfType(hesitantResult, 'excessive_pause'))!.unit).toBe('s');
    const odd = { ...flawOfType(mixedResult, 'too_fast'), evidence: { hf_ratio_z: 2.5 } } as unknown as Flaw;
    expect(evidenceGauge(odd)).toBeNull();
  });
});

describe('evidence headline', () => {
  it('summarises in one line', () => {
    expect(evidenceHeadline(flawOfType(mixedResult, 'too_fast'))).toBe('197 vs 141 words/min');
    const pause = flawOfType(mixedResult, 'excessive_pause').evidence as { pause_duration_s: number; pause_baseline_mean_s: number };
    expect(evidenceHeadline(flawOfType(mixedResult, 'excessive_pause'))).toBe(`${pause.pause_duration_s.toFixed(2)} s vs ${pause.pause_baseline_mean_s.toFixed(2)} s`);
  });
});
