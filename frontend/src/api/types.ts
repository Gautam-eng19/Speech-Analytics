import type { components } from './schema';

/**
 * Friendly names for the API's types. They are all derived from `schema.d.ts`, which is generated from the backend's OpenAPI
 * document (`npm run gen:types`); nothing here is hand-written or hand-extended (api-contract.md).
 */
type S = components['schemas'];

export type AnalysisResult = S['AnalysisResult'];
export type AnalysisNote = S['AnalysisNote'];
export type AlignedWord = S['AlignedWord'];
export type AudioInfo = S['AudioInfo'];
export type BaselineInfo = S['BaselineInfo'];
export type BaselineStats = S['BaselineStats'];
export type BaselineSummary = S['BaselineSummary'];
export type UnavailableBaseline = S['UnavailableBaseline'];
export type BaselineListResponse = S['BaselineListResponse'];
export type DetectionRule = S['DetectionRule'];
export type ErrorCode = S['ErrorCode'];
export type ErrorResponse = S['ErrorResponse'];
export type FeatureScore = S['FeatureScore'];
export type FeatureSet = S['FeatureSet'];
export type Flaw = S['Flaw'];
export type FlawType = S['FlawType'];
export type HealthResponse = S['HealthResponse'];
export type PauseEvent = S['PauseEvent'];
export type ProcessingMeta = S['ProcessingMeta'];
export type ScoreSummary = S['ScoreSummary'];
export type StatusResponse = S['StatusResponse'];

export type RateEvidence = S['RateEvidence'];
export type EnergyEvidence = S['EnergyEvidence'];
export type PauseEvidence = S['PauseEvidence'];
export type FlatPitchEvidence = S['FlatPitchEvidence'];
export type PitchInstabilityEvidence = S['PitchInstabilityEvidence'];
export type ClarityEvidence = S['ClarityEvidence'];
export type Evidence = Flaw['evidence'];

/** Where the dashboard got an analysis from. */
export type AnalysisSource = 'upload' | 'sample' | 'history';

/** One entry of samples/index.json (written by scripts/demo/build_demo_samples.py). */
export interface SampleInjected {
  type: FlawType;
  start_s: number;
  end_s: number;
  /** Outcome computed when the sample was built: did the real pipeline find this injected flaw? */
  detected: boolean;
}

export interface SampleEntry {
  id: string;
  title: string;
  description: string;
  analysis_id: string;
  audio: string;
  result: string;
  duration_s: number;
  injected: SampleInjected[];
  extra_detections: number;
  seed: number;
  candidates_tried: number;
}

export interface SampleIndex {
  synthetic: true;
  generator: string;
  voice: string;
  note: string;
  selection_note: string;
  diagnostics: { clean_takes_flagged: number; clean_takes_probed: number; comment: string };
  passage: { passage_id: string; title: string; text: string; word_count: number };
  baseline: { baseline_id: string; takes: number; sha256: string };
  samples: SampleEntry[];
}
