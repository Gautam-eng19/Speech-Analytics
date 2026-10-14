import type { AnalysisResult } from '@/api/types';
import { extent, niceTicks, scaleLinear } from '@/lib/decimate';
import { fmtLevel, fmtNum } from '@/lib/format';
import type { TimeWindow } from '@/lib/time';

/** The lanes of the timeline and what each one needs to be drawn. Everything is read from the AnalysisResult. */
export type LaneKey = 'axis' | 'flaws' | 'truth' | 'words' | 'loudness' | 'pitch' | 'rate' | 'pauses';

export interface LaneCtx {
  result: AnalysisResult;
  t0: number;
  t1: number;
  width: number;
  x: (t: number) => number;
}

export function makeCtx(result: AnalysisResult, view: TimeWindow, width: number): LaneCtx {
  return { result, t0: view.t0, t1: view.t1, width, x: scaleLinear(view.t0, view.t1, 0, Math.max(1, width)) };
}

export function laneHeights(compact: boolean): Record<LaneKey, number> {
  return compact
    ? { axis: 24, flaws: 36, truth: 22, words: 0, loudness: 72, pitch: 0, rate: 72, pauses: 44 }
    : { axis: 26, flaws: 40, truth: 22, words: 40, loudness: 100, pitch: 100, rate: 92, pauses: 48 };
}

/** A y axis: the value range a lane draws, its tick values, and how to print them. */
export interface YModel {
  domain: [number, number];
  ticks: number[];
  unit: string;
  decimals: number;
}

/** dBFS meter scale. Fixed, so the picture does not rescale when the user zooms; quieter frames sit on the floor. */
export const LOUDNESS_MODEL: YModel = { domain: [-80, 0], ticks: [-60, -40, -20, 0], unit: 'dBFS', decimals: 0 };

export function pitchModel(result: AnalysisResult): YModel | null {
  const bs = result.baseline_stats;
  const data = extent(result.features.f0_timeline.values_hz);
  const lo = Math.min(data?.[0] ?? Infinity, bs.f0_voiced_hz_p05 ?? bs.f0_voiced_hz_mean - 2 * bs.f0_voiced_hz_std);
  const hi = Math.max(data?.[1] ?? -Infinity, bs.f0_voiced_hz_p95 ?? bs.f0_voiced_hz_mean + 2 * bs.f0_voiced_hz_std);
  if (!Number.isFinite(lo) || !Number.isFinite(hi) || hi <= lo) return null;
  const pad = (hi - lo) * 0.1;
  const domain: [number, number] = [Math.floor((lo - pad) / 10) * 10, Math.ceil((hi + pad) / 10) * 10];
  return { domain, ticks: niceTicks(domain[0], domain[1], 3), unit: 'Hz', decimals: 0 };
}

export function rateModel(result: AnalysisResult): YModel | null {
  const bs = result.baseline_stats;
  const data = extent(result.features.speech_rate_timeline.words_per_min);
  const lo = Math.min(data?.[0] ?? Infinity, bs.rate_wpm_mean - 3 * bs.rate_wpm_std);
  const hi = Math.max(data?.[1] ?? -Infinity, bs.rate_wpm_mean + 3 * bs.rate_wpm_std);
  if (!Number.isFinite(lo) || !Number.isFinite(hi) || hi <= lo) return null;
  const domain: [number, number] = [Math.max(0, Math.floor(lo / 10) * 10), Math.ceil(hi / 10) * 10];
  return { domain, ticks: niceTicks(domain[0], domain[1], 3), unit: 'words/min', decimals: 0 };
}

export const LANE_PAD = 7;

export function yScale(model: YModel, height: number): (v: number) => number {
  return scaleLinear(model.domain[1], model.domain[0], LANE_PAD, height - LANE_PAD);
}

export interface LaneLabel {
  name: string;
  /** Second line: unit and the baseline value the lane is compared with. */
  detail: string;
}

/** Text for the label column. Numbers are the backend's baseline statistics, printed with fixed decimals. */
export function laneLabel(key: LaneKey, result: AnalysisResult): LaneLabel {
  const bs = result.baseline_stats;
  switch (key) {
    case 'flaws':
      return { name: 'Findings', detail: `${result.flaws.length} detected` };
    case 'truth':
      return { name: 'Injected', detail: 'known ground truth' };
    case 'words':
      return { name: 'Words', detail: `${result.alignment.length} aligned` };
    case 'loudness':
      return { name: 'Loudness', detail: `dBFS · baseline ${fmtLevel(bs.energy_db_mean, 1)} ± ${fmtNum(bs.energy_db_std, 1)}` };
    case 'pitch':
      return { name: 'Pitch', detail: `Hz · context, not scored · baseline ${fmtNum(bs.f0_voiced_hz_mean, 0)}` };
    case 'rate':
      return { name: 'Speech rate', detail: `words/min · baseline ${fmtNum(bs.rate_wpm_mean, 0)} ± ${fmtNum(bs.rate_wpm_std, 0)}` };
    case 'pauses':
      return { name: 'Pauses', detail: `${result.features.pause_events.length} found · bar height = length` };
    default:
      return { name: '', detail: '' };
  }
}

export function yModelFor(key: LaneKey, result: AnalysisResult): YModel | null {
  if (key === 'loudness') return LOUDNESS_MODEL;
  if (key === 'pitch') return pitchModel(result);
  if (key === 'rate') return rateModel(result);
  return null;
}
