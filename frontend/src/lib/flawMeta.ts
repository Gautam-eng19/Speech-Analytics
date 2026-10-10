import type { FlawType } from '@/api/types';
import type { IconName } from '@/components/Icon';

/**
 * Static glossary of flaw types: labels, icons and plain-language definitions.
 * Mirrors ARCHITECTURE.md section 13/17 and DEC-026. `available` is false for flaw types the backend cannot detect yet
 * (flat pitch needs a baseline statistic that does not exist; the P1 types are not implemented).
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
    measured: 'Words per minute over a rolling window, compared with the baseline mean and spread (z-score).',
  },
  too_slow: {
    type: 'too_slow', label: 'Too slow', family: 'rate', icon: 'g-slow', available: true,
    definition: 'Speech rate stayed well below the baseline for a sustained stretch. Long pauses inside the window lower the measured rate.',
    measured: 'Words per minute over a rolling window, compared with the baseline mean and spread (z-score).',
  },
  excessive_pause: {
    type: 'excessive_pause', label: 'Excessive pause', family: 'pause', icon: 'g-pause', available: true,
    definition: 'A silence much longer than the baseline’s pauses of the same kind (inside a phrase, or between sentences).',
    measured: 'Pause length compared with the baseline mean and spread for its boundary type (z-score).',
  },
  low_energy: {
    type: 'low_energy', label: 'Low energy', family: 'energy', icon: 'g-quiet', available: true,
    definition: 'Loudness stayed well below the baseline speaking level.',
    measured: 'Frame loudness in dB compared with the baseline mean and spread (z-score).',
  },
  high_energy: {
    type: 'high_energy', label: 'High energy', family: 'energy', icon: 'g-loud', available: true,
    definition: 'Loudness stayed well above the baseline speaking level.',
    measured: 'Frame loudness in dB compared with the baseline mean and spread (z-score).',
  },
  flat_pitch: {
    type: 'flat_pitch', label: 'Flat pitch', family: 'pitch', icon: 'g-flat', available: false,
    definition: 'Pitch moved much less than in the baseline delivery. Not detected yet: it needs a baseline statistic of pitch variation that does not exist.',
    measured: 'Pitch variation inside a window compared with the baseline.',
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

/** Score dimensions (FeatureName). `pitch` has no detector yet, so it is never part of the composite. */
export const SCORE_DIMENSIONS = [
  { key: 'speech_rate', label: 'Speech rate', flaws: ['too_fast', 'too_slow'] },
  { key: 'pauses', label: 'Pauses', flaws: ['excessive_pause'] },
  { key: 'energy', label: 'Energy', flaws: ['low_energy', 'high_energy'] },
  { key: 'pitch', label: 'Pitch', flaws: ['flat_pitch'] },
] as const;
