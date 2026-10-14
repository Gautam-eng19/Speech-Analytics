import type { FlawType } from '@/api/types';
import type { IconName } from '@/components/Icon';

/**
 * Static glossary of flaw types: labels, icons and plain-language definitions.
 * Mirrors ARCHITECTURE.md section 13/17 and DEC-026. `available` is false for flaw types the backend cannot detect yet
 * (the P1 types are not implemented; flat pitch has been detected word by word since DEC-042).
 */
export type FlawFamily = 'rate' | 'pause' | 'energy' | 'pitch' | 'clarity';

export interface FlawMeta {
  type: FlawType;
  label: string;
  family: FlawFamily;
  icon: IconName;
  available: boolean;
  /** One-sentence definition of what the finding means. */
  definition: string;
  /** What the measured evidence is, in the backend's terms. */
  measured: string;
}

export const FLAW_ORDER: FlawType[] = [
  'too_fast', 'too_slow', 'excessive_pause', 'low_energy', 'high_energy', 'flat_pitch', 'pitch_instability', 'reduced_clarity',
];

export const FLAW_META: Record<FlawType, FlawMeta> = {
  too_fast: {
    type: 'too_fast', label: 'Too fast', family: 'rate', icon: 'g-fast', available: true,
    definition: 'Speech rate stayed well above the baseline for a sustained stretch.',
    measured: 'Words per minute over a run of words, compared with the pace the baseline readings had for those same words. (A baseline without a word-by-word profile: a rolling window against the overall mean and spread.)',
  },
  too_slow: {
    type: 'too_slow', label: 'Too slow', family: 'rate', icon: 'g-slow', available: true,
    definition: 'Speech rate stayed well below the baseline for a sustained stretch. Pauses are judged on their own: only a short silence after a word counts towards its pace.',
    measured: 'Words per minute over a run of words, compared with the pace the baseline readings had for those same words. (A baseline without a word-by-word profile: a rolling window against the overall mean and spread.)',
  },
  excessive_pause: {
    type: 'excessive_pause', label: 'Excessive pause', family: 'pause', icon: 'g-pause', available: true,
    definition: 'A silence much longer than the baseline’s pauses of the same kind (inside a phrase, or between sentences).',
    measured: 'Pause length compared with the baseline mean and spread for its boundary type (z-score).',
  },
  low_energy: {
    type: 'low_energy', label: 'Low energy', family: 'energy', icon: 'g-quiet', available: true,
    definition: 'Loudness stayed well below the baseline speaking level.',
    measured: 'Loudness of a run of words in dB, compared with the level the baseline readings had for those same words, after removing the recording’s overall level. (A baseline without a word-by-word profile: frame loudness against the overall mean and spread.)',
  },
  high_energy: {
    type: 'high_energy', label: 'High energy', family: 'energy', icon: 'g-loud', available: true,
    definition: 'Loudness stayed well above the baseline speaking level.',
    measured: 'Loudness of a run of words in dB, compared with the level the baseline readings had for those same words, after removing the recording’s overall level. (A baseline without a word-by-word profile: frame loudness against the overall mean and spread.)',
  },
  flat_pitch: {
    type: 'flat_pitch', label: 'Flat pitch', family: 'pitch', icon: 'g-flat', available: true,
    definition: 'The voice moved much less than in the baseline delivery of the same words: a more monotone stretch.',
    measured: 'How far the pitch of a run of words moves around the recording’s own median pitch (in Hz), compared with how far the baseline readings moved on those same words. Needs a baseline with a pitch profile.',
  },
  pitch_instability: {
    type: 'pitch_instability', label: 'Pitch instability', family: 'pitch', icon: 'g-unstable', available: false,
    definition: 'Erratic pitch jumps compared with the baseline. Planned (P1); not detected yet.',
    measured: 'Pitch variability inside a window compared with the baseline.',
  },
  reduced_clarity: {
    type: 'reduced_clarity', label: 'Reduced clarity', family: 'clarity', icon: 'g-clarity', available: false,
    definition: 'Loss of high-frequency energy, an acoustic proxy for muffled articulation. Planned (P1); not detected yet.',
    measured: 'High-frequency energy ratio compared with the baseline.',
  },
};

export function flawMeta(type: string): FlawMeta {
  return (FLAW_META as Record<string, FlawMeta | undefined>)[type] ?? {
    type: type as FlawType, label: type.replace(/_/g, ' '), family: 'rate', icon: 'flag', available: false,
    definition: 'Unknown finding type.', measured: '',
  };
}

export const flawColor = (type: string): string => `var(--f-${type})`;

/** Score dimensions (FeatureName). `pitch` is part of the composite only when the baseline has a pitch profile (otherwise the analysis says it was not checked). */
export const SCORE_DIMENSIONS = [
  { key: 'speech_rate', label: 'Speech rate', flaws: ['too_fast', 'too_slow'] },
  { key: 'pauses', label: 'Pauses', flaws: ['excessive_pause'] },
  { key: 'energy', label: 'Energy', flaws: ['low_energy', 'high_energy'] },
  { key: 'pitch', label: 'Pitch', flaws: ['flat_pitch'] },
] as const;
