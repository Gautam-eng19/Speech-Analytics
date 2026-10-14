import type { AnalysisResult } from '@/api/types';
import { flawsByTime } from './result';

/** RFC 4180: a field containing a comma, a quote or a line break is quoted, and quotes inside it are doubled. */
export function csvField(value: unknown): string {
  if (value === null || value === undefined) return '';
  const text = typeof value === 'string' ? value : String(value);
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

export function toCsv(rows: unknown[][]): string {
  return rows.map((row) => row.map(csvField).join(',')).join('\r\n') + '\r\n';
}

const BASE_COLUMNS = [
  'flaw_id', 'type', 'start_s', 'end_s', 'duration_s', 'severity', 'reliability', 'low_confidence',
  'rule_feature', 'rule_direction', 'rule_threshold_z', 'rule_min_duration_s', 'explanation_method', 'explanation', 'recommendation',
  'affected_words', 'warnings',
] as const;

/**
 * The findings of an analysis as a table for a spreadsheet: one row per finding in time order, every value exactly as the backend
 * returned it (no rounding), the evidence flattened into `evidence.<field>` columns. A UTF-8 byte-order mark makes Excel read the
 * typographic quotes and dashes in the explanations correctly.
 */
export function findingsCsv(result: AnalysisResult): string {
  const flaws = flawsByTime(result.flaws);
  const evidenceKeys: string[] = [];
  for (const flaw of flaws) for (const key of Object.keys(flaw.evidence)) if (!evidenceKeys.includes(key)) evidenceKeys.push(key);
  const header = [...BASE_COLUMNS, ...evidenceKeys.map((key) => `evidence.${key}`)];
  const rows = flaws.map((f) => {
    const evidence = f.evidence as unknown as Record<string, unknown>;
    return [
      f.flaw_id, f.type, f.start_s, f.end_s, f.duration_s, f.severity, f.reliability, f.low_confidence,
      f.rule?.feature, f.rule?.direction, f.rule?.threshold_z, f.rule?.min_duration_s, f.explanation_method, f.explanation, f.recommendation,
      (f.affected_words ?? []).join(' '), (f.warnings ?? []).join(' | '),
      ...evidenceKeys.map((key) => evidence[key]),
    ];
  });
  return '﻿' + toCsv([header, ...rows]);
}
