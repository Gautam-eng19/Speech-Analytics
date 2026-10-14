import { describe, expect, it } from 'vitest';
import { byWords, evidenceGauge, evidenceHeadline, evidenceRows } from '@/lib/evidence';
import type { Flaw } from '@/api/types';
import { flawOfType, hesitantResult, mixedResult } from './fixtures';

describe('evidence rows', () => {
  it('shows a rate finding with the backend numbers at fixed decimals', () => {
    const f = flawOfType(mixedResult, 'too_fast');
    const rows = evidenceRows(f);
    expect(rows.map((r) => r.label)).toEqual(['Participant rate', 'Baseline, same words', 'Difference', 'z-score', 'Measured over']);   // the samples are judged word by word
    const e = f.evidence as { rate_participant_wpm: number; rate_baseline_mean_wpm: number; rate_baseline_std_wpm: number; rate_delta_wpm: number; rate_z_score: number };
    expect(rows[0]).toMatchObject({ value: e.rate_participant_wpm.toFixed(1), unit: 'words/min' });
    expect(rows[1]!.value).toBe(`${e.rate_baseline_mean_wpm.toFixed(1)} ± ${e.rate_baseline_std_wpm.toFixed(1)}`);
    expect(rows[2]!.value).toBe(`+${e.rate_delta_wpm.toFixed(1)}`);
    expect(rows[3]!.value).toBe(`+${e.rate_z_score.toFixed(2)}`);
  });
  it('names the baseline value for what it is: the same words for a word-by-word finding, the overall mean otherwise', () => {
    const f = flawOfType(mixedResult, 'too_fast');
    expect(byWords(f)).toBe(true);
    const overall = { ...f, rule: { ...f.rule!, feature: 'rate_z' } } as Flaw;
    expect(byWords(overall)).toBe(false);
    expect(evidenceRows(overall).map((r) => r.label)).toEqual(['Participant rate', 'Baseline rate', 'Difference', 'z-score', 'Measured over']);
    expect(evidenceRows(overall)[1]!.hint).toBe('mean ± standard deviation');
    expect(evidenceRows(f)[1]!.hint).toMatch(/same|these words/);
    const quiet = flawOfType(mixedResult, 'low_energy');
    expect(evidenceRows(quiet).map((r) => r.label)).toContain('Baseline, same words');
    expect(evidenceRows({ ...quiet, rule: { ...quiet.rule!, feature: 'energy_z' } } as Flaw).map((r) => r.label)).toContain('Baseline level');
    expect(byWords({ ...f, rule: undefined } as unknown as Flaw)).toBe(false);
  });
  it('shows a pause finding with its boundary type', () => {
    const f = flawOfType(mixedResult, 'excessive_pause');
    const rows = evidenceRows(f);
    const e = f.evidence as { pause_duration_s: number };
    expect(rows[0]).toMatchObject({ label: 'Pause length', value: e.pause_duration_s.toFixed(2) });
    expect(rows.find((r) => r.label === 'Where')?.value).toBe('Cross sentence');
  });
  it('shows a flat-pitch finding with the backend numbers: movement in Hz against the baseline, z-score, voiced share', () => {
    const base = flawOfType(mixedResult, 'too_fast');
    const flat = {
      ...base, type: 'flat_pitch', rule: { feature: 'pitch_run_z', direction: 'below', threshold_z: -4, min_duration_s: 1 },
      evidence: { f0_std_hz_in_window: 4.84, f0_std_baseline_hz: 10.36, f0_std_z: -4.24, f0_voiced_fraction: 0.4306, window_duration_s: 6.14 },
    } as unknown as Flaw;
    const rows = evidenceRows(flat);
    expect(rows.map((r) => r.label)).toEqual(['Participant pitch movement', 'Baseline, same words', 'z-score', 'Voiced speech', 'Measured over']);
    expect(rows[0]).toMatchObject({ value: '4.8', unit: 'Hz' });
    expect(rows[1]).toMatchObject({ value: '10.4', unit: 'Hz' });
    expect(rows[2]!.value).toBe('−4.24');
    expect(rows[3]).toMatchObject({ value: '43', unit: '%' });
    expect(rows[4]).toMatchObject({ value: '6.1', unit: 's' });
    expect(evidenceHeadline(flat)).toBe('4.8 vs 10.4 Hz of movement');
    expect(evidenceGauge(flat)).toBeNull();                                                      // the backend gives no separate spread to draw
    const whole = { ...flat, rule: { ...flat.rule!, feature: 'pitch_z' } } as Flaw;
    expect(evidenceRows(whole)[1]!.label).toBe('Baseline movement');
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
    const rate = flawOfType(mixedResult, 'too_fast').evidence as { rate_participant_wpm: number; rate_baseline_mean_wpm: number };
    expect(evidenceHeadline(flawOfType(mixedResult, 'too_fast'))).toBe(`${Math.round(rate.rate_participant_wpm)} vs ${Math.round(rate.rate_baseline_mean_wpm)} words/min`);
    const pause = flawOfType(mixedResult, 'excessive_pause').evidence as { pause_duration_s: number; pause_baseline_mean_s: number };
    expect(evidenceHeadline(flawOfType(mixedResult, 'excessive_pause'))).toBe(`${pause.pause_duration_s.toFixed(2)} s vs ${pause.pause_baseline_mean_s.toFixed(2)} s`);
  });
});
