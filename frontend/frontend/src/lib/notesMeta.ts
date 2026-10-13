import type { IconName } from '@/components/Icon';

/**
 * Presentation of the backend's `notes[]`. The backend decides WHAT is a limitation and writes the message; this file only groups
 * notes and picks an icon. Unknown codes are still shown in full (a note is never dropped because the dashboard has not heard of it).
 */
export type NoteCategory = 'calibration' | 'baseline' | 'audio' | 'alignment' | 'scoring' | 'input' | 'system';
export type NoteLevel = 'caution' | 'info';

export interface NoteMeta {
  category: NoteCategory;
  level: NoteLevel;
  title: string;
}

export const NOTE_CATEGORY_LABEL: Record<NoteCategory, string> = {
  calibration: 'Calibration',
  baseline: 'Baseline',
  audio: 'Recording',
  alignment: 'Word alignment',
  scoring: 'Scoring scope',
  input: 'Input',
  system: 'System',
};

export const NOTE_CATEGORY_ORDER: NoteCategory[] = ['calibration', 'baseline', 'scoring', 'audio', 'alignment', 'input', 'system'];

const KNOWN: Record<string, NoteMeta> = {
  thresholds_uncalibrated: { category: 'calibration', level: 'caution', title: 'Thresholds are not calibrated' },
  baseline_thin_rate: { category: 'baseline', level: 'caution', title: 'Thin baseline: speech rate' },
  baseline_thin_pauses: { category: 'baseline', level: 'caution', title: 'Thin baseline: pauses' },
  pauses_not_comparable: { category: 'baseline', level: 'info', title: 'Some pauses cannot be compared' },
  audio_very_quiet: { category: 'audio', level: 'caution', title: 'Very quiet recording' },
  mfcc_unavailable: { category: 'audio', level: 'info', title: 'MFCC summary unavailable' },
  alignment_warning: { category: 'alignment', level: 'caution', title: 'Alignment warning' },
  words_without_timing: { category: 'alignment', level: 'info', title: 'Words without timing' },
  passage_text_unavailable: { category: 'input', level: 'info', title: 'Passage text unavailable' },
  content_mismatch: { category: 'input', level: 'caution', title: 'Transcript differs from the passage' },
  speaker_gender_ignored: { category: 'input', level: 'info', title: 'Speaker hint ignored' },
  result_not_stored: { category: 'system', level: 'caution', title: 'Result was not saved' },
  explanation_provider_unavailable: { category: 'system', level: 'info', title: 'Explanation provider unavailable' },
  explanation_fallback_used: { category: 'system', level: 'info', title: 'Fallback explanation used' },
};

export function noteMeta(code: string): NoteMeta {
  const known = KNOWN[code];
  if (known) return known;
  if (code.endsWith('_not_scored')) {
    const dimension = code.slice(0, -'_not_scored'.length).replace(/_/g, ' ');
    return { category: 'scoring', level: 'info', title: `${capitalise(dimension)} is not scored` };
  }
  if (code.endsWith('_unavailable')) {
    const feature = code.slice(0, -'_unavailable'.length).replace(/_/g, ' ');
    return { category: 'scoring', level: 'caution', title: `${capitalise(feature)} analysis unavailable` };
  }
  return { category: 'system', level: 'info', title: capitalise(code.replace(/_/g, ' ')) };
}

export const NOTE_ICON: Record<NoteLevel, IconName> = { caution: 'alert-triangle', info: 'info' };

function capitalise(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}
