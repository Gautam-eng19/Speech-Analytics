import type { Evidence, EnergyEvidence, FlatPitchEvidence, Flaw, PauseEvidence, RateEvidence } from '@/api/types';
import { fmtLevel, fmtNum, fmtSigned, titleCase } from './format';

/**
 * Turns a flaw's typed evidence into rows and a gauge for display. Every number is the backend's; this file only chooses labels,
 * units and decimals, using the same fixed decimals as the backend's own explanation text (1 for rates and dB, 2 for z-scores).
 */
export interface EvidenceRow {
  label: string;
  value: string;
  unit?: string;
  hint?: string;
}

/** What the evidence gauge draws: the participant value against the baseline's mean and spread. All values come from the backend. */
export interface EvidenceGauge {
  label: string;
  unit: string;
  value: number;
  mean: number;
  std: number;
  z: number;
  decimals: number;
}

const isRate = (e: Evidence): e is RateEvidence => 'rate_z_score' in e;
const isEnergy = (e: Evidence): e is EnergyEvidence => 'energy_z_score' in e;
const isPause = (e: Evidence): e is PauseEvidence => 'pause_z_score' in e;
const isFlatPitch = (e: Evidence): e is FlatPitchEvidence => 'f0_std_z' in e;

export function evidenceGauge(flaw: Flaw): EvidenceGauge | null {
  const e = flaw.evidence;
  if (isRate(e)) {
    return { label: 'Speech rate', unit: 'words/min', value: e.rate_participant_wpm, mean: e.rate_baseline_mean_wpm, std: e.rate_baseline_std_wpm, z: e.rate_z_score, decimals: 1 };
  }
  if (isEnergy(e)) {
    return { label: 'Loudness', unit: 'dBFS', value: e.energy_mean_db, mean: e.energy_baseline_mean_db, std: e.energy_baseline_std_db, z: e.energy_z_score, decimals: 1 };
  }
  if (isPause(e)) {
    return { label: 'Pause length', unit: 's', value: e.pause_duration_s, mean: e.pause_baseline_mean_s, std: e.pause_baseline_std_s, z: e.pause_z_score, decimals: 2 };
  }
  return null;
}

/** True for a finding judged word by word against how the baseline readings read the same words (the backend's rule says so). */
export const byWords = (flaw: Flaw): boolean => /_(run|overall)_z$/.test(flaw.rule?.feature ?? '');

export function evidenceRows(flaw: Flaw): EvidenceRow[] {
  const e = flaw.evidence;
  const same = byWords(flaw);
  if (isRate(e)) {
    return [
      { label: 'Participant rate', value: fmtNum(e.rate_participant_wpm, 1), unit: 'words/min' },
      { label: same ? 'Baseline, same words' : 'Baseline rate', value: `${fmtNum(e.rate_baseline_mean_wpm, 1)} ± ${fmtNum(e.rate_baseline_std_wpm, 1)}`, unit: 'words/min', hint: same ? 'what the baseline readings had for these words ± spread' : 'mean ± standard deviation' },
      { label: 'Difference', value: `${fmtSigned(e.rate_delta_wpm, 1)}`, unit: 'words/min', hint: `${fmtSigned(e.rate_delta_pct, 1)} % of the baseline ${same ? 'value' : 'mean'}` },
      { label: 'z-score', value: fmtSigned(e.rate_z_score, 2), hint: `peak ${fmtSigned(e.peak_z_score, 2)}` },
      { label: 'Measured over', value: fmtNum(e.window_duration_s, 1), unit: 's', hint: `${e.word_count_in_window} words` },
    ];
  }
  if (isEnergy(e)) {
    return [
      { label: 'Participant level', value: fmtLevel(e.energy_mean_db, 1), unit: 'dBFS' },
      { label: same ? 'Baseline, same words' : 'Baseline level', value: `${fmtLevel(e.energy_baseline_mean_db, 1)} ± ${fmtNum(e.energy_baseline_std_db, 1)}`, unit: 'dBFS', hint: same ? 'what the baseline readings had for these words ± spread' : 'mean ± standard deviation' },
      { label: 'Difference', value: fmtSigned(e.energy_delta_db, 1), unit: 'dB' },
      { label: 'z-score', value: fmtSigned(e.energy_z_score, 2) },
      { label: 'Measured over', value: fmtNum(e.window_duration_s, 1), unit: 's' },
    ];
  }
  if (isPause(e)) {
    return [
      { label: 'Pause length', value: fmtNum(e.pause_duration_s, 2), unit: 's' },
      { label: 'Baseline pause', value: `${fmtNum(e.pause_baseline_mean_s, 2)} ± ${fmtNum(e.pause_baseline_std_s, 2)}`, unit: 's', hint: `${titleCase(e.boundary_type)} pauses` },
      { label: 'Difference', value: fmtSigned(e.pause_delta_s, 2), unit: 's' },
      { label: 'z-score', value: fmtSigned(e.pause_z_score, 2) },
      { label: 'Where', value: titleCase(e.boundary_type), hint: `detected by ${e.detection_source}` },
    ];
  }
  if (isFlatPitch(e)) {
    // The backend gives the movement of the pitch in Hz (the root-mean-square distance from the recording's median pitch) and no separate spread.
    return [
      { label: 'Participant pitch movement', value: fmtNum(e.f0_std_hz_in_window, 1), unit: 'Hz', hint: 'how far the pitch moved around its usual level' },
      { label: same ? 'Baseline, same words' : 'Baseline movement', value: fmtNum(e.f0_std_baseline_hz, 1), unit: 'Hz', hint: 'what the baseline readings moved on these words' },
      { label: 'z-score', value: fmtSigned(e.f0_std_z, 2), hint: 'negative: the voice moved less than the baseline' },
      { label: 'Voiced speech', value: fmtNum(100 * e.f0_voiced_fraction, 0), unit: '%', hint: 'only voiced speech has a pitch' },
      { label: 'Measured over', value: fmtNum(e.window_duration_s, 1), unit: 's' },
    ];
  }
  // Not produced by the current backend; show whatever numbers arrive instead of hiding them.
  return Object.entries(e as unknown as Record<string, unknown>).map(([key, value]) => ({
    label: titleCase(key),
    value: typeof value === 'number' ? fmtNum(value, 2) : String(value),
  }));
}

/** Short one-line summary of the evidence for list rows, built from backend values. */
export function evidenceHeadline(flaw: Flaw): string {
  const e = flaw.evidence;
  if (isRate(e)) return `${fmtNum(e.rate_participant_wpm, 0)} vs ${fmtNum(e.rate_baseline_mean_wpm, 0)} words/min`;
  if (isEnergy(e)) return `${fmtSigned(e.energy_delta_db, 1)} dB vs baseline`;
  if (isPause(e)) return `${fmtNum(e.pause_duration_s, 2)} s vs ${fmtNum(e.pause_baseline_mean_s, 2)} s`;
  if (isFlatPitch(e)) return `${fmtNum(e.f0_std_hz_in_window, 1)} vs ${fmtNum(e.f0_std_baseline_hz, 1)} Hz of movement`;
  return '';
}
