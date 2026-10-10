import type { AnalysisResult, SampleIndex } from '@/api/types';
import type { LoadedAnalysis } from '@/state/analysis';
import cleanJson from '../public/samples/clean-delivery.json';
import hesitantJson from '../public/samples/hesitant-delivery.json';
import indexJson from '../public/samples/index.json';
import mixedJson from '../public/samples/mixed-flaws.json';
import rushedJson from '../public/samples/rushed-explanation.json';

/**
 * The shipped demo samples double as fixtures: they are real AnalysisResults produced by the backend's pipeline, so these tests also
 * check that the dashboard's types and helpers fit what the backend actually returns.
 */
export const cleanResult = cleanJson as unknown as AnalysisResult;
export const hesitantResult = hesitantJson as unknown as AnalysisResult;
export const mixedResult = mixedJson as unknown as AnalysisResult;
export const rushedResult = rushedJson as unknown as AnalysisResult;
export const sampleIndex = indexJson as unknown as SampleIndex;

export function loaded(result: AnalysisResult, overrides: Partial<LoadedAnalysis> = {}): LoadedAnalysis {
  const entry = sampleIndex.samples.find((s) => s.analysis_id === result.analysis_id) ?? null;
  return {
    id: result.analysis_id,
    result,
    source: entry ? 'sample' : 'upload',
    title: entry?.title ?? 'Test recording',
    audioUrl: null,
    sample: entry,
    loadedAt: 0,
    ...overrides,
  };
}

export function flawOfType(result: AnalysisResult, type: string) {
  const flaw = result.flaws.find((f) => f.type === type);
  if (!flaw) throw new Error(`fixture has no ${type} finding`);
  return flaw;
}

/** A small hand-made result for edge cases (no findings, short arrays) that is easy to reason about. */
export function tinyResult(overrides: Partial<AnalysisResult> = {}): AnalysisResult {
  return {
    api_contract_version: '1.2.0',
    analysis_id: 'tiny-0001',
    config_version: '1.0.0',
    pipeline_version: '1.0.0',
    audio: { sha256: 'a'.repeat(64), duration_s: 10, sample_rate_hz: 16000, channels: 1, peak_dbfs: -3, trim_start_s: 1, source_duration_s: 12 },
    baseline: { baseline_id: 'b1', passage_id: 'p1', sha256: 'b'.repeat(64), dataset_version: 'test' },
    alignment_method: 'manual',
    transcript: 'one two three',
    alignment: [
      { word: 'one', start_s: 1.0, end_s: 1.5, confidence: 0.9 },
      { word: 'two', start_s: 2.0, end_s: 2.5, confidence: 0.8 },
      { word: 'three', start_s: 3.0, end_s: 3.6, confidence: 0.7 },
    ],
    features: {
      f0_timeline: { times_s: [1.0, 1.01, 1.02, 1.03], values_hz: [null, 150, 152, null], voiced: [false, true, true, false] },
      energy_timeline: { times_s: [1.0, 1.01, 1.02, 1.03], values_db: [-60, -20, -18, -50] },
      speech_rate_timeline: { times_s: [2.0, 6.0], words_per_min: [120, 140] },
      pause_events: [{ start_s: 1.5, end_s: 2.0, duration_s: 0.5, detection_source: 'both', boundary_type: 'within_phrase' }],
    },
    baseline_stats: {
      f0_voiced_hz_mean: 150, f0_voiced_hz_std: 10, energy_db_mean: -25, energy_db_std: 8, rate_wpm_mean: 130, rate_wpm_std: 10,
      pause_within_phrase_mean_s: 0.2, pause_within_phrase_std_s: 0.05, pause_cross_sentence_mean_s: 0.5,
    },
    flaws: [],
    scores: { composite_score: 100, scoring_version: '1.0.0', feature_scores: {} },
    processing_meta: { cached: false, processing_time_s: 1.5, transcript_source: 'manual' },
    notes: [],
    ...overrides,
  } as AnalysisResult;
}
