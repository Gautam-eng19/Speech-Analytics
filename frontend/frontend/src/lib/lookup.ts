import type { AlignedWord, AnalysisResult, Flaw, PauseEvent } from '@/api/types';
import { flawsAt, wordIndexAt } from './result';
import { nearestIndex } from './time';

/**
 * What the result says at one moment, found by lookup in the backend's arrays (nearest sample, containing pause, word being spoken).
 * Nothing is interpolated or computed: a value is either read from the result or reported as absent.
 */
export interface CursorReading {
  time: number;
  word: AlignedWord | null;
  loudnessDb: number | null;
  /** null: outside the analysed audio. 'unvoiced': a frame without a pitch estimate. */
  f0Hz: number | 'unvoiced' | null;
  rate: { wpm: number; centre: number } | null;
  pause: PauseEvent | null;
  flaws: Flaw[];
}

/** A frame lookup only counts when the time is within this distance of a frame (frames are 10 ms apart). */
const FRAME_TOLERANCE_S = 0.04;

export function readAt(result: AnalysisResult, time: number): CursorReading {
  const { energy_timeline: energy, f0_timeline: f0, speech_rate_timeline: rate, pause_events } = result.features;

  const ei = nearestIndex(energy.times_s, time);
  const loudnessDb = ei >= 0 && Math.abs((energy.times_s[ei] as number) - time) <= FRAME_TOLERANCE_S ? energy.values_db[ei] ?? null : null;

  const fi = nearestIndex(f0.times_s, time);
  let f0Hz: CursorReading['f0Hz'] = null;
  if (fi >= 0 && Math.abs((f0.times_s[fi] as number) - time) <= FRAME_TOLERANCE_S) {
    const value = f0.values_hz[fi];
    f0Hz = value === null || value === undefined ? 'unvoiced' : value;
  }

  const ri = nearestIndex(rate.times_s, time);
  const rateReading = ri >= 0 ? { wpm: rate.words_per_min[ri] as number, centre: rate.times_s[ri] as number } : null;

  const wi = wordIndexAt(result.alignment, time);
  const candidate = wi >= 0 ? result.alignment[wi] ?? null : null;
  const word = candidate && time <= candidate.end_s ? candidate : null;

  const pause = pause_events.find((e) => time >= e.start_s && time <= e.end_s) ?? null;

  return { time, word, loudnessDb, f0Hz, rate: rateReading, pause, flaws: flawsAt(result.flaws, time) };
}
