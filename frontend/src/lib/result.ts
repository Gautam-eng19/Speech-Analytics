import type { AnalysisResult, Flaw, AlignedWord } from '@/api/types';

/**
 * Small, display-oriented helpers over an AnalysisResult. They locate things (a word at a time, the flaws that overlap a range) and
 * order lists. They never derive a measurement: durations, scores and severities are always read from the result.
 */

/** Length of the uploaded recording on its own timeline (the timeline every time in the result refers to). */
export function recordingDuration(result: AnalysisResult): number {
  return result.audio.source_duration_s ?? result.audio.trim_start_s + result.audio.duration_s;
}

/** The part of the recording that was analysed (leading and trailing silence were trimmed off). */
export function analysedSpan(result: AnalysisResult): { start: number; end: number } {
  return { start: result.audio.trim_start_s, end: result.audio.trim_start_s + result.audio.duration_s };
}

export function flawsByTime(flaws: readonly Flaw[]): Flaw[] {
  return [...flaws].sort((a, b) => a.start_s - b.start_s || a.end_s - b.end_s);
}

export function flawsBySeverity(flaws: readonly Flaw[]): Flaw[] {
  return [...flaws].sort((a, b) => b.severity - a.severity || a.start_s - b.start_s);
}

export function findFlaw(result: AnalysisResult, flawId: string | null | undefined): Flaw | null {
  return flawId ? result.flaws.find((f) => f.flaw_id === flawId) ?? null : null;
}

/** Index of the flaw before / after a time, in time order (wrapping is left to the caller). */
export function adjacentFlaw(flaws: readonly Flaw[], time: number, direction: 1 | -1): Flaw | null {
  const ordered = flawsByTime(flaws);
  if (direction === 1) return ordered.find((f) => f.start_s > time + 0.05) ?? null;
  for (let i = ordered.length - 1; i >= 0; i--) if (ordered[i]!.start_s < time - 0.05) return ordered[i]!;
  return null;
}

export function flawsAt(flaws: readonly Flaw[], time: number): Flaw[] {
  return flaws.filter((f) => time >= f.start_s && time <= f.end_s);
}

/** Index of the word being spoken at `time` (the last word that has started), or -1 before the first one. */
export function wordIndexAt(words: readonly AlignedWord[], time: number): number {
  let lo = 0;
  let hi = words.length - 1;
  let answer = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if ((words[mid] as AlignedWord).start_s <= time) {
      answer = mid;
      lo = mid + 1;
    } else hi = mid - 1;
  }
  return answer;
}

/** The score dimension (FeatureName) that a flaw type belongs to, as the backend scores it. */
export function dimensionOf(flawType: string): 'speech_rate' | 'pauses' | 'energy' | 'pitch' | null {
  switch (flawType) {
    case 'too_fast':
    case 'too_slow':
      return 'speech_rate';
    case 'excessive_pause':
      return 'pauses';
    case 'low_energy':
    case 'high_energy':
      return 'energy';
    case 'flat_pitch':
    case 'pitch_instability':
      return 'pitch';
    default:
      return null;
  }
}

/** Words whose midpoint lies inside [start, end], used to underline a flaw in the transcript. */
export function wordsInRange(words: readonly AlignedWord[], start: number, end: number): number[] {
  const hit: number[] = [];
  words.forEach((w, i) => {
    const mid = (w.start_s + w.end_s) / 2;
    if (mid >= start && mid <= end) hit.push(i);
  });
  return hit;
}
